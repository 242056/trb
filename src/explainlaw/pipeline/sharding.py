"""Шардирование backlog process/gate между воркерами."""

from __future__ import annotations


def normalize_shard(*, shard_count: int | None, shard_index: int | None) -> tuple[int, int] | None:
    """Вернуть (count, index) или None, если шардирование выключено."""
    if shard_count is None or shard_count <= 1:
        return None
    if shard_index is None:
        raise ValueError("shard_index обязателен при shard_count > 1")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError(f"shard_index={shard_index} вне диапазона 0..{shard_count - 1}")
    return shard_count, shard_index


def apply_id_shard(stmt, column, *, shard_count: int | None, shard_index: int | None):
    """Фильтр document.id % count == index (без пересечений между воркерами)."""
    normalized = normalize_shard(shard_count=shard_count, shard_index=shard_index)
    if normalized is None:
        return stmt
    count, index = normalized
    return stmt.where((column % count) == index)
