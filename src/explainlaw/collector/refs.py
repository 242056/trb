import logging

from sqlalchemy.orm import Session

from explainlaw.config import settings
from explainlaw.db.models import RefDocumentType
from explainlaw.pravo.client import PravoApiClient

logger = logging.getLogger(__name__)


def sync_reference_data(session: Session, pravo: PravoApiClient) -> None:
    """Синхронизация справочников из API (раздел 5.7)."""
    for item in pravo.get_document_types(block=settings.pravo_block_president):
        if session.get(RefDocumentType, item.id) is None:
            session.add(RefDocumentType(id=item.id, name=item.name))

    session.flush()
    logger.info("Справочники синхронизированы")
