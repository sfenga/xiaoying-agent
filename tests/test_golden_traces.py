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


@pytest.mark.parametrize("case_id,expected", list(EXPECTED_TOOL_SEQUENCE.items()))
def test_golden_tool_sequence(case_id, expected):
    seqs = {cid: [] for cid in EXPECTED_TOOL_SEQUENCE}
    for cid, result in _results():
        seqs[cid].append([s.tool for s in result.trace])
    assert seqs[case_id] == expected, f"{case_id} 动作序列偏离黄金轨迹: {seqs[case_id]}"


def test_case7_turn1_is_conflict_turn2_resolved():
    seqs = {cid: [] for cid in EXPECTED_TOOL_SEQUENCE}
    for cid, result in _results():
        seqs[cid].append(result)
    r1, r2 = seqs["case7_conflict_resolved"]
    assert r1.status == "needs_confirmation"
    assert r2.status == "answered"
    assert [c.doc_id for c in r2.citations] == ["D01"]
    assert "30 天" in (r2.answer or "")
