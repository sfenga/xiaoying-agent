"""ReAct 循环行为:各场景决策路径、步数上限、Trace 结构。"""
from __future__ import annotations

from src.kb_agent.store import DocStore

from .conftest import DATA_PATH, make_history


def test_case1_clear_answer(agent):
    r = agent.run("每个月吃饭有补贴吗?能补多少?")
    assert r.status == "answered"
    assert r.answer and "300" in r.answer
    assert [c.doc_id for c in r.citations] == ["D04"]
    store = DocStore.load(DATA_PATH)
    assert r.citations[0].quote in store.get("D04").full_text()
    assert r.steps_used == len(r.trace)
    assert r.trace[0].tool == "search"
    assert r.trace[-1].tool == "finish"
    assert all(s.thought for s in r.trace)          # 每步都有决策依据
    assert all(s.observation for s in r.trace[:-1])  # 中间步骤都有观察


def test_case4_paraphrase_uses_rewrite(agent):
    """口语化问题:首轮检索无结果 → 同义词改写 → 命中 → 读取作答。"""
    r = agent.run("工作满一年能休几天假?")
    assert r.status == "answered"
    assert "5 天" in r.answer
    assert [c.doc_id for c in r.citations] == ["D03"]
    search_steps = [s for s in r.trace if s.tool == "search"]
    assert len(search_steps) == 2                    # 改写重试发生了
    assert "改写" in search_steps[1].thought or "同义词" in search_steps[1].thought


def test_case3_out_of_scope_with_gaps(agent):
    r = agent.run("公司附近有什么好吃的餐厅推荐?")
    assert r.status == "out_of_scope"
    assert r.answer is None
    assert r.citations == []                          # 不编造、不乱引用
    assert r.gaps
    search_steps = [s for s in r.trace if s.tool == "search"]
    assert len(search_steps) == 2                     # 改写重试后仍无结果
    queries = [s.params["query"] for s in search_steps]
    assert len(set(queries)) == 2                     # 两次查询不同(真的改写了)


def test_case5_context_followup(agent):
    r1 = agent.run("每个月吃饭有补贴吗?能补多少?")
    r2 = agent.run("那上下班路上的呢?", history=make_history(r1))
    assert r2.status == "answered"
    assert "200" in r2.answer
    assert [c.doc_id for c in r2.citations] == ["D04"]
    first_search = next(s for s in r2.trace if s.tool == "search")
    assert "历史" in first_search.thought             # 决策依据说明结合了历史
    assert "补贴" in first_search.params["query"]     # 查询合并了上一轮主题词
    assert r2.history and r2.history[0]["question"] == r1.question


def test_case5_without_history_still_answered(agent):
    """同一问题脱离上下文也能靠别名规则回答(但路径不同)。"""
    r = agent.run("那上下班路上的呢?")
    assert r.status == "answered"
    assert "200" in r.answer


def test_step_limit_returns_explicit_unfinished(agent_factory):
    agent = agent_factory(max_steps=2)
    r = agent.run("报销申请的期限是多久?")  # 该场景完整需要 4 步
    assert r.status == "unfinished"
    assert r.limit_reached is True
    assert r.steps_used == 2
    assert r.answer is None
    assert r.citations == []
    assert any("上限" in g for g in r.gaps)


def test_step_limit_one(agent_factory):
    agent = agent_factory(max_steps=1)
    r = agent.run("每个月吃饭有补贴吗?能补多少?")
    assert r.status == "unfinished" and r.limit_reached


def test_empty_question_asks_clarification(agent):
    r = agent.run("   ")
    assert r.status == "clarification_needed"
    assert r.next_question_to_user
    assert r.steps_used == 0


def test_invalid_finish_becomes_feedback_and_model_self_corrects(agent):
    """finish 校验失败必须作为观察反馈给模型(而非崩溃),模型修正后正常结束。"""

    class FlipFlopModel:
        engine = "mock"
        name = "flipflop"

        def __init__(self):
            self.calls = 0

        def decide(self, question, history, steps, steps_left):
            self.calls += 1
            if self.calls == 1:
                return {"thought": "先给个非法状态试试", "tool": "finish", "params": {"status": "ok"}}
            assert steps[-1].observation.ok is False
            assert "status 非法" in steps[-1].observation.error
            return {
                "thought": "按错误反馈修正为合法状态",
                "tool": "finish",
                "params": {"status": "out_of_scope", "gaps": ["测试用"], "topics": []},
            }

    model = FlipFlopModel()
    agent.model = model
    r = agent.run("每个月吃饭有补贴吗?")
    assert model.calls == 2
    assert r.status == "out_of_scope"
    assert r.steps_used == 2
    assert r.trace[0].observation.ok is False
    assert r.trace[0].next_action  # 非法 finish 后的后续动作已被记录


def test_trace_records_next_action_chain(agent):
    r = agent.run("每个月吃饭有补贴吗?能补多少?")
    assert r.trace[0].next_action and r.trace[0].next_action.startswith("read")
    assert r.trace[1].next_action and r.trace[1].next_action.startswith("finish")
    assert r.trace[-1].next_action == "(结束)"


def test_conflict_resolved_by_explicit_doc(agent):
    """冲突场景闭环:用户确认制度版本后,直接读取指定文档作答,不再检索。"""
    r1 = agent.run("报销申请的期限是多久?")
    assert r1.status == "needs_confirmation"
    r2 = agent.run("按 D01 的规定算", history=make_history(r1))
    assert r2.status == "answered"
    assert "30 天" in r2.answer
    assert [c.doc_id for c in r2.citations] == ["D01"]
    assert [s.tool for s in r2.trace] == ["read", "finish"]
    assert "指定了文档" in r2.trace[0].thought


def test_followup_new_topic_on_confirmed_doc(agent):
    """确认制度版本后的新主题追问:新主题接管,答案引用指定文档中的对应条款。"""
    r1 = agent.run("报销申请的期限是多久?")
    r2 = agent.run("按D01算,那住宿费标准呢?", history=make_history(r1))
    assert r2.status == "answered"
    assert "500 元" in r2.answer
    assert [c.doc_id for c in r2.citations] == ["D01"]
    assert r2.trace[0].tool == "read"  # 中文语境直读同样生效


def test_followup_topic_absent_in_confirmed_doc_asks_clarification(agent):
    """确认文档中根本没有新主题的条款 → 如实澄清,不拿无关条款充数。"""
    r1 = agent.run("报销申请的期限是多久?")
    r2 = agent.run("按 D01 算,那年假有几天?", history=make_history(r1))
    assert r2.status == "clarification_needed"
    assert r2.citations == []  # 不用 D01 的无关条款答年假问题
    assert any("年假" in g for g in r2.gaps)
    assert r2.next_question_to_user


def test_doc_ref_not_in_history_falls_back_to_search(agent):
    """引用了历史中未出现过的文档 → 不直读,走常规检索流程重新对齐证据。"""
    r1 = agent.run("每个月吃饭有补贴吗?能补多少?")  # 历史引用只有 D04
    r2 = agent.run("按 D99 算", history=make_history(r1))
    assert r2.trace[0].tool == "search"  # 未采纳无效文档引用


def test_doc_ref_without_context_asks_clarification(agent):
    """无任何上下文时只说「按D01算」:应请求澄清,而不是误报资料外。"""
    r = agent.run("按D01算")
    assert r.status == "clarification_needed"
    assert r.citations == []
    assert r.next_question_to_user


def test_mock_does_not_hardcode_top_k(agent_factory):
    """--top-k 配置必须全链路生效(Mock 不得硬编码 top_k)。"""
    a = agent_factory(top_k=1)
    r = a.run("报销申请的期限是多久?")
    search_obs = r.trace[0].observation
    assert search_obs.params["top_k"] == 1
    assert len(search_obs.data["hits"]) <= 1


def test_engine_and_model_recorded(agent):
    r = agent.run("每个月吃饭有补贴吗?能补多少?")
    assert r.engine == "mock"
    assert r.model == "mock-policy-v1"
    assert r.max_steps == 8


def test_trace_records_params_and_observations(agent):
    r = agent.run("每个月吃饭有补贴吗?能补多少?")
    search_step = r.trace[0]
    assert "query" in search_step.params
    assert search_step.observation.summary
    read_step = next(s for s in r.trace if s.tool == "read")
    assert read_step.params["doc_id"] == "D04"
    assert read_step.observation.data["doc"]["title"]
