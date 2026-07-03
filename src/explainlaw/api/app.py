from datetime import date, datetime

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select

from explainlaw.config import settings
from explainlaw.db.models import GateStatus, NpaDelta, NpaDocument, NpaSummary, PostBank
from explainlaw.db.session import SessionLocal
from explainlaw.observability.health import check_health

app = FastAPI(title="ExplainLaw", version="0.1.0", description="Мониторинг федеральных законов")


class DocumentListItem(BaseModel):
    eo_number: str
    number: str | None
    name: str | None
    publish_date: date | None
    document_date: date | None
    source_url: str
    pages_count: int | None
    summary: str | None
    gate_status: str | None
    delta_completeness: str | None
    delta_preview: str | None


class DocumentListResponse(BaseModel):
    total: int
    items: list[DocumentListItem]


class PostListItem(BaseModel):
    id: int
    title: str
    post_type: str
    status: str
    published_at: datetime | None
    preview: str


class PostListResponse(BaseModel):
    total: int
    items: list[PostListItem]


def _load_documents(limit: int, offset: int) -> tuple[int, list[tuple[NpaDocument, str | None, str | None, NpaDelta | None]]]:
    with SessionLocal() as session:
        total = session.execute(select(func.count()).select_from(NpaDocument)).scalar_one()
        rows = session.execute(
            select(NpaDocument, NpaSummary.summary_text, NpaSummary.gate_status, NpaDelta)
            .outerjoin(NpaSummary, NpaDocument.id == NpaSummary.document_id)
            .outerjoin(NpaDelta, NpaDocument.id == NpaDelta.document_id)
            .order_by(desc(NpaDocument.publish_date_short), desc(NpaDocument.discovered_at))
            .limit(limit)
            .offset(offset)
        ).all()
        return total, list(rows)


def _delta_preview(delta: NpaDelta | None) -> str | None:
    if not delta:
        return None
    changes = delta.delta_data.get("changes") or []
    if not changes:
        return None
    first = changes[0]
    target = first.get("target_act", {}).get("name") or first.get("target_act", {}).get("number")
    article = (first.get("unit_address") or {}).get("статья")
    after = first.get("text_after") or ""
    snippet = (after[:120] + "…") if len(after) > 120 else after
    prefix = f"Изменяет: {target}"
    if article:
        prefix += f", ст. {article}"
    return f"{prefix}. {snippet}".strip()


@app.get("/health")
def health() -> dict:
    with SessionLocal() as session:
        result = check_health(session)
    return {"status": "ok" if result.get("healthy") else "degraded", **result}


@app.get("/api/documents", response_model=DocumentListResponse)
def list_documents(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DocumentListResponse:
    total, rows = _load_documents(limit, offset)
    items = [
        DocumentListItem(
            eo_number=doc.eo_number,
            number=doc.number,
            name=doc.name,
            publish_date=doc.publish_date_short,
            document_date=doc.document_date,
            source_url=doc.source_url,
            pages_count=doc.pages_count,
            summary=summary,
            gate_status=gate_status.value if gate_status else None,
            delta_completeness=delta.completeness_status.value if delta else None,
            delta_preview=_delta_preview(delta),
        )
        for doc, summary, gate_status, delta in rows
    ]
    return DocumentListResponse(total=total, items=items)


def _load_posts(limit: int) -> tuple[int, list[PostBank]]:
    with SessionLocal() as session:
        total = session.execute(select(func.count()).select_from(PostBank)).scalar_one()
        rows = session.execute(
            select(PostBank)
            .order_by(desc(PostBank.created_at))
            .limit(limit)
        ).scalars().all()
        return total, list(rows)


@app.get("/api/posts", response_model=PostListResponse)
def list_posts(limit: int = Query(default=20, ge=1, le=100)) -> PostListResponse:
    total, rows = _load_posts(limit)
    items = [
        PostListItem(
            id=post.id,
            title=post.title,
            post_type=post.post_type.value,
            status=post.status.value,
            published_at=post.published_at,
            preview=(post.content[:200] + "…") if len(post.content) > 200 else post.content,
        )
        for post in rows
    ]
    return PostListResponse(total=total, items=items)


@app.get("/posts", response_class=HTMLResponse)
def posts_page(limit: int = Query(default=20, ge=1, le=100)) -> str:
    total, rows = _load_posts(limit)
    cards = []
    for post in rows:
        status = post.status.value
        pub = post.published_at.date().isoformat() if post.published_at else "—"
        cards.append(
            f'<article class="card">'
            f'<div class="meta"><span class="type">{post.post_type.value}</span> · '
            f'<span class="status {status}">{status}</span> · <span>{pub}</span></div>'
            f'<h2>{_escape_html(post.title)}</h2>'
            f'<pre class="content">{_escape_html(post.content)}</pre>'
            f"</article>"
        )
    body = "\n".join(cards) if cards else (
        '<p class="empty">Пока нет готовых постов. Запустите: '
        '<code>explainlaw publish</code></p>'
    )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ExplainLaw — Посты</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }}
    .nav {{ margin-bottom: 1rem; font-size: 0.9rem; }}
    .card {{ border-bottom: 1px solid #e5e5e5; padding: 1.25rem 0; }}
    .meta {{ font-size: 0.85rem; color: #888; }}
    .status.ready {{ color: #065f46; }}
    .status.published {{ color: #1a56db; }}
    pre.content {{ white-space: pre-wrap; font-family: inherit; font-size: 0.92rem; color: #333; }}
    a {{ color: #1a56db; text-decoration: none; }}
  </style>
</head>
<body>
  <p class="nav"><a href="/">← Законы</a></p>
  <h1>Банк постов</h1>
  <p class="lead">Всего: {total}</p>
  {body}
</body>
</html>"""


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@app.get("/", response_class=HTMLResponse)
def index(limit: int = Query(default=50, ge=1, le=200)) -> str:
    total, rows = _load_documents(limit, 0)
    cards = []
    for doc, summary, gate_status, delta in rows:
        title = _escape_html(doc.name or doc.eo_number)
        pub = doc.publish_date_short.isoformat() if doc.publish_date_short else "—"
        num = doc.number or "—"
        gate_label = gate_status.value if gate_status else "pending"
        summary_html = (
            f'<p class="summary">{_escape_html(summary)}</p>'
            if summary
            else '<p class="summary pending">Сводка готовится…</p>'
        )
        delta_html = ""
        preview = _delta_preview(delta)
        if preview:
            badge = delta.completeness_status.value if delta else "partial"
            delta_html = (
                f'<p class="delta"><span class="badge {badge}">{badge}</span> '
                f'{_escape_html(preview)}</p>'
            )
        cards.append(
            f'<article class="card">'
            f'<div class="meta"><span>{pub}</span> · <span>№ {num}</span> · '
            f'<span class="gate {gate_label}">{gate_label}</span></div>'
            f'<h2><a href="{doc.source_url}" target="_blank" rel="noopener">{title}</a></h2>'
            f"{summary_html}"
            f"{delta_html}"
            f"</article>"
        )

    body = "\n".join(cards) if cards else (
        '<p class="empty">Пока нет документов. Запустите: <code>explainlaw collect</code></p>'
    )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ExplainLaw — Федеральные законы</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; line-height: 1.5; }}
    h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
    p.lead {{ color: #666; margin-top: 0; }}
    .card {{ border-bottom: 1px solid #e5e5e5; padding: 1.25rem 0; }}
    .card h2 {{ font-size: 1.05rem; margin: 0.4rem 0; font-weight: 600; }}
    .meta {{ font-size: 0.85rem; color: #888; }}
    .summary {{ color: #333; margin: 0.5rem 0 0; font-size: 0.95rem; }}
    .summary.pending {{ color: #999; font-style: italic; }}
    .delta {{ color: #444; margin: 0.35rem 0 0; font-size: 0.9rem; }}
    .badge {{ font-size: 0.7rem; text-transform: uppercase; padding: 0.1rem 0.35rem; border-radius: 4px; margin-right: 0.35rem; }}
    .badge.full {{ background: #d1fae5; color: #065f46; }}
    .badge.partial {{ background: #fef3c7; color: #92400e; }}
    .gate {{ font-size: 0.75rem; text-transform: uppercase; }}
    .gate.passed {{ color: #065f46; }}
    .gate.flagged {{ color: #b45309; }}
    .gate.pending {{ color: #6b7280; }}
    a {{ color: #1a56db; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .empty {{ color: #666; }}
    code {{ background: #f4f4f5; padding: 0.1rem 0.35rem; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Федеральные законы</h1>
  <p class="lead">Источник: <a href="{settings.pravo_api_base_url}">publication.pravo.gov.ru</a> · В базе: {total} · <a href="/posts">Посты</a></p>
  {body}
</body>
</html>"""
