import re
from dataclasses import dataclass

from explainlaw.db.models import RelationType
from explainlaw.extraction.act_identifier import parse_federal_law_references
from explainlaw.extraction.article_blocks import split_article_blocks


@dataclass
class RelationMatch:
    target_act_identifier: dict
    target_name_text: str
    relation_type: RelationType
    source_article: str | None = None


_AMENDS_HINT_RE = re.compile(
    r"внести|изложить|дополнить|исключить|заменить",
    re.IGNORECASE,
)


def _primary_target_from_block(article_num: str, block: str) -> RelationMatch | None:
    refs = parse_federal_law_references(block)
    if not refs:
        return None

    # Первая ссылка на ФЗ в статье-поправке — обычно изменяемый акт
    target = refs[0]
    relation_type = RelationType.amends if _AMENDS_HINT_RE.search(block) else RelationType.references
    return RelationMatch(
        target_act_identifier=target,
        target_name_text=target.get("name", ""),
        relation_type=relation_type,
        source_article=article_num,
    )


def extract_relations(name: str | None, full_text: str) -> list[RelationMatch]:
    """Извлекает связи из полного текста поправки (по статьям)."""
    results: list[RelationMatch] = []
    seen: set[str] = set()

    for article_num, block in split_article_blocks(full_text):
        match = _primary_target_from_block(article_num, block)
        if match is None:
            continue
        key = f"{article_num}:{match.target_act_identifier.get('number')}:{match.target_act_identifier.get('date')}:{match.target_name_text}"
        if key in seen:
            continue
        seen.add(key)
        results.append(match)

    if results:
        return results

    # Фоллбэк: заголовок документа (одиночные поправки)
    header = name or ""
    refs = parse_federal_law_references(f"{header}\n{full_text[:3000]}")
    for target in refs:
        key = f"{target.get('number')}:{target.get('date')}:{target.get('name')}"
        if key in seen:
            continue
        seen.add(key)
        results.append(
            RelationMatch(
                target_act_identifier=target,
                target_name_text=target.get("name", ""),
                relation_type=RelationType.amends,
            )
        )

    return results
