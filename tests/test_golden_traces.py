"""黄金轨迹:7 组验证用例的动作序列断言(防回归;策略调整导致路径变化时同步更新此表)。"""
from __future__ import annotations

import pytest

from src.kb_agent.cli import DEMO_CASES, build_agent
from src.kb_agent.config import Config

from .conftest import DATA_PATH, RULES_PATH, make_history

EXPECTED_TOOL_SEQUENCE = {
    # 每个用例对应若干轮,每轮一条动作序列(case5/case7 为两轮)
    "case1_clear_answer": [["search", "read", "finish"]],
    "case2_doc_conflict": [["search", "read", "read", "finish"]],
    "case3_out_of_scope": [["search", "search", "finish"]],
    "case4_paraphrase": [["search", "search", "read", "finish"]],
    "case5_context_followup": [["search", "read", "finish"], ["search", "read", "finish"]],
    "case6_tool_failure": [["search", "read", "read", "finish"]],  # 第一次 read 失败(注入)
    "case7_conflict_resolved": [["search", "read", "read", "finish"], ["read", "finish"]],
}


def _results():
    cfg = Config(engine="mock", engine_request="mock", data_path=DATA_PATH, rules_path=RULES_PATH)
    for case in DEMO_CASES:
        agent, _ = build_agent(cfg, inject_override=case.inject)
        if case.turn1_question:
            turn1 = agent.run(case.turn1_question)
            yield case.case_id, turn1
            yield case.case_id, agent.run(case.question, history=make_history(turn1))
        else:
            yield case.case_id, agent.run(case.question)


@pytest.fixture(scope="module")
def all_results():
    """全部用例只跑一次,供各参数化断言共享。"""
    seqs = {}
    for cid, result in _results():
        seqs.setdefault(cid, []).append(result)
    return seqs


def test_all_demo_cases_have_golden_sequences(all_results):
    """新增 DEMO_CASES 而未登记黄金轨迹时,在此显式失败并给出提示。"""
    unregistered = set(all_results) - set(EXPECTED_TOOL_SEQUENCE)
    assert not unregistered, f"以下用例尚未登记黄金轨迹(请更新 EXPECTED_TOOL_SEQUENCE): {sorted(unregistered)}"


@pytest.mark.parametrize("case_id,expected", list(EXPECTED_TOOL_SEQUENCE.items()))
def test_golden_tool_sequence(all_results, case_id, expected):
    seqs = [[s.tool for s in r.trace] for r in all_results[case_id]]
    assert seqs == expected, f"{case_id} 动作序列偏离黄金轨迹: {seqs}"


def test_case7_turn1_is_conflict_turn2_resolved(all_results):
    r1, r2 = all_results["case7_conflict_resolved"]
    assert r1.status == "needs_confirmation"
    assert r2.status == "answered"
    assert [c.doc_id for c in r2.citations] == ["D01"]
    assert "30 天" in (r2.answer or "")
