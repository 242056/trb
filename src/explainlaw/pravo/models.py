from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PravoDocumentItem(BaseModel):
    eo_number: str = Field(alias="eoNumber")
    number: str | None = None
    document_date: datetime | None = Field(default=None, alias="documentDate")
    name: str | None = None
    complex_name: str | None = Field(default=None, alias="complexName")
    publish_date_short: datetime | None = Field(default=None, alias="publishDateShort")
    view_date: str | None = Field(default=None, alias="viewDate")
    document_type_id: UUID | None = Field(default=None, alias="documentTypeId")
    signatory_authority_id: UUID | None = Field(default=None, alias="signatoryAuthorityId")
    pages_count: int | None = Field(default=None, alias="pagesCount")
    pdf_file_length: int | None = Field(default=None, alias="pdfFileLength")
    has_svg: bool | None = Field(default=None, alias="hasSvg")
    zip_file_length: int | None = Field(default=None, alias="zipFileLength")
    id: UUID | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    def raw_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class PravoDocumentsPage(BaseModel):
    items: list[PravoDocumentItem] = Field(default_factory=list)
    items_total_count: int = Field(default=0, alias="itemsTotalCount")
    items_per_page: int = Field(default=0, alias="itemsPerPage")
    current_page: int = Field(default=1, alias="currentPage")
    pages_total_count: int = Field(default=0, alias="pagesTotalCount")

    model_config = {"populate_by_name": True}


class RefItem(BaseModel):
    id: UUID
    name: str
    weight: int | None = None
    category_id: UUID | None = Field(default=None, alias="categoryId")

    model_config = {"populate_by_name": True, "extra": "allow"}


class CollectParams(BaseModel):
    target_date: date | None = None
    period_type: str = "daily"
