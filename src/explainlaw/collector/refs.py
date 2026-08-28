import logging

from sqlalchemy.orm import Session

from explainlaw.db.models import RefDocumentType, RefSignatoryAuthority
from explainlaw.pravo.client import PravoApiClient

logger = logging.getLogger(__name__)


def _target_blocks(client: PravoApiClient) -> list[str]:
    return list(dict.fromkeys(t.block for t in client.collect_targets()))


def sync_reference_data(session: Session, pravo: PravoApiClient) -> None:
    """Синхронизация справочников типов документов и подписантов по всем блокам сбора.

    Вызывается в начале каждого сбора (collect / fetch-missing). После неё
    `upsert_refs` в repository.py делает только lookup по GUID, без обращений к API.
    """
    for block in _target_blocks(pravo):
        for item in pravo.get_document_types(block=block):
            if session.get(RefDocumentType, item.id) is None:
                session.add(RefDocumentType(id=item.id, name=item.name))
    sync_signatory_authorities(session, pravo)

    session.flush()
    logger.info("Справочники синхронизированы (блоки: %s)", ", ".join(_target_blocks(pravo)))


def sync_signatory_authorities(session: Session, pravo: PravoApiClient) -> None:
    """Синхронизация органов, подписывающих документы, по блокам сбора (5.7)."""
    for block in _target_blocks(pravo):
        try:
            authorities = pravo.get_signatory_authorities(block=block)
        except Exception:
            logger.warning("Не удалось получить подписантов блока %s", block, exc_info=True)
            continue
        for item in authorities:
            if session.get(RefSignatoryAuthority, item.id) is None:
                session.add(
                    RefSignatoryAuthority(id=item.id, name=item.name, category_id=item.category_id)
                )
    session.flush()
