"""数据结构:动作、观察、Trace 步骤、最终答案与任务状态。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# ---- 任务状态(最终交付中的"任务状态"字段) ----
STATUS_ANSWERED = "answered"                    # 依据文档给出明确答案
STATUS_NEEDS_CONFIRMATION = "needs_confirmation"  # 文档冲突/需用户确认适用范围
STATUS_OUT_OF_SCOPE = "out_of_scope"            # 问题超出资料范围
STATUS_CLARIFICATION = "clarification_needed"   # 问题本身不清晰,需要澄清
STATUS_UNFINISHED = "unfinished"                # 达到步数上限/模型故障等未完成

ALL_STATUSES = [
    STATUS_ANSWERED,
    STATUS_NEEDS_CONFIRMATION,
    STATUS_OUT_OF_SCOPE,
    STATUS_CLARIFICATION,
    STATUS_UNFINISHED,
]

# ReAct 循环中模型可选的动作
TOOL_SEARCH = "search"
TOOL_READ = "read"
TOOL_FINISH = "finish"
VALID_TOOLS = {TOOL_SEARCH, TOOL_READ, TOOL_FINISH}


@dataclass
class Citation:
    """引用:文档 ID + 版本 + 章节 + 逐字原文片段。"""

    doc_id: str
    title: str
    version_date: str
    section: str
    quote: str


@dataclass
class ConflictOption:
    """冲突中的一个候选规定。evidence 说明证据来源:read=读取原文 / snippet=检索片段。"""

    doc_id: str
    title: str
    version_date: str
    section: str
    quote: str
    value: str
    evidence: str = "read"


@dataclass
class Conflict:
    """同一问题在不同文档中的不一致规定。"""

    topic: str
    options: List[ConflictOption] = field(default_factory=list)


@dataclass
class Observation:
    """工具执行结果(成功或失败),作为下一轮模型决策的输入。"""

    tool: str
    params: Dict[str, Any]
    ok: bool
    summary: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class TraceStep:
    """Trace 的一步:决策依据(简要) + 动作 + 观察结果 + 该观察引发的后续动作。"""

    step: int
    thought: str
    tool: str
    params: Dict[str, Any]
    observation: Optional[Observation] = None
    next_action: Optional[str] = None  # 形如 "read {\"doc_id\": \"D01\"}";结束步骤为 "(结束)"


@dataclass
class HistoryTurn:
    """对话历史一轮,用于上下文追问。"""

    question: str
    answer: str
    status: str = STATUS_ANSWERED
    cited_doc_ids: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentResult:
    """一次问答的完整交付:回答、引用、冲突、资料缺口、任务状态、Trace。"""

    question: str
    status: str
    answer: Optional[str] = None
    citations: List[Citation] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    next_question_to_user: Optional[str] = None
    topics: List[str] = field(default_factory=list)
    steps_used: int = 0
    max_steps: int = 0
    limit_reached: bool = False
    engine: str = "mock"
    model: str = "mock-policy"
    history: List[Dict[str, Any]] = field(default_factory=list)
    trace: List[TraceStep] = field(default_factory=list)
    dropped_citations: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d
