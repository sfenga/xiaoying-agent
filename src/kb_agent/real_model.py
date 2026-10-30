"""真实模型路径:把 ReAct 循环状态渲染为提示词,让 LLM 逐步输出动作 JSON。"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .llm import OpenAICompatLLM, parse_action
from .schemas import HistoryTurn, TOOL_FINISH, TOOL_READ, TOOL_SEARCH, TraceStep

SYSTEM_PROMPT = """你是企业制度/FAQ 问答 Agent,只能依据工具返回的文档内容回答问题,严禁编造。

你可以反复调用以下工具,每次输出且仅输出一个 JSON 动作对象(不要输出其他文字):

1. 检索文档片段:
{"thought": "一句话决策依据", "tool": "search", "params": {"query": "检索词,空格分隔多个词", "top_k": 4}}
2. 读取文档原文(先检索到 doc_id 再读取;可指定 section 章节名):
{"thought": "一句话决策依据", "tool": "read", "params": {"doc_id": "D01", "section": "可选,章节名"}}
3. 结束并给出最终交付:
{"thought": "一句话决策依据", "tool": "finish", "params": {
    "status": "answered | needs_confirmation | out_of_scope | clarification_needed | unfinished",
    "answer": "面向用户的回答文本;无答案时为 null",
    "citations": [{"doc_id": "D01", "section": "章节名", "quote": "逐字摘自该文档的原文片段"}],
    "conflicts": [{"topic": "冲突主题", "options": [
        {"doc_id": "D01", "section": "章节名", "quote": "原文", "value": "30 天", "evidence": "read 或 snippet"}]}],
    "gaps": ["资料缺口说明"],
    "next_question_to_user": "需要向用户追问的问题,无则 null",
    "topics": ["本轮对话主题词,供后续追问使用"]}}

必须遵守的规则:
1. quote 必须逐字摘自文档原文(标题/章节名/正文),评审会逐字校验;禁止改写、拼接或杜撰。
2. 多个文档对同一问题给出不同规定时,不得自行选择答案:列出全部冲突(带各自 doc_id 与原文),
   status 用 needs_confirmation,并在 next_question_to_user 中请用户确认适用的制度/范围。
3. 检索无结果时:先改写查询(同义词、口语说法、上下位词)再试一次;仍无结果则 status 用
   out_of_scope,在 gaps 中说明资料缺口,严禁编造答案。
4. 用户问题含有指代(如"那……呢")时,结合对话历史理解真实意图后再检索。
5. 回答必须给出发明文号(doc_id)与原文片段;没有文档依据就不要回答。
6. 工具报错时,根据错误信息调整动作(换文档、换查询词或如实说明缺口),不要重复同一失败动作。
7. 只输出一个 JSON 对象;不要用 markdown 代码块以外的文字解释。
"""


def render_history(history: List[HistoryTurn]) -> str:
    if not history:
        return "(无对话历史)"
    lines = []
    for i, turn in enumerate(history, 1):
        cited = ",".join(turn.cited_doc_ids) or "无"
        lines.append(f"[第{i}轮] 用户:{turn.question}")
        lines.append(f"[第{i}轮] 助手(status={turn.status},引用:{cited}):{turn.answer}")
    return "\n".join(lines)


def render_observation_data(data: Any, limit: int = 1200) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(data)
    if len(text) > limit:
        text = text[:limit] + f"…(截断,共 {len(text)} 字符)"
    return text


def render_steps(steps: List[TraceStep]) -> str:
    if not steps:
        return "(尚未执行任何步骤)"
    lines = []
    for s in steps:
        params = json.dumps(s.params, ensure_ascii=False)
        lines.append(f"Step {s.step} | 决策依据:{s.thought or '(无)'}")
        lines.append(f"  动作:{s.tool} {params}")
        if s.observation is not None:
            obs = s.observation
            if obs.ok:
                lines.append(f"  观察摘要:{obs.summary}")
                if obs.data is not None:
                    lines.append(f"  观察数据:{render_observation_data(obs.data)}")
            else:
                lines.append(f"  观察摘要:{obs.summary};错误:{obs.error}")
    return "\n".join(lines)


def build_user_prompt(question: str, history: List[HistoryTurn], steps: List[TraceStep], steps_left: int) -> str:
    return (
        f"## 对话历史\n{render_history(history)}\n\n"
        f"## 本轮用户问题\n{question}\n\n"
        f"## 已执行步骤与观察\n{render_steps(steps)}\n\n"
        f"剩余可用步数:{steps_left}。\n"
        "请根据以上观察决定下一步:继续调用 search/read,或输出 finish 给出最终交付。"
        "只输出一个 JSON 动作对象。"
    )


class LLMReActModel:
    """真实模型决策器:每一步调用 LLM 产出动作。输出不可解析时返回无效动作,
    由循环把"解析失败"作为观察反馈给模型,促使其自我修正。"""

    engine = "real"

    def __init__(self, llm: OpenAICompatLLM):
        self.llm = llm

    @property
    def name(self) -> str:
        return self.llm.model

    def decide(self, question: str, history: List[HistoryTurn], steps: List[TraceStep], steps_left: int) -> Dict[str, Any]:
        user_prompt = build_user_prompt(question, history, steps, steps_left)
        content = self.llm.chat(SYSTEM_PROMPT, user_prompt)
        action = parse_action(content)
        if action is None:
            return {
                "thought": "模型输出无法解析为动作 JSON(将收到格式错误反馈)",
                "tool": "__invalid__",
                "params": {"raw_output": content[:400]},
            }
        action.setdefault("thought", "")
        action.setdefault("params", {})
        return action
