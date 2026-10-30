"""Trace 与结果的序列化 / Markdown 渲染。"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .schemas import (
    AgentResult,
    Citation,
    Conflict,
    ConflictOption,
    HistoryTurn,
    Observation,
    TraceStep,
)

MOCK_BANNER = (
    "⚠️ 本 Trace 由离线 Mock 决策策略生成:仅验证 ReAct 流程与工具链路,"
    "不证明真实模型的决策效果。"
)


def result_to_dict(result: AgentResult) -> Dict[str, Any]:
    return result.to_dict()


def _quote_line(c: Citation, index: int) -> str:
    return f"{index}. [{c.doc_id} v{c.version_date} §{c.section or '-'}]《{c.title}》 「{c.quote}」"


def result_from_dict(d: Dict[str, Any]) -> AgentResult:
    """从 output.json 的 dict 还原 AgentResult(供 `cli trace` 复现渲染)。"""
    trace: List[TraceStep] = []
    for s in d.get("trace", []):
        obs_raw = s.get("observation")
        obs = None
        if obs_raw:
            obs = Observation(
                tool=obs_raw.get("tool", ""),
                params=obs_raw.get("params", {}),
                ok=bool(obs_raw.get("ok")),
                summary=obs_raw.get("summary", ""),
                data=obs_raw.get("data"),
                error=obs_raw.get("error"),
            )
        trace.append(
            TraceStep(
                step=int(s.get("step", 0)),
                thought=s.get("thought", ""),
                tool=s.get("tool", ""),
                params=s.get("params", {}),
                observation=obs,
                next_action=s.get("next_action"),
            )
        )
    citations = [Citation(**c) for c in d.get("citations", [])]
    conflicts = [
        Conflict(
            topic=c.get("topic", ""),
            options=[ConflictOption(**o) for o in c.get("options", [])],
        )
        for c in d.get("conflicts", [])
    ]
    return AgentResult(
        question=d.get("question", ""),
        status=d.get("status", ""),
        answer=d.get("answer"),
        citations=citations,
        conflicts=conflicts,
        gaps=d.get("gaps", []),
        next_question_to_user=d.get("next_question_to_user"),
        topics=d.get("topics", []),
        steps_used=int(d.get("steps_used", 0)),
        max_steps=int(d.get("max_steps", 0)),
        limit_reached=bool(d.get("limit_reached")),
        engine=d.get("engine", ""),
        model=d.get("model", ""),
        history=d.get("history", []),
        trace=trace,
        dropped_citations=d.get("dropped_citations", []),
        notes=d.get("notes", []),
    )


def render_markdown(result: AgentResult, title: str | None = None, mock_banner: bool | None = None) -> str:
    if mock_banner is None:
        mock_banner = result.engine == "mock"
    lines: List[str] = []
    lines.append(f"# Trace:{title or result.question}")
    lines.append("")
    lines.append(f"- **问题**: {result.question}")
    engine_line = f"- **引擎**: {result.engine}(model: {result.model})"
    if mock_banner:
        engine_line += f"  \n  > {MOCK_BANNER}"
    lines.append(engine_line)
    lines.append(
        f"- **任务状态**: `{result.status}` | **步数**: {result.steps_used}/{result.max_steps}"
        + (" | **达到上限**" if result.limit_reached else "")
    )
    lines.append("")

    lines.append("## 最终交付")
    lines.append("")
    lines.append(f"- **回答**: {result.answer if result.answer else '(无 —— 未给出答案)'}")
    if result.citations:
        lines.append("- **引用(文档 ID / 版本 / 章节 / 逐字原文)**:")
        for i, c in enumerate(result.citations, 1):
            lines.append(f"  {_quote_line(c, i)}")
    else:
        lines.append("- **引用**: 无")
    if result.conflicts:
        lines.append("- **冲突**:")
        for conflict in result.conflicts:
            lines.append(f"  - 主题「{conflict.topic}」:")
            for o in conflict.options:
                lines.append(
                    f"    - [{o.doc_id} v{o.version_date} §{o.section or '-'}] 「{o.quote}」"
                    f" → {o.value or '(无数值)'}(证据来源: {o.evidence})"
                )
    if result.gaps:
        lines.append(f"- **资料缺口**: {';'.join(result.gaps)}")
    if result.next_question_to_user:
        lines.append(f"- **需向用户确认**: {result.next_question_to_user}")
    if result.dropped_citations:
        lines.append(f"- **被剔除的无效引用**: {json.dumps(result.dropped_citations, ensure_ascii=False)}")
    if result.notes:
        lines.append(f"- **备注**: {';'.join(result.notes)}")
    lines.append("")

    lines.append("## 决策过程(步骤 / 决策依据 / 工具参数 / 观察摘要)")
    lines.append("")
    for s in result.trace:
        lines.append(f"### Step {s.step} — {s.tool}")
        lines.append("")
        lines.append(f"- **决策依据**: {s.thought or '(无)'}")
        lines.append(f"- **工具参数**: `{json.dumps(s.params, ensure_ascii=False)}`")
        if s.next_action:
            lines.append(f"- **后续动作**: {s.next_action}")
        if s.observation is not None:
            obs = s.observation
            if obs.ok:
                lines.append(f"- **观察摘要**: {obs.summary}")
                if obs.data is not None:
                    data_text = json.dumps(obs.data, ensure_ascii=False, indent=2)
                    lines.append(f"- **观察数据**:\n\n```json\n{data_text}\n```")
            else:
                lines.append(f"- **观察摘要**: {obs.summary}")
                lines.append(f"- **错误**: {obs.error}")
        lines.append("")

    if result.history:
        lines.append("## 使用的对话历史")
        lines.append("")
        for h in result.history:
            cited = ",".join(h.get("cited_doc_ids", [])) or "无"
            lines.append(f"- 用户:{h.get('question', '')}")
            lines.append(f"  助手(status={h.get('status', '')},引用 {cited}):{h.get('answer', '')}")
        lines.append("")
    return "\n".join(lines)
