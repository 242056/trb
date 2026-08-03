"""Оркестратор публикационного конвейера — итерация 4 (§7.1–7.2)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from explainlaw.config import settings
from explainlaw.content.digest import build_enactment_week_post, create_digest_post
from explainlaw.content.selector import select_cards_for_digest
from explainlaw.db.models import PostBank, PostStatus, PostType
from explainlaw.pipeline.topics import TOPIC_POST_READY

logger = logging.getLogger(__name__)


@dataclass
class PublishStats:
    cards_available: int = 0
    cards_selected: int = 0
    digest_created: bool = False
    digest_post_id: int | None = None
    digest_type: str | None = None
    fallback_created: bool = False
    fallback_post_id: int | None = None
    reserve_ready_count: int = 0
    published_count: int = 0
    export_path: str | None = None
    telegram_sent: bool = False
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {
            "cards_available": self.cards_available,
            "cards_selected": self.cards_selected,
            "digest_created": self.digest_created,
            "digest_post_id": self.digest_post_id,
            "digest_type": self.digest_type,
            "fallback_created": self.fallback_created,
            "fallback_post_id": self.fallback_post_id,
            "reserve_ready_count": self.reserve_ready_count,
            "published_count": self.published_count,
            "export_path": self.export_path,
            "telegram_sent": self.telegram_sent,
            "dry_run": self.dry_run,
        }


class WeeklyPublisher:
    def __init__(self, session: Session, *, kafka_producer=None) -> None:
        self._session = session
        self._kafka = kafka_producer

    def run(
        self,
        *,
        min_items: int | None = None,
        max_items: int | None = None,
        dry_run: bool = False,
        mark_published: bool = False,
        today: date | None = None,
    ) -> PublishStats:
        stats = PublishStats(dry_run=dry_run)
        today = today or date.today()
        min_items = min_items or settings.digest_min_items
        max_items = max_items or settings.digest_max_items

        candidates = select_cards_for_digest(self._session, max_items=max_items * 2, today=today)
        stats.cards_available = len(candidates)
        selected = candidates[:max_items]
        stats.cards_selected = len(selected)

        if dry_run:
            stats.reserve_ready_count = self._count_ready_posts()
            return stats

        # Уже собранный сегодня ready-дайджест не дублируем (повтор weekly / ручной retry).
        post = self._ready_digest_today(today)
        reused = post is not None
        if post is None:
            if len(selected) >= min_items:
                post = create_digest_post(
                    self._session, selected, today=today, post_type=PostType.digest
                )
                stats.digest_type = PostType.digest.value
            elif selected:
                post = create_digest_post(
                    self._session, selected, today=today, post_type=PostType.mini_digest
                )
                stats.digest_type = PostType.mini_digest.value
            else:
                post = build_enactment_week_post(self._session, today=today)
                if post:
                    stats.fallback_created = True
                    stats.fallback_post_id = post.id
                    stats.digest_type = PostType.enactment_week.value
                    self._publish_kafka(post.id, post.post_type.value)

        if post and not stats.fallback_created:
            stats.digest_created = not reused
            stats.digest_post_id = post.id
            stats.digest_type = stats.digest_type or post.post_type.value
            if not reused:
                self._publish_kafka(post.id, post.post_type.value)

        stats.reserve_ready_count = self._count_ready_posts()
        if stats.reserve_ready_count < settings.post_reserve_count:
            fallback = build_enactment_week_post(self._session, today=today)
            if fallback:
                stats.fallback_created = True
                stats.fallback_post_id = fallback.id
                self._publish_kafka(fallback.id, fallback.post_type.value)
                stats.reserve_ready_count = self._count_ready_posts()

        if mark_published:
            # Публикуем именно созданный дайджест/fallback, а не самый старый ready.
            target = post
            if target is None:
                target = self._oldest_ready_post()
            if target is not None:
                self._mark_post_published(target)
                stats.published_count = 1
                if stats.digest_post_id is None:
                    stats.digest_post_id = target.id
                if stats.digest_type is None:
                    stats.digest_type = target.post_type.value
                stats.export_path = self._export_post(target)
                stats.telegram_sent = self._send_post_to_telegram(target)

        self._session.commit()
        return stats

    def _count_ready_posts(self) -> int:
        return self._session.execute(
            select(func.count())
            .select_from(PostBank)
            .where(PostBank.status == PostStatus.ready)
        ).scalar_one()

    def _ready_digest_today(self, today: date) -> PostBank | None:
        day_start = datetime(
            today.year, today.month, today.day, tzinfo=ZoneInfo("Europe/Moscow")
        )
        return self._session.execute(
            select(PostBank)
            .where(
                PostBank.status == PostStatus.ready,
                PostBank.post_type.in_([PostType.digest, PostType.mini_digest]),
                PostBank.created_at >= day_start,
            )
            .order_by(PostBank.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _oldest_ready_post(self) -> PostBank | None:
        return self._session.execute(
            select(PostBank)
            .where(PostBank.status == PostStatus.ready)
            .order_by(PostBank.created_at.asc())
            .limit(1)
        ).scalar_one_or_none()

    def _mark_post_published(self, post: PostBank) -> None:
        post.status = PostStatus.published
        post.published_at = datetime.now(timezone.utc)
        self._session.flush()

    def _export_post(self, post: PostBank) -> str | None:
        """Экспорт одного поста в PUBLISH_EXPORT_DIR."""
        out_dir = Path(settings.publish_export_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = (post.published_at or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"post_{post.id}_{stamp}.md"
        body = f"# {post.title}\n\n{post.content}\n"
        path.write_text(body, encoding="utf-8")
        meta = {
            "post_id": post.id,
            "post_type": post.post_type.value,
            "title": post.title,
            "published_at": post.published_at.isoformat() if post.published_at else None,
        }
        path.with_suffix(".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Экспорт публикации: %s", path)
        return str(path)

    def _send_post_to_telegram(self, post: PostBank) -> bool:
        if not settings.telegram_publish:
            return False
        from explainlaw.messaging.telegram import format_post_for_telegram, send_telegram_text

        text = format_post_for_telegram(title=post.title, content=post.content)
        if send_telegram_text(text):
            logger.info("Дайджест отправлен в Telegram (post_id=%s)", post.id)
            return True
        logger.warning("Не удалось отправить post_id=%s в Telegram", post.id)
        return False

    def _publish_kafka(self, post_id: int, post_type: str) -> None:
        if self._kafka is None:
            return
        payload = {"post_id": post_id, "post_type": post_type}
        self._kafka.produce(TOPIC_POST_READY, json.dumps(payload).encode())
        self._kafka.poll(0)
