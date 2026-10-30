"""检索质量:命中、改写扩展、逐字片段、弱相关过滤。"""
from __future__ import annotations

import json

import pytest

from src.kb_agent.retrieval import RetrievalIndex, expand_terms
from src.kb_agent.store import DocStore

from .conftest import DATA_PATH, RULES_PATH


@pytest.fixture()
def index():
    store = DocStore.load(DATA_PATH)
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return RetrievalIndex(store, rules)


def test_expand_terms_domain_and_alias():
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    raw, expanded = expand_terms("每个月吃饭有补贴吗?", [], rules)
    assert "补贴" in raw and "餐补" in raw          # domain term + 口语别名
    assert "补助" in expanded and "津贴" in expanded  # 同义词扩展
    raw2, _ = expand_terms("工作满一年能休几天假?", [], rules)
    assert "年假" in raw2                            # 「几天假」→ 年假


def test_expand_terms_includes_history_topics():
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    raw, _ = expand_terms("那路上的呢?", ["交通", "补贴"], rules)
    assert "交通" in raw and "补贴" in raw


def test_search_hits_conflict_documents(index):
    hits = index.search(["报销", "期限"], top_k=4)
    by_doc = {h.doc_id for h in hits}
    assert {"D01", "D02"} <= by_doc
    headings = {h.heading for h in hits if h.doc_id in ("D01", "D02")}
    assert "报销期限" in headings


def test_search_paraphrase_via_expansion(index):
    assert index.search(["年假"], top_k=4) == []            # 文档里写的是「年休假」
    hits = index.search(["年假", "年休假", "带薪年假"], top_k=4)
    assert hits and hits[0].doc_id == "D03"


def test_search_out_of_domain_empty(index):
    assert index.search(["餐厅"], top_k=4) == []
    assert index.search(["公司附近有什么好吃的餐厅推荐?"], top_k=4) == []


def test_snippet_is_verbatim(index):
    store = DocStore.load(DATA_PATH)
    for terms in (["报销", "期限"], ["餐补", "补贴"], ["年假", "年休假"]):
        for hit in index.search(terms, top_k=4):
            doc = store.get(hit.doc_id)
            section = next(s for s in doc.sections if s.heading == hit.heading)
            assert hit.snippet in section.text, f"片段非逐字: {hit.doc_id}/{hit.heading}"


def test_search_deterministic(index):
    a = index.search(["报销", "期限"], top_k=4)
    b = index.search(["报销", "期限"], top_k=4)
    assert [(h.doc_id, h.heading, h.score) for h in a] == [(h.doc_id, h.heading, h.score) for h in b]


def test_top_k_limit(index):
    hits = index.search(["报销"], top_k=2)
    assert len(hits) <= 2


def test_empty_query(index):
    assert index.search([], top_k=4, question="") == []
