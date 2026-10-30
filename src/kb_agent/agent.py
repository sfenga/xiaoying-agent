"""ReAct 决策循环:模型选动作 → 执行工具 → 观察结果 → 模型调整下一步或结束。

循环职责:
- 驱动"决策-执行-观察"直到模型给出合法 finish,或达到步数上限(返回明确的未完成状态);
- 对 finish 参数做校验(状态合法、引用逐字可核验、冲突需附原文),不合法则把错误作为
  观察反馈给模型,促使其自我修正;
- 记录完整 Trace(步骤、决策依据、工具参数、观察摘要)。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import json

from .llm import LLMError
from .schemas import (
    ALL_STATUSES,
    AgentResult,
    Citation,
    Conflict,
    ConflictOption,
    HistoryTurn,
    Observation,
    STATUS_ANSWERED,
    STATUS_NEEDS_CONFIRMATION,
    STATUS_OUT_OF_SCOPE,
    TOOL_FINISH,
    TraceStep,
    VALID_TOOLS,
)
from .store import Doc, DocStore
from .tools import ToolBox


def _link_next_action(steps: List[TraceStep]) -> None:
    """把最新一步的动作回填为上一步的「后续动作」,满足考核对 Trace 记录的要求。"""
    if len(steps) < 2:
        return
    prev, latest = steps[-2], steps[-1]
    prev.next_action = (
        f"{latest.tool} {json.dumps(latest.params, ensure_ascii=False)}"
        if latest.tool != TOOL_FINISH
        else "finish(给出最终交付,循环结束)"
    )


class ReActAgent:
    def __init__(
        self,
        model: Any,
        toolbox: ToolBox,
        store: DocStore,
        max_steps: int = 8,
        engine: str = "mock",
        model_name: str = "mock-policy",
    ):
        self.model = model
        self.toolbox = toolbox
        self.store = store
        self.max_steps = max(1, max_steps)
        self.engine = engine
        self.model_name = model_name

    # ------------------------------------------------------------------ #
    def run(self, question: str, history: Optional[List[HistoryTurn]] = None) -> AgentResult:
        history = list(history or [])
        steps: List[TraceStep] = []
        failure_note: Optional[str] = None
        self._dropped = []
        self._notes = []

        question = str(question or "").strip()
        if not question:
            return self._result(
                question,
                history,
                {
                    "status": "clarification_needed",
                    "answer": None,
                    "citations": [],
                    "conflicts": [],
                    "gaps": ["问题为空"],
                    "next_question_to_user": "请输入您想了解的制度或福利问题。",
                    "topics": [],
                },
                steps,
                steps_used=0,
                limit_reached=False,
            )

        for step_no in range(1, self.max_steps + 1):
            steps_left = self.max_steps - step_no + 1
            try:
                action = self.model.decide(question, history, steps, steps_left)
            except LLMError as exc:
                failure_note = f"模型服务调用失败: {exc}"
                break
            except Exception as exc:  # 模型实现缺陷不应导致进程崩溃
                failure_note = f"模型决策异常: {exc!r}"
                break

            thought = str(action.get("thought", "")).strip()
            tool = str(action.get("tool", "")).strip().lower()
            params = action.get("params") or {}
            if not isinstance(params, dict):
                params = {"raw_params": params}

            if tool == TOOL_FINISH:
                final, info = self._build_final(params)
                if final is not None:
                    steps.append(
                        TraceStep(
                            step_no,
                            thought,
                            TOOL_FINISH,
                            params,
                            Observation(TOOL_FINISH, params, True, info),
                        )
                    )
                    _link_next_action(steps)
                    steps[-1].next_action = "(结束)"
                    return self._result(question, history, final, steps, step_no, limit_reached=False)
                # finish 参数不合法 → 作为观察反馈,模型可自我修正
                steps.append(
                    TraceStep(
                        step_no,
                        thought,
                        TOOL_FINISH,
                        params,
                        Observation(TOOL_FINISH, params, False, "finish 参数校验未通过", error=info),
                    )
                )
                _link_next_action(steps)
                continue

            if tool not in VALID_TOOLS:
                steps.append(
                    TraceStep(
                        step_no,
                        thought,
                        tool or "unknown",
                        params,
                        Observation(
                            tool or "unknown",
                            params,
                            False,
                            "未知动作",
                            error=f"未知工具 {tool!r},可用动作: search / read / finish",
                        ),
                    )
                )
                continue

            obs = self.toolbox.execute(tool, params)
            steps.append(TraceStep(step_no, thought, tool, params, obs))
            _link_next_action(steps)

        # ---- 未正常结束:达到上限或模型故障,返回明确的未完成状态 ----
        if failure_note:
            gaps = [failure_note]
        else:
            gaps = [f"已达最大步数上限 {self.max_steps},任务未完成;已完成的检索/读取记录见 trace。"]
        return self._result(
            question,
            history,
            {
                "status": "unfinished",
                "answer": None,
                "citations": [],
                "conflicts": [],
                "gaps": gaps,
                "next_question_to_user": None,
                "topics": [],
            },
            steps,
            steps_used=len(steps),
            limit_reached=failure_note is None,
        )

    # ------------------------------------------------------------------ #
    def _result(
        self,
        question: str,
        history: List[HistoryTurn],
        final: Dict[str, Any],
        steps: List[TraceStep],
        steps_used: int,
        limit_reached: bool,
    ) -> AgentResult:
        return AgentResult(
            question=question,
            status=final["status"],
            answer=final.get("answer"),
            citations=final.get("citations", []),
            conflicts=final.get("conflicts", []),
            gaps=final.get("gaps", []),
            next_question_to_user=final.get("next_question_to_user"),
            topics=final.get("topics", []),
            steps_used=steps_used,
            max_steps=self.max_steps,
            limit_reached=limit_reached,
            engine=self.engine,
            model=self.model_name,
            history=[h.to_dict() for h in history],
            trace=steps,
            dropped_citations=self._dropped,
            notes=self._notes,
        )

    # ------------------------------------------------------------------ #
    # finish 参数校验与引用核验
    # ------------------------------------------------------------------ #
    def _build_final(self, params: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
        """返回 (最终交付 dict, 摘要/错误说明)。final 为 None 表示校验未通过。

        注意:同一 run 内可能被多次调用(finish 校验失败后的重试),
        _dropped/_notes 只在 run() 开始时重置,以便累积记录每次校验的剔除项。
        """
        status = str(params.get("status", "")).strip()
        if status not in ALL_STATUSES:
            return None, f"status 非法: {status!r},必须是 {' / '.join(ALL_STATUSES)}"

        citations, cit_errors = self._validate_citations(params.get("citations") or [])
        conflicts, conf_errors = self._validate_conflicts(params.get("conflicts") or [])
        errors = cit_errors + conf_errors

        answer = params.get("answer")
        answer = answer.strip() if isinstance(answer, str) else None
        gaps = [str(g) for g in (params.get("gaps") or []) if str(g).strip()]
        next_q = params.get("next_question_to_user")
        next_q = next_q.strip() if isinstance(next_q, str) else None
        topics = [str(t) for t in (params.get("topics") or []) if str(t).strip()]

        # 状态级约束:回答必须有可核验依据;冲突/资料外必须说明
        if status == STATUS_ANSWERED and not citations:
            return None, "status=answered 需要至少一条可核验引用(逐字原文);无文档依据请改用 out_of_scope 或 clarification_needed"
        if status == STATUS_NEEDS_CONFIRMATION and not conflicts and not next_q:
            return None, "status=needs_confirmation 需要提供 conflicts 或 next_question_to_user"
        if status == STATUS_OUT_OF_SCOPE and not gaps:
            return None, "status=out_of_scope 需要在 gaps 中说明资料缺口"

        if errors:
            return None, ";".join(errors)
        if self._dropped:
            self._notes.append(f"已剔除 {len(self._dropped)} 条无法核验的引用(原文中不存在或文档不存在)")

        summary = f"最终交付: status={status},引用 {len(citations)} 条,冲突 {len(conflicts)} 组,缺口 {len(gaps)} 项"
        return (
            {
                "status": status,
                "answer": answer,
                "citations": citations,
                "conflicts": conflicts,
                "gaps": gaps,
                "next_question_to_user": next_q,
                "topics": topics,
            },
            summary,
        )

    def _check_quote(self, doc_id: str, quote: str, raw: Any, index_label: Any) -> Tuple[Optional[Doc], Optional[Dict[str, Any]]]:
        """校验 doc_id 存在且 quote 逐字可核验;失败时返回剔除记录。"""
        if not doc_id or not quote:
            return None, {"index": index_label, "reason": "缺少 doc_id 或 quote", "raw": raw}
        doc = self._get_doc(doc_id)
        if doc is None:
            return None, {"index": index_label, "reason": f"文档 {doc_id} 不存在", "raw": raw}
        if quote not in doc.full_text():
            return None, {
                "index": index_label,
                "reason": f"quote 未逐字出现在 {doc_id} 原文中",
                "quote": quote[:80],
                "raw": raw,
            }
        return doc, None

    def _validate_citations(self, raw_citations: Any) -> Tuple[List[Citation], List[str]]:
        valid: List[Citation] = []
        errors: List[str] = []
        if not isinstance(raw_citations, list):
            return [], ["citations 必须是数组"]
        for i, raw in enumerate(raw_citations):
            if not isinstance(raw, dict):
                errors.append(f"citations[{i}] 不是对象")
                continue
            doc_id = str(raw.get("doc_id", "")).strip()
            quote = str(raw.get("quote", "")).strip()
            section = str(raw.get("section", "")).strip()
            doc, dropped = self._check_quote(doc_id, quote, raw, i)
            if dropped is not None:
                self._dropped.append(dropped)
                continue
            assert doc is not None
            if not section:
                section = self._find_section(doc, quote)
            valid.append(
                Citation(doc_id=doc_id, title=doc.title, version_date=doc.version_date, section=section, quote=quote)
            )
        return valid, errors

    def _validate_conflicts(self, raw_conflicts: Any) -> Tuple[List[Conflict], List[str]]:
        valid: List[Conflict] = []
        errors: List[str] = []
        if not isinstance(raw_conflicts, list):
            return [], ["conflicts 必须是数组"]
        for i, raw in enumerate(raw_conflicts):
            if not isinstance(raw, dict):
                errors.append(f"conflicts[{i}] 不是对象")
                continue
            topic = str(raw.get("topic", "")).strip() or "(未注明主题)"
            options: List[ConflictOption] = []
            for j, opt in enumerate(raw.get("options") or []):
                if not isinstance(opt, dict):
                    errors.append(f"conflicts[{i}].options[{j}] 不是对象")
                    continue
                doc_id = str(opt.get("doc_id", "")).strip()
                quote = str(opt.get("quote", "")).strip()
                doc, dropped = self._check_quote(doc_id, quote, opt, f"conflict[{i}].option[{j}]")
                if dropped is not None:
                    self._dropped.append(dropped)
                    continue
                assert doc is not None
                section = str(opt.get("section", "")).strip() or (self._find_section(doc, quote) if quote else "")
                options.append(
                    ConflictOption(
                        doc_id=doc_id,
                        title=doc.title,
                        version_date=doc.version_date,
                        section=section,
                        quote=quote,
                        value=str(opt.get("value", "")).strip(),
                        evidence=str(opt.get("evidence", "read")).strip() or "read",
                    )
                )
            if len(options) >= 2:
                valid.append(Conflict(topic=topic, options=options))
            elif raw.get("options"):
                errors.append(f"conflicts[{i}] 有效选项不足 2 条(逐字校验未通过的已剔除)")
        return valid, errors

    def _get_doc(self, doc_id: str) -> Optional[Doc]:
        try:
            return self.store.get(doc_id)
        except KeyError:
            return None

    @staticmethod
    def _find_section(doc: Doc, quote: str) -> str:
        for sec in doc.sections:
            if quote in sec.text:
                return sec.heading
        return ""
