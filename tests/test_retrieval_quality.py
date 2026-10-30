"""检索质量评测集:口语/改写/复合查询的召回断言(支撑"检索改进"这一高分依据)。

新增查询或调整检索器后在此登记期望文档;任何召回回归都会被本文件捕获。
"""
from __future__ import annotations

import json

import pytest

from src.kb_agent.retrieval import RetrievalIndex, expand_terms
from src.kb_agent.store import DocStore

from .conftest import DATA_PATH, RULES_PATH


@pytest.fixture(scope="module")
def index():
    store = DocStore.load(DATA_PATH)
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return RetrievalIndex(store, rules)


def _terms(question, rules):
    return expand_terms(question, [], rules)[1]


RULES = json.loads(RULES_PATH.read_text(encoding="utf-8"))

# (问题, 期望出现在 top-4 命中文档集合中的 doc_id 集合;空集合 = 期望零命中)
CASES = [
    ("报销申请的期限是多久?", {"D01", "D02"}),
    ("发票最晚什么时候要交?", {"D01", "D02"}),
    ("工作满一年能休几天假?", {"D03"}),
    ("每个月吃饭有补贴吗?", {"D04"}),
    ("上下班有交通补贴吗?", {"D04"}),
    ("夏天室外岗位有什么补贴?", {"D04"}),
    ("出差住宿费标准是多少?", {"D01"}),
    ("出差期间吃饭有补助吗?", {"D07"}),
    ("办公系统密码多久换一次?", {"D05"}),
    ("上班迟到会怎么处理?", {"D03"}),
    ("离职时要归还办公用品吗?", {"D06"}),
    ("试用期一般是多久?", {"D08"}),
    ("新员工报到要带什么材料?", {"D08"}),
    ("对外发文件需要审批吗?", {"D05"}),
    ("忘打卡了怎么办?", {"D03"}),
    # 资料外负例:期望零命中
    ("公司年会抽奖的奖品是什么?", set()),
    ("公司附近有什么好吃的餐厅推荐?", set()),
]


@pytest.mark.parametrize("question,expected", CASES)
def test_recall(index, question, expected):
    hits = index.search(_terms(question, RULES), top_k=4, question=question)
    got = {h.doc_id for h in hits}
    missing = expected - got
    assert not missing, f"「{question}」召回缺失 {missing},实际命中 {sorted(got)}"
    if not expected:
        assert not got, f"「{question}」应零命中,实际命中 {sorted(got)}"


def test_conflict_query_ranks_both_period_sections_first(index):
    """冲突查询:D01/D02 的「报销期限」章节应排在最前(数值片段可见才能触发冲突核查)。"""
    hits = index.search(_terms("报销申请的期限是多久?", RULES), top_k=4, question="报销申请的期限是多久?")
    top2 = [(h.doc_id, h.heading) for h in hits[:2]]
    assert ("D01", "报销期限") in top2 and ("D02", "报销期限") in top2


def test_snippets_of_period_sections_contain_values(index):
    """触发冲突的关键:期限章节的检索片段必须带数值。"""
    hits = index.search(_terms("报销申请的期限是多久?", RULES), top_k=6, question="报销")
    by_key = {(h.doc_id, h.heading): h.snippet for h in hits}
    assert "30" in by_key[("D01", "报销期限")]
    assert "15" in by_key[("D02", "报销期限")]
