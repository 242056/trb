import argparse
import json
import logging
import sys
from datetime import date, timedelta

from sqlalchemy import desc, func, select

from explainlaw.collector.service import DailyCollector
from explainlaw.config import settings
from explainlaw.content.publisher import WeeklyPublisher
from explainlaw.db.models import (
    GateFlag,
    GateStatus,
    MissingActsQueue,
    NpaDelta,
    NpaDocument,
    NpaSector,
    NpaSummary,
    NpaText,
    PipelineJobType,
    PostBank,
    PostStatus,
)
from explainlaw.db.session import SessionLocal
from explainlaw.gates.runner import GateRunner
from explainlaw.messaging.kafka import kafka_producer
from explainlaw.missing_acts.fetcher import MissingActsFetcher
from explainlaw.observability.health import check_health, send_alerts
from explainlaw.observability.recorder import record_run
from explainlaw.pipeline.daily import DailyPipeline
from explainlaw.pipeline.processor import DocumentProcessor
from explainlaw.pravo.client import PravoApiClient
from explainlaw.storage.object_store import get_storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("explainlaw")


def cmd_collect(args: argparse.Namespace) -> int:
    target_date = date.fromisoformat(args.date) if args.date else None
    date_from = date.fromisoformat(args.date_from) if args.date_from else None
    date_to = date.fromisoformat(args.date_to) if args.date_to else None

    if args.days and not (date_from or date_to or target_date or args.all_catalog):
        date_to = date.today()
        date_from = date_to - timedelta(days=args.days - 1)

    storage = get_storage()

    with kafka_producer() as producer, SessionLocal() as session:
        collector = DailyCollector(session, storage, kafka_producer=producer)
        try:
            stats = collector.collect(
                target_date=target_date,
                period_type=args.period,
                date_from=date_from,
                date_to=date_to,
                all_catalog=args.all_catalog,
            )
            record_run(session, job_type=PipelineJobType.collect, metrics=stats.to_dict())
            session.commit()
        finally:
            collector.close()

    print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))

    if stats.errors and stats.new == 0:
        return 1
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    storage = get_storage()
    with kafka_producer() as producer, SessionLocal() as session:
        processor = DocumentProcessor(
            session,
            storage,
            kafka_producer=producer,
            force=args.force,
            amendments_only=args.amendments_only,
            resume=getattr(args, "resume", False),
        )
        stats = processor.process(limit=args.limit)
        record_run(session, job_type=PipelineJobType.process, metrics=stats.to_dict())
        session.commit()

    print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
    return 1 if stats.errors and stats.summarized == 0 else 0


def cmd_gate(args: argparse.Namespace) -> int:
    with kafka_producer() as producer, SessionLocal() as session:
        runner = GateRunner(
            session,
            kafka_producer=producer,
            force=args.force,
            amendments_only=args.amendments_only,
        )
        stats = runner.run(limit=args.limit)
        record_run(session, job_type=PipelineJobType.gate, metrics=stats.to_dict())
        session.commit()

    print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
    return 1 if stats.errors and stats.passed == 0 else 0


def cmd_publish(args: argparse.Namespace) -> int:
    with kafka_producer() as producer, SessionLocal() as session:
        publisher = WeeklyPublisher(session, kafka_producer=producer)
        stats = publisher.run(
            min_items=args.min_items,
            max_items=args.max_items,
            dry_run=args.dry_run,
            mark_published=args.mark_published,
        )
        if not args.dry_run:
            record_run(session, job_type=PipelineJobType.publish, metrics=stats.to_dict())
            session.commit()

    print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_fetch_missing(args: argparse.Namespace) -> int:
    storage = get_storage()
    with kafka_producer(), SessionLocal() as session:
        fetcher = MissingActsFetcher(session, storage)
        try:
            stats = fetcher.fetch(limit=args.limit)
            record_run(session, job_type=PipelineJobType.fetch_missing, metrics=stats.to_dict())
            session.commit()
        finally:
            fetcher.close()

    print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
    return 1 if stats.errors and stats.fetched == 0 else 0


def cmd_rebuild_deltas(args: argparse.Namespace) -> int:
    """Пересобрать дельты для поправок и прогнать гейты (§8.3)."""
    storage = get_storage()
    resume = getattr(args, "resume", False)
    with kafka_producer() as producer, SessionLocal() as session:
        processor = DocumentProcessor(
            session,
            storage,
            kafka_producer=producer,
            force=not resume,
            amendments_only=True,
            rebuild_deltas_only=True,
            resume=resume,
        )
        process_stats = processor.process(limit=args.limit)
        record_run(session, job_type=PipelineJobType.process, metrics=process_stats.to_dict())
        session.commit()

        gate_stats = GateRunner(
            session,
            kafka_producer=producer,
            force=True,
            amendments_only=True,
        ).run(limit=args.limit)
        record_run(session, job_type=PipelineJobType.gate, metrics=gate_stats.to_dict())
        session.commit()

    print(
        json.dumps(
            {"process": process_stats.to_dict(), "gate": gate_stats.to_dict()},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    storage = get_storage()
    target_date = date.fromisoformat(args.date) if args.date else None
    with kafka_producer() as producer, SessionLocal() as session:
        pipeline = DailyPipeline(session, storage, kafka_producer=producer)
        stats = pipeline.run(
            target_date=target_date,
            process_limit=args.process_limit,
            fetch_missing_limit=args.fetch_missing,
            weekly_publish=args.weekly_publish,
            send_alerts=not args.no_alert,
        )

    print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
    return 0 if stats.health.get("healthy", True) else 1


def cmd_health(args: argparse.Namespace) -> int:
    with SessionLocal() as session:
        health = check_health(session)
        if args.alert:
            health["alert_sent"] = send_alerts(health)

    print(json.dumps(health, ensure_ascii=False, indent=2))
    return 0 if health.get("healthy") else 1


def cmd_backfill_pdfs(args: argparse.Namespace) -> int:
    """Догон PDF/TIFF-ZIP для документов без сырья."""
    storage = get_storage()
    with kafka_producer() as producer, SessionLocal() as session:
        collector = DailyCollector(session, storage, kafka_producer=producer)
        try:
            stats = collector.backfill_missing_pdfs(limit=args.limit)
            record_run(session, job_type=PipelineJobType.collect, metrics=stats)
            session.commit()
        finally:
            collector.close()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 1 if stats.get("errors") and stats.get("fetched", 0) == 0 else 0


def cmd_refresh_summaries(args: argparse.Namespace) -> int:
    """Пересобрать сводки для документов с дельтой (Gateway/Qwen)."""
    storage = get_storage()
    with kafka_producer() as producer, SessionLocal() as session:
        processor = DocumentProcessor(
            session,
            storage,
            kafka_producer=producer,
            force=True,
            amendments_only=True,
        )
        # force пересоздаёт summaries; rebuild_deltas_only=False
        stats = processor.process(limit=args.limit)
        record_run(session, job_type=PipelineJobType.process, metrics=stats.to_dict())
        session.commit()
    print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    with SessionLocal() as session:
        rows = session.execute(
            select(NpaDocument, NpaSummary.summary_text)
            .outerjoin(NpaSummary, NpaDocument.id == NpaSummary.document_id)
            .order_by(desc(NpaDocument.publish_date_short), desc(NpaDocument.discovered_at))
            .limit(args.limit)
        ).all()

    if not rows:
        print("Документов в базе нет.")
        return 0

    for doc, summary in rows:
        pub = doc.publish_date_short.isoformat() if doc.publish_date_short else "—"
        num = doc.number or "—"
        name = (doc.name or doc.eo_number)[:60]
        summary_short = (summary[:80] + "…") if summary and len(summary) > 80 else (summary or "—")
        print(f"{pub}  №{num:>6}  {name}")
        print(f"  {summary_short}")
        print(f"  → {doc.source_url}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    with SessionLocal() as session:
        in_db = session.execute(select(func.count()).select_from(NpaDocument)).scalar_one()
        with_text = session.execute(select(func.count()).select_from(NpaText)).scalar_one()
        with_summary = session.execute(select(func.count()).select_from(NpaSummary)).scalar_one()
        with_delta = session.execute(select(func.count()).select_from(NpaDelta)).scalar_one()
        missing_acts = session.execute(select(func.count()).select_from(MissingActsQueue)).scalar_one()
        gate_flags = session.execute(select(func.count()).select_from(GateFlag)).scalar_one()
        post_bank = session.execute(select(func.count()).select_from(PostBank)).scalar_one()
        post_ready = session.execute(
            select(func.count()).select_from(PostBank).where(PostBank.status == PostStatus.ready)
        ).scalar_one()
        post_published = session.execute(
            select(func.count()).select_from(PostBank).where(PostBank.status == PostStatus.published)
        ).scalar_one()
        gate_passed = session.execute(
            select(func.count()).select_from(NpaSummary).where(NpaSummary.gate_status == GateStatus.passed)
        ).scalar_one()
        gate_flagged = session.execute(
            select(func.count()).select_from(NpaSummary).where(NpaSummary.gate_status == GateStatus.flagged)
        ).scalar_one()
        with_sectors = session.execute(select(func.count()).select_from(NpaSector)).scalar_one()
        with_act_group = session.execute(
            select(func.count())
            .select_from(NpaDocument)
            .where(NpaDocument.act_group_id.isnot(None))
        ).scalar_one()

    in_api = settings.pravo_catalog_fz_total
    if args.refresh:
        client = PravoApiClient()
        try:
            in_api = client.count_catalog_federal_laws()
        finally:
            client.close()

    pending_collect = max(0, in_api - in_db)
    pending_process = max(0, in_db - with_text)

    print(json.dumps(
        {
            "catalog_api_total": in_api,
            "catalog_note": "Официальный API publication.pravo.gov.ru, ФЗ с ~2011 года (граница источника)",
            "in_database": in_db,
            "with_text": with_text,
            "with_summary": with_summary,
            "with_delta": with_delta,
            "missing_acts_queue": missing_acts,
            "gate_passed": gate_passed,
            "gate_flagged": gate_flagged,
            "gate_flags_total": gate_flags,
            "with_sectors": with_sectors,
            "with_act_group": with_act_group,
            "post_bank_ready": post_bank,
            "post_bank_status_ready": post_ready,
            "post_bank_status_published": post_published,
            "pending_collect": pending_collect,
            "pending_process": pending_process,
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("explainlaw.api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="explainlaw", description="ExplainLaw — Шаг 1")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="Ежедневный сбор ФЗ с publication.pravo.gov.ru")
    p_collect.add_argument("--date", help="Один день: YYYY-MM-DD")
    p_collect.add_argument("--from", dest="date_from", help="Начало диапазона YYYY-MM-DD")
    p_collect.add_argument("--to", dest="date_to", help="Конец диапазона YYYY-MM-DD")
    p_collect.add_argument(
        "--days",
        type=int,
        help="Собрать за последние N дней (включая сегодня), альтернатива --from/--to",
    )
    p_collect.add_argument(
        "--all",
        dest="all_catalog",
        action="store_true",
        help="Весь каталог ФЗ из API (~7700 с 2011 г.). Дедуп по eoNumber, можно запускать повторно",
    )
    p_collect.add_argument(
        "--period",
        default="daily",
        choices=["daily", "weekly", "monthly"],
        help="PeriodType для API при сборе без --date (по умолчанию daily)",
    )
    p_collect.set_defaults(func=cmd_collect)

    p_list = sub.add_parser("list", help="Список собранных ФЗ")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=cmd_list)

    p_process = sub.add_parser("process", help="Извлечь текст из PDF и сгенерировать сводки")
    p_process.add_argument("--limit", type=int, help="Обработать не более N документов")
    p_process.add_argument("--force", action="store_true", help="Переобработать уже обработанные")
    p_process.add_argument(
        "--amendments-only",
        action="store_true",
        help="Только законы о внесении изменений",
    )
    p_process.add_argument(
        "--resume",
        action="store_true",
        help="Пропускать документы, у которых дельта уже есть",
    )
    p_process.set_defaults(func=cmd_process)

    p_gate = sub.add_parser("gate", help="Гейты качества (дельта + сводка) → post_bank")
    p_gate.add_argument("--limit", type=int, help="Проверить не более N документов")
    p_gate.add_argument("--force", action="store_true", help="Перепроверить уже проверенные")
    p_gate.add_argument(
        "--amendments-only",
        action="store_true",
        help="Только поправки с дельтой",
    )
    p_gate.set_defaults(func=cmd_gate)

    p_publish = sub.add_parser("publish", help="Собрать еженедельный дайджест из post_bank (§7.2)")
    p_publish.add_argument("--min-items", type=int, help="Минимум карточек для полного дайджеста")
    p_publish.add_argument("--max-items", type=int, help="Максимум карточек в дайджесте")
    p_publish.add_argument("--dry-run", action="store_true", help="Только показать отбор, без записи")
    p_publish.add_argument(
        "--mark-published",
        action="store_true",
        help="Пометить один готовый пост как опубликованный",
    )
    p_publish.set_defaults(func=cmd_publish)

    p_fetch = sub.add_parser(
        "fetch-missing",
        help="Загрузить акты из missing_acts_queue через API",
    )
    p_fetch.add_argument("--limit", type=int, default=5, help="Сколько записей очереди обработать")
    p_fetch.set_defaults(func=cmd_fetch_missing)

    p_rebuild = sub.add_parser(
        "rebuild-deltas",
        help="Пересобрать дельты поправок и прогнать гейты (§8.3)",
    )
    p_rebuild.add_argument("--limit", type=int, help="Обработать не более N поправок")
    p_rebuild.add_argument(
        "--resume",
        action="store_true",
        help="Только поправки без дельты (безопасный догон)",
    )
    p_rebuild.set_defaults(func=cmd_rebuild_deltas)

    p_backfill_pdf = sub.add_parser(
        "backfill-pdfs",
        help="Догон PDF/TIFF-ZIP для документов без сырья (§4.1)",
    )
    p_backfill_pdf.add_argument("--limit", type=int, help="Не более N документов")
    p_backfill_pdf.set_defaults(func=cmd_backfill_pdfs)

    p_refresh = sub.add_parser(
        "refresh-summaries",
        help="Пересобрать ИИ-сводки для поправок (Gateway/Qwen)",
    )
    p_refresh.add_argument("--limit", type=int, help="Не более N документов")
    p_refresh.set_defaults(func=cmd_refresh_summaries)

    p_daily = sub.add_parser("daily", help="Ежедневный конвейер: collect → process → gate → fetch-missing")
    p_daily.add_argument("--date", help="День сбора YYYY-MM-DD (по умолчанию сегодня)")
    p_daily.add_argument("--process-limit", type=int, help="Лимит документов на обработку/гейты")
    p_daily.add_argument("--fetch-missing", type=int, default=3, help="Сколько актов из очереди подтянуть")
    p_daily.add_argument(
        "--weekly-publish",
        action="store_true",
        help="Также собрать еженедельный дайджест (для cron по понедельникам)",
    )
    p_daily.add_argument("--no-alert", action="store_true", help="Не отправлять webhook-алерт")
    p_daily.set_defaults(func=cmd_daily)

    p_health = sub.add_parser("health", help="Проверка здоровья конвейера и алерты (§11)")
    p_health.add_argument("--alert", action="store_true", help="Отправить webhook при проблемах")
    p_health.set_defaults(func=cmd_health)

    p_status = sub.add_parser("status", help="Сколько ФЗ в API, в БД, ожидают обработки")
    p_status.add_argument("--refresh", action="store_true", help="Пересчитать каталог через API (~10 с)")
    p_status.set_defaults(func=cmd_status)

    p_serve = sub.add_parser("serve", help="Запустить веб-интерфейс")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=7000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
