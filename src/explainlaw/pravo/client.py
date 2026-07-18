import logging
from datetime import date
from typing import Any
from uuid import UUID

import httpx

from explainlaw.collector.repository import parse_api_date
from explainlaw.config import settings
from explainlaw.pravo.models import PravoDocumentItem, PravoDocumentsPage, RefItem

logger = logging.getLogger(__name__)

PAGE_SIZES = (10, 30, 100, 200)


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

    def resolve_fz_type_id(self) -> UUID:
        if settings.pravo_document_type_fz_id:
            return UUID(settings.pravo_document_type_fz_id)
        for item in self.get_document_types(block=settings.pravo_block_president):
            if item.name == "Федеральный закон":
                return item.id
        raise RuntimeError("Не найден GUID вида «Федеральный закон» в /api/DocumentTypes")

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

    def iter_federal_laws(
        self,
        *,
        period_type: str = "daily",
        target_date: date | None = None,
        fz_type_id: UUID | None = None,
    ):
        """Итератор ФЗ с клиентской фильтрацией — API не всегда фильтрует тип/дату на сервере."""
        fz_id = fz_type_id or self.resolve_fz_type_id()
        effective_period = "Day" if target_date else period_type
        page = 1

        while True:
            result = self.list_documents_page(
                block=settings.pravo_block_president,
                document_type_id=fz_id,
                period_type=effective_period,
                target_date=target_date,
                page_index=page,
                page_size=200,
            )
            if not result.items:
                break

            for item in result.items:
                if item.document_type_id != fz_id:
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

    def iter_all_federal_laws(
        self,
        *,
        fz_type_id: UUID | None = None,
        publish_date_from: date | None = None,
        publish_date_to: date | None = None,
    ):
        """Полный каталог ФЗ блока president — ~95 страниц API, данные с 2011 года.

        Официальный API не отдаёт ФЗ до ~2011; это граница источника, не баг сборщика.
        """
        fz_id = fz_type_id or self.resolve_fz_type_id()
        page = 1

        while True:
            result = self.list_documents_page(
                block=settings.pravo_block_president,
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
                if item.document_type_id != fz_id:
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
