"""Единый интерфейс сборки редакции нормы (раздел 6.3, требование 5).

Остальной код не знает внутренней механики — переход к атомарной модели
= замена реализации здесь, без правок по всему продукту.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from explainlaw.db.models import (
    ApplyKind,
    ApplyStatus,
    Norm,
    NormChangeEvent,
    NormRevisionCache,
)


class NormRevisionAssembler:
    """Сборка редакции нормы N на дату X = baseline + события с effective_date ≤ X."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_revision(self, norm_id: UUID, as_of_date: date) -> str | None:
        cached = self._get_valid_cache(norm_id, as_of_date)
        if cached is not None:
            return cached

        text = self._assemble(norm_id, as_of_date)
        if text is not None:
            self._write_cache(norm_id, as_of_date, text)
        return text

    def _get_valid_cache(self, norm_id: UUID, as_of_date: date) -> str | None:
        stmt = select(NormRevisionCache).where(
            NormRevisionCache.norm_id == norm_id,
            NormRevisionCache.as_of_date == as_of_date,
            NormRevisionCache.invalidated_at.is_(None),
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        return row.assembled_text if row else None

    def _assemble(self, norm_id: UUID, as_of_date: date) -> str | None:
        events = self._session.execute(
            select(NormChangeEvent)
            .where(
                NormChangeEvent.norm_id == norm_id,
                NormChangeEvent.effective_date <= as_of_date,
            )
            .order_by(
                NormChangeEvent.effective_date,
                NormChangeEvent.apply_order,
            )
        ).scalars().all()

        if not events:
            return None

        current_text: str | None = None

        for event in events:
            if event.apply_kind == ApplyKind.address_patch:
                event.apply_status = ApplyStatus.needs_manual
                continue

            if event.apply_kind == ApplyKind.full_redaction:
                if event.text_after is not None:
                    current_text = event.text_after
                    event.apply_status = ApplyStatus.applied
                else:
                    event.apply_status = ApplyStatus.failed
            else:
                event.apply_status = ApplyStatus.needs_manual

        self._session.flush()
        return current_text

    def _write_cache(self, norm_id: UUID, as_of_date: date, text: str) -> None:
        cache = NormRevisionCache(
            norm_id=norm_id,
            as_of_date=as_of_date,
            assembled_text=text,
        )
        self._session.add(cache)

    def invalidate_cache_for_norm(self, norm_id: UUID) -> None:
        """Инвалидация кэша при наступлении новой даты вступления в силу."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        caches = self._session.execute(
            select(NormRevisionCache).where(
                NormRevisionCache.norm_id == norm_id,
                NormRevisionCache.invalidated_at.is_(None),
            )
        ).scalars().all()
        for cache in caches:
            cache.invalidated_at = now

    def get_norm(self, stable_norm_id: str) -> Norm | None:
        return self._session.execute(
            select(Norm).where(Norm.stable_norm_id == stable_norm_id)
        ).scalar_one_or_none()
