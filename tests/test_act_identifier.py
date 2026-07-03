from explainlaw.extraction.act_identifier import identifier_key, parse_federal_law_references
from explainlaw.extraction.relations import extract_relations

SAMPLE = """
Статья 1
Внести в статью 48 Федерального закона от 21 июля 1997 года №114-ФЗ
«О службе в таможенных органах Российской Федерации» следующие изменения:
изложить статью 48 в следующей редакции:
«Статья 48. Новый текст статьи».

Статья 2
В части двенадцатой статьи 26 Федерального закона «О банках и банковской деятельности»
(в редакции Федерального закона от 3 февраля 1996 года №17-ФЗ) слова "кредитная организация"
заменить словами "банк".
"""


def test_parse_federal_law_with_date_and_number():
    refs = parse_federal_law_references(SAMPLE)
    assert any(r.get("number") == "114-ФЗ" and r.get("date") == "1997-07-21" for r in refs)


def test_parse_federal_law_title_first_with_edition():
    refs = parse_federal_law_references(SAMPLE)
    bank = next(r for r in refs if "банках" in r.get("name", "").lower())
    assert bank.get("number") == "17-ФЗ"
    assert bank.get("date") == "1996-02-03"


def test_extract_relations_per_article():
    rels = extract_relations("О внесении изменений...", SAMPLE)
    assert len(rels) >= 2
    assert any(r.target_act_identifier.get("number") == "114-ФЗ" for r in rels)


def test_identifier_key_stable():
    a = {"type": "federal_law", "number": "114-ФЗ", "date": "1997-07-21", "name": "О службе"}
    b = dict(a)
    assert identifier_key(a) == identifier_key(b)
