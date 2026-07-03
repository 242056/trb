"""Kafka-топики конвейера обработки (раздел 7–8)."""

TOPIC_DOCUMENT_DISCOVERED = "npa.document.discovered"
TOPIC_RAW_STORED = "npa.raw.stored"
TOPIC_TEXT_EXTRACTED = "npa.text.extracted"
TOPIC_DELTA_COMPUTED = "npa.delta.computed"
TOPIC_SUMMARY_GENERATED = "npa.summary.generated"
TOPIC_GATE_RESULT = "npa.gate.result"
TOPIC_POST_READY = "npa.post.ready"

ALL_TOPICS = [
    TOPIC_DOCUMENT_DISCOVERED,
    TOPIC_RAW_STORED,
    TOPIC_TEXT_EXTRACTED,
    TOPIC_DELTA_COMPUTED,
    TOPIC_SUMMARY_GENERATED,
    TOPIC_GATE_RESULT,
    TOPIC_POST_READY,
]
