import logging
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

import httpx

from explainlaw.collector.repository import parse_api_date
from explainlaw.config import settings
from explainlaw.pravo.models import PravoDocumentsPage, RefItem

logger = logging.getLogger(__name__)

PAGE_SIZES = (10, 30, 100, 200)


@dataclass(frozen=True)
class PravoTarget:
    """Документный тип портала для сбора: блок + тип (GUID или имя для резолва)."""

    block: str
    type_id: UUID | None = None
    type_name: str | None = None

    def key(self) -> str:
        return f"{self.block}:{self.type_id or self.type_name}"


class PravoApiClient:
    """Клиент официального API publication.pravo.gov.ru (только чтение)."""

    def __init__(self, *, base_url: str | None = None, timeout: float = 60.0) -> None:
        self._base_url = (base_url or settings.pravo_api_base_url).rstrip("/")
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PravoApiClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def document_url(self, eo_number: str) -> str:
        return f"{self._base_url}/document/{eo_number}"

    def pdf_url(self, eo_number: str) -> str:
        return f"{self._base_url}/File/pdf/{eo_number}"

    def get_document_types(self, *, block: str) -> list[RefItem]:
        response = self._client.get("/api/DocumentTypes", params={"block": block})
        response.raise_for_status()
        return [RefItem.model_validate(item) for item in response.json()]

    def get_signatory_authorities(self, *, block: str | None = None) -> list[RefItem]:
        params = {"block": block} if block else None
        response = self._client.get("/api/SignatoryAuthorities", params=params)
        response.raise_for_status()
        return [RefItem.model_validate(item) for item in response.json()]

    def document_type_name(self, type_id: UUID) -> str | None:
        """Имя типа документа по GUID (поиск по одному запросу на каждый блок)."""
        for block in self._known_blocks:
            for item in self.get_document_types(block=block):
                if item.id == type_id:
                    return item.name
        return None

    def signatory_authority_name(self, authority_id: UUID) -> str | None:
        for block in self._known_blocks:
            try:
                for item in self.get_signatory_authorities(block=block):
                    if item.id == authority_id:
                        return item.name
            except Exception:
                continue
        return None

    @property
    def _known_blocks(self) -> list[str]:
        return list(dict.fromkeys([t.block for t in self.collect_targets()]))

    def resolve_fz_type_id(self) -> UUID:
        return self.resolve_target_type_id(self.base_target())

    def resolve_target_type_id(self, target: PravoTarget) -> UUID:
        """GUID типа документа: из target.type_id или по имени типа внутри target.block."""
        if target.type_id is not None:
            return target.type_id
        needle = (target.type_name or "").strip()
        if not needle:
            raise RuntimeError(f"Цель {target.key()} не задаёт ни type_id, ни type_name")
        for item in self.get_document_types(block=target.block):
            if item.name.lower() == needle.lower():
                return item.id
        raise RuntimeError(
            f"Не найден GUID типа «{needle}» в блоке «{target.block}» на /api/DocumentTypes"
        )

    def collect_targets(self) -> list[PravoTarget]:
        """Цели сбора из конфига: наборы блоков/типов, выровненные по порядку."""
        blocks = [b.strip() for b in settings.pravo_collect_blocks.split("|") if b.strip()]
        names = [t.strip() for t in settings.pravo_collect_types.split("|") if t.strip()]
        if len(blocks) != len(names):
            raise RuntimeError(
                "pravo_collect_blocks и pravo_collect_types должны иметь одинаковое число элементов "
                f"(получено {len(blocks)} и {len(names)})"
            )
        targets: list[PravoTarget] = []
        for block, name in zip(blocks, names):
            is_fz = name.lower() == "федеральный закон"
            type_id = UUID(settings.pravo_document_type_fz_id) if is_fz else None
            targets.append(PravoTarget(block=block, type_id=type_id, type_name=None if is_fz else name))
        return targets

    def base_target(self) -> PravoTarget:
        """Базовый (первый) тип набора — эталон каталога/дефолта."""
        return self.collect_targets()[0]

    def list_documents_page(
        self,
        *,
        block: str,
        document_type_id: UUID | None,
        period_type: str | None = "daily",
        target_date: date | None = None,
        publish_date_from: date | None = None,
        publish_date_to: date | None = None,
        page_index: int = 1,
        page_size: int = 200,
    ) -> PravoDocumentsPage:
        if page_size not in PAGE_SIZES:
            raise ValueError(f"PageSize must be one of {PAGE_SIZES}")

        params: dict[str, Any] = {
            "Block": block,
            "PageSize": page_size,
            "Index": page_index,
            "SortedBy": 4,
            "SortDestination": 1,
        }
        if period_type is not None:
            params["PeriodType"] = period_type
        if document_type_id is not None:
            params["DocumentTypeId"] = str(document_type_id)
        if period_type is not None and period_type.lower() == "day" and target_date is not None:
            params["PeriodType"] = "Day"
            params["Date"] = target_date.isoformat()
        if publish_date_from is not None:
            params["PublishDateFrom"] = publish_date_from.isoformat()
        if publish_date_to is not None:
            params["PublishDateTo"] = publish_date_to.isoformat()
        if target_date is not None and publish_date_from is None:
            params["PublishDateFrom"] = target_date.isoformat()
            params["PublishDateTo"] = target_date.isoformat()

        response = self._client.get("/api/Documents", params=params)
        response.raise_for_status()
        return PravoDocumentsPage.model_validate(response.json())

    def iter_documents(
        self,
        target: PravoTarget,
        *,
        period_type: str = "daily",
        target_date: date | None = None,
    ):
        """Итератор документов одного типа с клиентской фильтрацией —
        API не всегда фильтрует тип/дату на сервере."""
        type_id = self.resolve_target_type_id(target)
        effective_period = "Day" if target_date else period_type
        page = 1

        while True:
            result = self.list_documents_page(
                block=target.block,
                document_type_id=type_id,
                period_type=effective_period,
                target_date=target_date,
                page_index=page,
                page_size=200,
            )
            if not result.items:
                break

            for item in result.items:
                if item.document_type_id != type_id:
                    continue
                if target_date is not None:
                    pub_date = parse_api_date(item.publish_date_short)
                    if pub_date != target_date:
                        continue
                yield item

            if target_date is not None:
                page_dates = [
                    d for d in (parse_api_date(i.publish_date_short) for i in result.items) if d
                ]
                if page_dates and max(page_dates) < target_date:
                    break

            if page >= result.pages_total_count:
                break
            page += 1

    def iter_all_documents(
        self,
        target: PravoTarget,
        *,
        publish_date_from: date | None = None,
        publish_date_to: date | None = None,
    ):
        """Полный каталог документов одного типа в блоке — данные с ~2011 года.

        Официальный API не отдаёт ФЗ до ~2011; это граница источника, не баг сборщика.
        """
        type_id = self.resolve_target_type_id(target)
        page = 1

        while True:
            result = self.list_documents_page(
                block=target.block,
                document_type_id=None,
                period_type=None,
                publish_date_from=publish_date_from,
                publish_date_to=publish_date_to,
                page_index=page,
                page_size=200,
            )
            if not result.items:
                break

            for item in result.items:
                if item.document_type_id != type_id:
                    continue
                pub_date = parse_api_date(item.publish_date_short)
                if publish_date_from and pub_date and pub_date < publish_date_from:
                    continue
                if publish_date_to and pub_date and pub_date > publish_date_to:
                    continue
                yield item

            if page >= result.pages_total_count:
                break
            page += 1

    def iter_federal_laws(
        self,
        *,
        period_type: str = "daily",
        target_date: date | None = None,
        fz_type_id: UUID | None = None,
    ):
        """Итератор базового типа набора (ФЗ по умолчанию)."""
        target = self.base_target()
        if fz_type_id is not None:
            target = PravoTarget(block=target.block, type_id=fz_type_id)
        yield from self.iter_documents(
            target,
            period_type=period_type,
            target_date=target_date,
        )

    def iter_all_federal_laws(
        self,
        *,
        fz_type_id: UUID | None = None,
        publish_date_from: date | None = None,
        publish_date_to: date | None = None,
    ):
        """Полный каталог базового типа набора (ФЗ по умолчанию)."""
        target = self.base_target()
        if fz_type_id is not None:
            target = PravoTarget(block=target.block, type_id=fz_type_id)
        yield from self.iter_all_documents(
            target,
            publish_date_from=publish_date_from,
            publish_date_to=publish_date_to,
        )

    def count_catalog_federal_laws(self, *, fz_type_id: UUID | None = None) -> int:
        return sum(1 for _ in self.iter_all_federal_laws(fz_type_id=fz_type_id))

    def get_document(self, eo_number: str) -> dict[str, Any]:
        response = self._client.get("/api/Document", params={"eoNumber": eo_number})
        response.raise_for_status()
        return response.json()

    def download_pdf(self, eo_number: str) -> bytes:
        """Скачивает PDF. Для ~2011–2012 /File/pdf часто отдаёт ZIP с TIFF — конвертируем."""
        response = self._client.get(f"/File/pdf/{eo_number}")
        response.raise_for_status()
        data = response.content
        if data.startswith(b"%PDF"):
            return data
        if data.startswith(b"PK"):
            from explainlaw.extraction.tiff_zip import tiff_zip_to_pdf

            return tiff_zip_to_pdf(data)
        raise ValueError(f"Ответ для {eo_number} не похож на PDF/ZIP (magic={data[:8]!r})")

    def download_raw_file(self, eo_number: str) -> tuple[bytes, str]:
        """Сырой ответ /File/pdf: (bytes, 'pdf'|'tiff_zip')."""
        response = self._client.get(f"/File/pdf/{eo_number}")
        response.raise_for_status()
        data = response.content
        if data.startswith(b"%PDF"):
            return data, "pdf"
        if data.startswith(b"PK"):
            return data, "tiff_zip"
        raise ValueError(f"Ответ для {eo_number} не похож на PDF/ZIP")

    def download_zip(self, eo_number: str) -> bytes:
        response = self._client.get(f"/File/zip/{eo_number}")
        response.raise_for_status()
        data = response.content
        if not data.startswith(b"PK"):
            raise ValueError(f"Ответ для {eo_number} не похож на ZIP")
        return data

    def download_svg(self, eo_number: str) -> bytes:
        response = self._client.get(f"/File/svg/{eo_number}")
        response.raise_for_status()
        data = response.content
        head = data[:200].lstrip().lower()
        if b"<svg" not in head and b"<?xml" not in head:
            raise ValueError(f"Ответ для {eo_number} не похож на SVG")
        return data

    def download_page_snapshot(self, eo_number: str) -> bytes:
        response = self._client.get(f"/document/{eo_number}")
        response.raise_for_status()
        return response.content
