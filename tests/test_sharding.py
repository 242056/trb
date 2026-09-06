from explainlaw.db.models import NpaDocument
from explainlaw.pipeline.sharding import apply_id_shard, normalize_shard


def test_normalize_shard_disabled():
    assert normalize_shard(shard_count=None, shard_index=None) is None
    assert normalize_shard(shard_count=1, shard_index=0) is None


def test_normalize_shard_enabled():
    assert normalize_shard(shard_count=2, shard_index=1) == (2, 1)


def test_normalize_shard_rejects_bad_index():
    try:
        normalize_shard(shard_count=2, shard_index=2)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_apply_id_shard_adds_modulo_filter():
    from sqlalchemy import select

    stmt = select(NpaDocument)
    sharded = apply_id_shard(stmt, NpaDocument.id, shard_count=2, shard_index=0)
    compiled = str(sharded.compile(compile_kwargs={"literal_binds": True}))
    assert "%" in compiled or "mod" in compiled.lower()
    assert "0" in compiled
