"""文档库加载与校验。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.kb_agent.store import DocStore

from .conftest import DATA_PATH


@pytest.fixture()
def store():
    return DocStore.load(DATA_PATH)


def test_load_all_documents(store):
    assert len(store) == 8
    ids = [d.doc_id for d in store.all()]
    assert ids == ["D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08"]


def test_doc_fields(store):
    d01 = store.get("D01")
    assert d01.title == "员工费用报销制度"
    assert d01.version_date == "2023-01-15"
    assert d01.applies_to == ""  # 未注明适用范围(冲突场景的关键设定)
    assert any(s.heading == "报销期限" for s in d01.sections)
    assert "30 天" in [s.text for s in d01.sections if s.heading == "报销期限"][0]


def test_get_missing_raises(store):
    with pytest.raises(KeyError):
        store.get("D99")


def test_full_text_contains_section_text(store):
    d04 = store.get("D04")
    text = d04.full_text()
    for sec in d04.sections:
        assert sec.text in text
        assert sec.heading in text


def test_duplicate_doc_id_rejected(tmp_path):
    payload = {"documents": [
        {"doc_id": "X1", "title": "a", "version_date": "2024-01-01", "sections": [{"heading": "h", "text": "t"}]},
        {"doc_id": "X1", "title": "b", "version_date": "2024-01-02", "sections": [{"heading": "h", "text": "t"}]},
    ]}
    p = tmp_path / "dup.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        DocStore.load(p)


def test_missing_field_rejected(tmp_path):
    payload = {"documents": [{"doc_id": "X1", "title": "a", "sections": []}]}
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="缺少字段"):
        DocStore.load(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        DocStore.load(tmp_path / "nope.json")
