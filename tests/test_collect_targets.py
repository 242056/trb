"""Цели сбора: несколько блоков/типов и разрез статистики по типам."""

from uuid import UUID

import pytest

from explainlaw.collector.service import CollectStats, DailyCollector
from explainlaw.config import settings
from explainlaw.pravo.client import PravoApiClient, PravoTarget


def test_collect_targets_default_config_has_three_types():
    client = PravoApiClient()
    targets = client.collect_targets()
    assert len(targets) == 3
    # ФЗ — базовый тип: GUID приходит из конфига
    assert targets[0].block == "president"
    assert targets[0].type_id == UUID(settings.pravo_document_type_fz_id)
    # Указ — резолвится по имени внутри блока president
    assert targets[1] == PravoTarget(block="president", type_name="Указ")
    # Постановление — блок government
    assert targets[2] == PravoTarget(block="government", type_name="Постановление")


def test_collect_targets_base_target_is_fz():
    client = PravoApiClient()
    assert client.base_target().type_id == UUID(settings.pravo_document_type_fz_id)


def test_collect_targets_mismatched_lengths_raises(monkeypatch):
    monkeypatch.setattr(settings, "pravo_collect_blocks", "president")
    monkeypatch.setattr(settings, "pravo_collect_types", "Фз|Указ")
    client = PravoApiClient()
    with pytest.raises(RuntimeError):
        client.collect_targets()


def test_collect_stats_by_type_accumulates_per_target():
    stats = CollectStats()
    DailyCollector._bump_type(stats, "government:Постановление", "new", 1)
    DailyCollector._bump_type(stats, "government:Постановление", "new", 2)
    DailyCollector._bump_type(stats, "president:Указ", "skipped", 1)
    assert stats.by_type == {
        "government:Постановление": {"new": 3},
        "president:Указ": {"skipped": 1},
    }


def test_collect_stats_to_dict_includes_by_type():
    stats = CollectStats()
    DailyCollector._bump_type(stats, "government:Постановление", "new", 1)
    assert stats.to_dict()["by_type"] == {"government:Постановление": {"new": 1}}
