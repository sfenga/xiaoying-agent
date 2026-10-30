"""工具层行为:检索/读取观察、错误反馈、故障注入。"""
from __future__ import annotations

import json

import pytest

from src.kb_agent.retrieval import RetrievalIndex
from src.kb_agent.store import DocStore
from src.kb_agent.tools import (
    FailureInjector,
    ReadDocumentTool,
    SearchDocumentsTool,
    ToolBox,
)

from .conftest import DATA_PATH, RULES_PATH


@pytest.fixture()
def store():
    return DocStore.load(DATA_PATH)


@pytest.fixture()
def toolbox(store):
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    index = RetrievalIndex(store, rules)
    return ToolBox(
        SearchDocumentsTool(index, rules=rules),
        ReadDocumentTool(store),
        inject_failure="",
    )


def test_search_ok(toolbox):
    obs = toolbox.execute("search", {"query": "报销 期限"})
    assert obs.ok
    assert obs.tool == "search"
    assert obs.data["hits"]
    assert "命中" in obs.summary


def test_search_empty_query(toolbox):
    obs = toolbox.execute("search", {"query": "  "})
    assert not obs.ok
    assert "query" in obs.error


def test_read_ok(toolbox):
    obs = toolbox.execute("read", {"doc_id": "D01"})
    assert obs.ok
    assert obs.data["doc"]["doc_id"] == "D01"
    assert len(obs.data["sections"]) == 4


def test_read_missing_doc_lists_available(toolbox):
    obs = toolbox.execute("read", {"doc_id": "D99"})
    assert not obs.ok
    assert "D99" in obs.error and "可用文档" in obs.error


def test_read_section_filter(toolbox):
    obs = toolbox.execute("read", {"doc_id": "D01", "section": "报销期限"})
    assert obs.ok
    assert [s["heading"] for s in obs.data["sections"]] == ["报销期限"]


def test_read_unknown_section(toolbox):
    obs = toolbox.execute("read", {"doc_id": "D01", "section": "不存在的章节"})
    assert not obs.ok
    assert "可用章节" in obs.error


def test_unknown_tool(toolbox):
    obs = toolbox.execute("delete", {"doc_id": "D01"})
    assert not obs.ok
    assert "未知工具" in obs.error


def test_inject_read_once_fails_once(store):
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    index = RetrievalIndex(store, rules)
    box = ToolBox(SearchDocumentsTool(index, rules=rules), ReadDocumentTool(store), inject_failure="read_once")
    first = box.execute("read", {"doc_id": "D01"})
    assert not first.ok and "模拟工具故障" in first.error
    second = box.execute("read", {"doc_id": "D01"})
    assert second.ok


def test_inject_read_all_always_fails(store):
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    index = RetrievalIndex(store, rules)
    box = ToolBox(SearchDocumentsTool(index, rules=rules), ReadDocumentTool(store), inject_failure="read_all")
    assert not box.execute("read", {"doc_id": "D01"}).ok
    assert not box.execute("read", {"doc_id": "D02"}).ok
    assert box.execute("search", {"query": "报销"}).ok  # search 不受影响


def test_inject_search_once(store):
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    index = RetrievalIndex(store, rules)
    box = ToolBox(SearchDocumentsTool(index, rules=rules), ReadDocumentTool(store), inject_failure="search_once")
    assert not box.execute("search", {"query": "报销"}).ok
    assert box.execute("search", {"query": "报销"}).ok


def test_failure_injector_modes_covered():
    modes = {"", "read_once", "search_once", "read_all"}
    for mode in modes:
        FailureInjector(mode)  # 构造不抛错
