"""冲突处理(核心验收点):列冲突不擅自作答;内容替换后答案与动作随之改变。"""
from __future__ import annotations

import pytest

from src.kb_agent.store import DocStore

from .conftest import DATA_PATH, write_docs_variant


def test_conflict_lists_both_documents(agent):
    r = agent.run("报销申请的期限是多久?")
    assert r.status == "needs_confirmation"
    assert len(r.conflicts) == 1
    conflict = r.conflicts[0]
    values = {o.value for o in conflict.options}
    assert values == {"30 天", "15 天"}
    docs = {o.doc_id for o in conflict.options}
    assert docs == {"D01", "D02"}
    # 引用与冲突片段逐字可核验
    store = DocStore.load(DATA_PATH)
    for o in conflict.options:
        assert o.quote in store.get(o.doc_id).full_text()
    for c in r.citations:
        assert c.quote in store.get(c.doc_id).full_text()


def test_conflict_does_not_pick_a_side(agent):
    """不得凭空选择其中一个答案:回答必须呈现冲突并请求确认。"""
    r = agent.run("报销申请的期限是多久?")
    assert "不一致" in r.answer
    assert "无法给出单一结论" in r.answer
    assert r.next_question_to_user and "确认" in r.next_question_to_user
    assert r.gaps  # 说明缺口:未注明适用范围与优先级


def test_single_document_no_false_conflict(agent):
    """只检索到 D01 且无冲突时,可依据 D01 回答(参考实例要求)。"""
    r = agent.run("出差住宿费标准是多少?")
    assert r.status == "answered"
    assert "500 元" in r.answer
    assert [c.doc_id for c in r.citations] == ["D01"]
    assert r.conflicts == []


def test_content_swap_changes_conflict_values(agent_factory, tmp_path):
    """把 D01 的 30 天改为 45 天:冲突数值必须跟着变(审核要点:替换文档内容核对动作)。"""
    variant = write_docs_variant(tmp_path, {"D01": [("报销期限", "30 天", "45 天")]})
    agent = agent_factory(data_path=variant)
    r = agent.run("报销申请的期限是多久?")
    assert r.status == "needs_confirmation"
    values = {o.value for o in r.conflicts[0].options}
    assert values == {"45 天", "15 天"}


def test_content_swap_equal_values_no_conflict(agent_factory, tmp_path):
    """把 D02 改成与 D01 相同的 30 天:不应再报冲突,依据文档作答。"""
    variant = write_docs_variant(tmp_path, {"D02": [("报销期限", "15 天内", "30 天内")]})
    agent = agent_factory(data_path=variant)
    r = agent.run("报销申请的期限是多久?")
    assert r.status == "answered"
    assert "30 天" in r.answer
    assert r.conflicts == []


def test_content_swap_remove_numbers_no_false_conflict(agent_factory, tmp_path):
    """D02 报销期限条款改为无数值内容:不应误判冲突。"""
    variant = write_docs_variant(
        tmp_path,
        {"D02": [("报销期限", "员工须在费用发生后 15 天内提交报销申请,逾期系统将自动关闭申请入口。", "报销申请应当通过 OA 系统提交。")]},
    )
    agent = agent_factory(data_path=variant)
    r = agent.run("报销申请的期限是多久?")
    assert r.status == "answered"
    assert "30 天" in r.answer


def test_conflict_scenario_read_failure_still_flags_conflict(agent_factory):
    """工具失败注入下仍应识别冲突(读取失败的一侧用检索片段作证据)。"""
    agent = agent_factory(inject="read_once")
    r = agent.run("报销申请的期限是多久?")
    assert r.status == "needs_confirmation"
    values = {o.value for o in r.conflicts[0].options}
    assert values == {"30 天", "15 天"}
    evidences = {o.doc_id: o.evidence for o in r.conflicts[0].options}
    assert set(evidences.values()) == {"snippet", "read"}  # 一侧来自片段,一侧来自原文
    store = DocStore.load(DATA_PATH)
    for o in r.conflicts[0].options:  # 片段证据同样逐字可核验
        assert o.quote in store.get(o.doc_id).full_text()
