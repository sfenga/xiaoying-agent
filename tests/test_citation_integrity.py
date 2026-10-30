"""引用完整性:任何交付的引用都必须逐字存在于被引文档(评审审核要点)。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.kb_agent.cli import DEMO_CASES, build_agent
from src.kb_agent.config import Config
from src.kb_agent.schemas import HistoryTurn
from src.kb_agent.store import DocStore

from .conftest import DATA_PATH, RULES_PATH, make_history

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _iter_demo_results():
    cfg = Config(engine="mock", engine_request="mock", data_path=DATA_PATH, rules_path=RULES_PATH)
    for case in DEMO_CASES:
        agent, _ = build_agent(cfg, inject_override=case.inject)
        turn1 = None
        history = []
        if case.turn1_question:
            turn1 = agent.run(case.turn1_question)
            history = make_history(turn1)
        result = agent.run(case.question, history=history)
        yield case.case_id, result


def _assert_citations_valid(result, store):
    for c in result.citations:
        doc = store.get(c.doc_id)
        assert c.quote in doc.full_text(), f"引用不成立: {c.doc_id} 「{c.quote[:30]}…」"
        assert c.version_date == doc.version_date
        assert c.title == doc.title
    for conflict in result.conflicts:
        for o in conflict.options:
            doc = store.get(o.doc_id)
            assert o.quote in doc.full_text()
            assert o.version_date == doc.version_date


def test_live_run_citations_valid():
    store = DocStore.load(DATA_PATH)
    for case_id, result in _iter_demo_results():
        _assert_citations_valid(result, store)


def test_live_run_answered_has_citations():
    for case_id, result in _iter_demo_results():
        if result.status == "answered":
            assert result.citations, f"{case_id}: answered 却没有引用"
            assert result.answer


def test_committed_examples_citations_valid():
    """examples/ 中提交的 output.json 同样必须通过逐字校验。"""
    store = DocStore.load(DATA_PATH)
    case_dirs = [d for d in EXAMPLES_DIR.iterdir() if d.is_dir() and d.name.startswith("case")]
    assert len(case_dirs) >= 6, "examples/ 下应至少有 6 组材料"
    for case_dir in case_dirs:
        output = case_dir / "output.json"
        assert output.is_file(), f"{case_dir} 缺少 output.json"
        payload = json.loads(output.read_text(encoding="utf-8"))
        for c in payload.get("citations", []):
            doc = store.get(c["doc_id"])
            assert c["quote"] in doc.full_text(), f"{case_dir.name}: 引用不成立 {c['doc_id']}"
        for conflict in payload.get("conflicts", []):
            for o in conflict.get("options", []):
                doc = store.get(o["doc_id"])
                assert o["quote"] in doc.full_text(), f"{case_dir.name}: 冲突引用不成立 {o['doc_id']}"
        for dropped in payload.get("dropped_citations", []):
            raise AssertionError(f"{case_dir.name}: 存在被剔除的无效引用 {dropped}")


def test_dropped_citation_reported(agent):
    """模型给出不可核验引用时,应被剔除并如实记录,而不是原样透传。"""

    class BadModel:
        engine = "mock"
        name = "bad-model"

        def decide(self, question, history, steps, steps_left):
            if not steps:
                return {"thought": "t", "tool": "search", "params": {"query": "补贴"}}
            return {
                "thought": "t",
                "tool": "finish",
                "params": {
                    "status": "answered",
                    "answer": "编造的回答",
                    "citations": [
                        {"doc_id": "D04", "section": "餐补", "quote": "工作日午餐补贴为每月 300 元,随当月工资发放;"},
                        {"doc_id": "D04", "section": "餐补", "quote": "这句原文里根本不存在"},
                        {"doc_id": "D99", "section": "x", "quote": "whatever"},
                    ],
                    "topics": [],
                },
            }

    from src.kb_agent.tools import ReadDocumentTool, SearchDocumentsTool, ToolBox
    from src.kb_agent.retrieval import RetrievalIndex
    from src.kb_agent.agent import ReActAgent
    import json as _json

    store = DocStore.load(DATA_PATH)
    rules = _json.loads(RULES_PATH.read_text(encoding="utf-8"))
    box = ToolBox(SearchDocumentsTool(RetrievalIndex(store, rules), rules=rules), ReadDocumentTool(store))
    bad_agent = ReActAgent(BadModel(), box, store, max_steps=5, engine="mock", model_name="bad-model")
    r = bad_agent.run("每个月吃饭有补贴吗?")
    assert r.status == "answered"
    assert len(r.citations) == 1  # 合法引用保留
    assert len(r.dropped_citations) == 2  # 非法引用被剔除并记录
    assert any("剔除" in n for n in r.notes)
