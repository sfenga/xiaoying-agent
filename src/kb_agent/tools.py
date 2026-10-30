"""工具层:文档检索(search)与片段读取(read),支持故障注入。

工具只做确定性的信息存取,不做决策;决策由模型(真实 LLM 或 Mock 策略)完成。
所有异常都被 ToolBox 捕获并转为失败观察(Observation.ok=False),
保证 ReAct 循环中"工具失败"也能作为观察反馈给模型。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .retrieval import RetrievalIndex, expand_terms
from .schemas import Observation
from .store import DocStore


class ToolError(Exception):
    """工具执行失败(含故障注入产生的模拟故障)。"""


class SearchDocumentsTool:
    """文档检索工具:返回相关章节片段(逐字),供引用与冲突核查。"""

    name = "search"

    def __init__(self, index: RetrievalIndex, rules: dict | None = None, default_top_k: int = 4):
        self.index = index
        self.rules = rules or {}
        self.default_top_k = default_top_k

    def run(self, query: str, top_k: Optional[int] = None) -> Observation:
        params = {"query": query, "top_k": top_k or self.default_top_k}
        if not isinstance(query, str) or not query.strip():
            return Observation(self.name, params, ok=False, summary="检索失败", error="query 不能为空")
        query = query.strip()
        terms = self._terms_for(query)
        hits = self.index.search(terms, top_k=params["top_k"], question=query)
        data = {
            "query": query,
            "terms": terms,
            "hits": [h.to_dict() for h in hits],
        }
        doc_ids = sorted({h.doc_id for h in hits})
        summary = (
            f"检索「{query}」命中 {len(hits)} 条片段"
            + (f"(涉及文档: {', '.join(doc_ids)})" if doc_ids else "(无相关文档)")
        )
        return Observation(self.name, params, ok=True, summary=summary, data=data)

    def _terms_for(self, query: str) -> List[str]:
        """带空格的查询按词处理(Mock 传词表);自然语言整句则用规则做查询扩展。"""
        parts = [p for p in query.split() if p]
        if len(parts) > 1 or not query.strip():
            return parts
        if len(query) >= 6:
            raw, expanded = expand_terms(query, [], self.rules)
            if raw:
                return expanded
        return [query]


class ReadDocumentTool:
    """文档读取工具:按 doc_id 读取整篇(可按章节标题过滤)。"""

    name = "read"

    def __init__(self, store: DocStore):
        self.store = store

    def run(self, doc_id: str, section: Optional[str] = None) -> Observation:
        params: Dict[str, Any] = {"doc_id": doc_id, "section": section}
        if not isinstance(doc_id, str) or not doc_id.strip():
            return Observation(self.name, params, ok=False, summary="读取失败", error="doc_id 不能为空")
        doc_id = doc_id.strip()
        try:
            doc = self.store.get(doc_id)
        except KeyError:
            available = ", ".join(d.doc_id for d in self.store.all())
            return Observation(
                self.name,
                params,
                ok=False,
                summary=f"读取失败:不存在文档 {doc_id}",
                error=f"未找到文档 {doc_id},可用文档: {available}",
            )
        sections = doc.sections
        if section:
            matched = [s for s in doc.sections if s.heading == section or section in s.heading]
            if not matched:
                headings = "、".join(s.heading for s in doc.sections)
                return Observation(
                    self.name,
                    params,
                    ok=False,
                    summary=f"读取失败:{doc_id} 中没有章节「{section}」",
                    error=f"文档 {doc_id} 不含章节「{section}」,可用章节: {headings}",
                )
            sections = matched
        data = {
            "doc": {
                "doc_id": doc.doc_id,
                "title": doc.title,
                "version_date": doc.version_date,
                "applies_to": doc.applies_to or None,
            },
            "requested_section": section,
            "sections": [{"heading": s.heading, "text": s.text} for s in sections],
        }
        summary = f"读取 {doc.doc_id}《{doc.title}》(v{doc.version_date}) 共 {len(sections)} 节: " + "、".join(
            s.heading for s in sections
        )
        return Observation(self.name, params, ok=True, summary=summary, data=data)


class FailureInjector:
    """故障注入:模拟工具失败,用于演示与测试"工具失败"场景(非默认开启)。

    - read_once: 第一次 read 调用抛 ToolError,之后正常
    - search_once: 第一次 search 调用抛 ToolError,之后正常
    - read_all: 所有 read 调用都抛 ToolError
    """

    def __init__(self, mode: str):
        self.mode = mode or ""
        self._calls: Dict[str, int] = {"search": 0, "read": 0}

    def check(self, tool_name: str) -> None:
        if not self.mode:
            return
        if tool_name not in self._calls:
            return
        self._calls[tool_name] += 1
        count = self._calls[tool_name]
        should_fail = (
            (self.mode == "read_once" and tool_name == "read" and count == 1)
            or (self.mode == "search_once" and tool_name == "search" and count == 1)
            or (self.mode == "read_all" and tool_name == "read")
        )
        if should_fail:
            raise ToolError(
                f"模拟工具故障(注入模式 {self.mode}): {tool_name} 服务暂时不可用,请稍后或换用其他方式"
            )


class ToolBox:
    """工具集合与统一执行入口:任何异常都转为失败观察,绝不抛出到循环外。"""

    def __init__(self, search_tool: SearchDocumentsTool, read_tool: ReadDocumentTool, inject_failure: str = ""):
        self._tools = {search_tool.name: search_tool, read_tool.name: read_tool}
        self.injector = FailureInjector(inject_failure)

    def execute(self, name: str, params: Dict[str, Any]) -> Observation:
        params = params or {}
        tool = self._tools.get(name)
        if tool is None:
            return Observation(name, params, ok=False, summary=f"未知工具 {name}", error=f"未知工具 {name!r}")
        try:
            self.injector.check(name)
        except ToolError as exc:
            return Observation(name, params, ok=False, summary=f"工具 {name} 执行失败", error=str(exc))
        try:
            if name == "search":
                return tool.run(query=params.get("query"), top_k=params.get("top_k"))
            return tool.run(doc_id=params.get("doc_id"), section=params.get("section"))
        except ToolError as exc:
            return Observation(name, params, ok=False, summary=f"工具 {name} 执行失败", error=str(exc))
        except Exception as exc:  # 工具缺陷也不应中断循环
            return Observation(name, params, ok=False, summary=f"工具 {name} 内部异常", error=repr(exc))
