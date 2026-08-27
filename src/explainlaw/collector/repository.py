from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from explainlaw.db.models import NpaDocument, NpaRaw, RawFileType, RefDocumentType, RefSignatoryAuthority
from explainlaw.pravo.models import PravoDocumentItem
from explainlaw.storage.object_store import ObjectStorage


def parse_api_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_api_date(value: datetime | str | None) -> date | None:
    dt = parse_api_datetime(value)
    return dt.date() if dt else None


class DocumentRepository:
    def __init__(self, session: Session, storage: ObjectStorage) -> None:
        self._session = session
        self._storage = storage

    def exists(self, eo_number: str) -> bool:
        return (
            self._session.execute(
                select(NpaDocument.id).where(NpaDocument.eo_number == eo_number)
            ).scalar_one_or_none()
            is not None
        )

    def upsert_refs(self, item: PravoDocumentItem, pravo=None) -> None:
        """Дозаполняет справочники типа/подписанта, если их ещё нет в БД.

        В обычном цикле сбора справочники уже синхронизированы (collector/refs.py),
        поэтому здесь достаточно lookup по GUID. Для прямого ingest_one без синка
        подтягиваем имя из API по факту.
        """
        if item.document_type_id and self._session.get(RefDocumentType, item.document_type_id) is None:
            name = "Неизвестный тип"
            if pravo is not None:
                name = pravo.document_type_name(item.document_type_id) or name
            self._session.add(RefDocumentType(id=item.document_type_id, name=name))
        if item.signatory_authority_id and self._session.get(RefSignatoryAuthority, item.signatory_authority_id) is None:
            name = "Неизвестный орган"
            if pravo is not None:
                name = pravo.signatory_authority_name(item.signatory_authority_id) or name
            self._session.add(RefSignatoryAuthority(id=item.signatory_authority_id, name=name))
        self._session.flush()

    def create_document(
        self,
        item: PravoDocumentItem,
        *,
        source_url: str,
        raw_api: dict,
        pravo=None,
    ) -> NpaDocument:
        self.upsert_refs(item, pravo=pravo)
        doc = NpaDocument(
            eo_number=item.eo_number,
            number=item.number,
            document_date=parse_api_date(item.document_date),
            name=item.name,
            complex_name=item.complex_name,
            publish_date_short=parse_api_date(item.publish_date_short),
            view_date=parse_api_datetime(item.view_date),
            document_type_id=item.document_type_id,
            signatory_authority_id=item.signatory_authority_id,
            pages_count=item.pages_count,
            pdf_file_length=item.pdf_file_length,
            has_svg=item.has_svg,
            zip_file_length=item.zip_file_length,
            source_url=source_url,
            discovered_at=datetime.now(timezone.utc),
            api_metadata=raw_api,
        )
        self._session.add(doc)
        self._session.flush()
        return doc

    def add_raw_file(
        self,
        document: NpaDocument,
        *,
        raw_type: RawFileType,
        data: bytes,
        bucket: str,
        object_name: str,
        content_type: str,
    ) -> NpaRaw:
        storage_path, checksum, file_size = self._storage.put_raw(
            bucket=bucket,
            object_name=object_name,
            data=data,
            content_type=content_type,
        )
        raw = NpaRaw(
            document_id=document.id,
            raw_type=raw_type,
            storage_path=storage_path,
            checksum_sha256=checksum,
            file_size=file_size,
        )
        self._session.add(raw)
        return raw
