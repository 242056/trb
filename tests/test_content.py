from datetime import date

from explainlaw.content.scoring import score_card
from explainlaw.db.models import DeltaCompleteness, NpaDelta, NpaDocument, PostBank, PostStatus, PostType


def test_score_card_prefers_full_delta():
    doc = NpaDocument(
        id=1,
        eo_number="x",
        number="1-ФЗ",
        publish_date_short=date.today(),
        source_url="http://x",
        api_metadata={},
    )
    delta = NpaDelta(
        document_id=1,
        completeness_status=DeltaCompleteness.full,
        delta_data={"changes": [{}, {}], "change_count": 2},
    )
    card = PostBank(
        title="t",
        content="x" * 100,
        post_type=PostType.single,
        status=PostStatus.ready,
    )
    full_score = score_card(doc=doc, delta=delta, card=card)
    partial = NpaDelta(
        document_id=1,
        completeness_status=DeltaCompleteness.partial,
        delta_data={"changes": [{}], "change_count": 1},
    )
    partial_score = score_card(doc=doc, delta=partial, card=card)
    assert full_score > partial_score
