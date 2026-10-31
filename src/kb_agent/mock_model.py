"""离线 Mock 决策策略(确定性规则驱动的 ReAct)。

⚠️ 边界声明:Mock 不经过真实 LLM,仅用于无模型凭据时验证 ReAct 流程、
工具链路与交付格式;它不能证明真实模型的决策效果(docs/02-solution.md)。

策略概要(全部基于"观察结果"调整下一步动作,与真实模型走同一循环骨架):
1. 首轮检索问题主题词(含对话历史主题合并,处理"那……呢"式追问);
2. 检索无结果 → 用同义词扩展改写查询重试;仍无结果 → out_of_scope 并说明资料缺口;
3. 有命中 → 读取最相关文档原文,提取与问题相关的条款与数值;
4. 其他命中文档的片段显示不同数值(同单位)→ 读取该文档核实是否冲突;
5. 冲突成立 → needs_confirmation 列出双方原文并请用户确认,不擅自作答;
6. 工具失败 → 改读其他命中文档,以检索片段作为佐证;无法核实时如实说明。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .retrieval import expand_terms
from .schemas import HistoryTurn, TOOL_FINISH, TOOL_READ, TOOL_SEARCH, TraceStep
from .textutils import (
    bigram_counter,
    count_distinct_terms,
    extract_value,
    split_sentences,
)

FOLLOWUP_MARKERS = ("那", "呢", "还有", "它", "这个", "也")


def _unit(value: str) -> str:
    return value.split()[-1] if value else ""


def _is_followup(question: str) -> bool:
    return any(m in question for m in FOLLOWUP_MARKERS)


class MockReActModel:
    engine = "mock"
    name = "mock-policy-v1"

    def __init__(self, rules: dict | None = None):
        self.rules = rules or {}

    # ------------------------------------------------------------------ #
    # 主入口:根据 question + 已有步骤观察,给出下一个动作
    # ------------------------------------------------------------------ #
    def decide(
        self,
        question: str,
        history: List[HistoryTurn],
        steps: List[TraceStep],
        steps_left: int,
    ) -> Dict[str, Any]:
        topics = self._history_topics(history)
        raw, expanded = expand_terms(question, topics, self.rules)
        q_raw, _ = expand_terms(question, [], self.rules)
        hist_terms = [t for t in raw if t not in q_raw]  # 对话历史携带的主题词(打分权重低于新主题)
        multi_aspect = len(q_raw) >= 2  # 问题本身含多个主题词(如「出差住宿费标准」)→ 需覆盖多个方面

        searches = [s for s in steps if s.tool == TOOL_SEARCH]
        ok_searches = [s for s in searches if s.observation is not None and s.observation.ok]
        reads = [s for s in steps if s.tool == TOOL_READ]
        ok_reads = [s for s in reads if s.observation is not None and s.observation.ok]
        failed_reads = [s for s in reads if s.observation is not None and not s.observation.ok]
        followup = _is_followup(question) and bool(history)

        # -- 0. 用户在追问中指定了文档(如冲突场景确认「按 D01」)→ 直接读取,不再检索 --
        attempted = {str(s.params.get("doc_id", "")) for s in reads}
        doc_ref = self._explicit_doc_ref(question, history, attempted)
        if doc_ref:
            return self._read(
                doc_ref,
                f"用户在追问中指定了文档 {doc_ref},直接读取原文,结合对话历史主题定位条款",
            )
        # -- 0b. 无上下文却只引用了文档编号(如首问「按D01算」)→ 请求澄清,而非误报资料外 --
        if not history and not raw and re.search(r"(?i)(?<![A-Za-z0-9])d\d+(?![A-Za-z0-9])", question):
            return self._finish(
                status="clarification_needed",
                thought="问题只引用了文档编号而没有具体问题,请求澄清",
                answer=None,
                citations=[],
                gaps=["问题未说明想了解该文档中的什么内容"],
                next_q="请告诉我您想了解该文档中的什么问题(例如报销期限、住宿费标准等)。",
                topics=[],
            )

        last_hits: List[Dict[str, Any]] = []
        if ok_searches:
            last_hits = ok_searches[-1].observation.data.get("hits", [])  # type: ignore[union-attr]

            # -- 2. 检索无结果:改写重试,仍无则 out_of_scope --
            if not last_hits:
                tried = [str(s.params.get("query", "")) for s in ok_searches]
                if expanded != raw and " ".join(expanded) not in tried:
                    return self._search(" ".join(expanded), "检索无结果,使用同义词扩展改写查询后重试")
                return self._finish_out_of_scope(question, raw, tried)
        elif not ok_reads:
            # -- 1. 尚无成功检索:发起首轮(或对失败重试) --
            if searches:  # 有失败记录 → 换同义词扩展重试
                return self._search(
                    " ".join(expanded) or question,
                    "上次检索调用失败,附加同义词扩展后重试",
                )
            query = " ".join(raw) if raw else question
            thought = "先按问题主题词检索相关制度文档"
            if followup:
                thought = "问题含指代词(「那…呢」),已合并对话历史主题词检索"
            return self._search(query, thought)
        # ok_searches 为空但 ok_reads 非空:用户指定文档直读后,直接进入证据汇总

        # -- 3. 有命中:读取最相关文档 --
        primary = None
        for r in ok_reads:
            cand = self._extract_from_read(r, q_raw, hist_terms, question)
            if cand and (primary is None or cand["score"] > primary["score"]):
                primary = cand

        # 3a. 读取失败 → 改读其他命中文档(恢复路径)
        if failed_reads:
            nxt = next((h for h in last_hits if h["doc_id"] not in attempted), None)
            if nxt:
                return self._read(
                    nxt["doc_id"],
                    f"读取上一文档失败,改读命中文档 {nxt['doc_id']},并以检索片段作为另一证据来源",
                )

        # 3b. 从未读过 → 读最相关文档
        if not reads:
            top = last_hits[0]
            return self._read(
                top["doc_id"],
                f"检索命中 {len(last_hits)} 条,优先读取最相关文档 {top['doc_id']} 的原文核实",
            )

        # 3c. 冲突/补证核查:其他文档片段带数值且主题可比 → 读原文核实
        if primary:
            for h in last_hits:
                if h["doc_id"] == primary["doc_id"] or h["doc_id"] in attempted:
                    continue
                if not self._heading_comparable(h["heading"], raw):
                    continue
                snippet_value = extract_value(h["snippet"])
                if not snippet_value:
                    continue
                if multi_aspect:
                    need_verify = True  # 复合问题:逐一读取可比命中文档,覆盖各个方面
                    reason = f"复合问题需覆盖「{h['heading']}」方面,读取原文核实"
                elif primary["value"]:
                    need_verify = (
                        _unit(snippet_value) == _unit(primary["value"])
                        and snippet_value != primary["value"]
                    )
                    reason = (
                        f"片段显示 {h['doc_id']} 为「{snippet_value}」,与 {primary['doc_id']} 的"
                        f"「{primary['value']}」不一致,读取原文核实是否冲突"
                    )
                else:
                    need_verify = True  # 已读文档没有数值,改读带数值的命中文档
                    reason = f"已读文档未见对应数值,改读 {h['doc_id']} 核实"
                if need_verify:
                    return self._read(h["doc_id"], reason)

        # -- 4. 汇总所有证据做结束决策 --
        return self._summarize(question, raw, q_raw, last_hits, ok_reads, failed_reads, primary, attempted)

    # ------------------------------------------------------------------ #
    # 证据汇总与结束动作
    # ------------------------------------------------------------------ #
    def _summarize(
        self,
        question: str,
        raw: List[str],
        q_raw: List[str],
        last_hits: List[Dict[str, Any]],
        ok_reads: List[TraceStep],
        failed_reads: List[TraceStep],
        primary: Optional[Dict[str, Any]],
        attempted: set,
    ) -> Dict[str, Any]:
        options: Dict[str, Dict[str, Any]] = {}   # doc_id -> 证据 option
        sentence_only: Dict[str, Dict[str, Any]] = {}
        hist_terms = [t for t in raw if t not in q_raw]

        for r in ok_reads:
            cand = self._extract_from_read(r, q_raw, hist_terms, question)
            if not cand:
                continue
            entry = self._option_from_extract(cand, evidence="read")
            if cand["value"]:
                options[cand["doc_id"]] = entry
            else:
                sentence_only[cand["doc_id"]] = entry

        # 读取失败/未读取的命中文档:用检索片段作为佐证(逐字、可校验)
        for h in last_hits:
            doc_id = h["doc_id"]
            if doc_id in options or doc_id in sentence_only:
                continue
            read_failed = doc_id in attempted and doc_id not in {r.params.get("doc_id") for r in ok_reads}
            comparable = self._heading_comparable(h["heading"], raw)
            if not (read_failed or comparable):
                continue
            snippet_value = extract_value(h["snippet"])
            entry = {
                "doc_id": doc_id,
                "title": h["title"],
                "version_date": h["version_date"],
                "section": h["heading"],
                "quote": h["snippet"],
                "value": snippet_value or "",
                "evidence": "snippet",
                "score": self._score_sentence(h["heading"], h["snippet"], q_raw, hist_terms, question),
            }
            if snippet_value:
                options[doc_id] = entry
            else:
                sentence_only[doc_id] = entry

        # -- 冲突判定:同一单位下出现不同数值才算真冲突(不同单位=不同方面,不是冲突) --
        conflict_group = self._find_conflict_group(options)
        if conflict_group:
            # 冲突主题标签优先用本轮问题自身的主题词,避免混入历史携带话题
            topic = "、".join(q_raw[:3]) if q_raw else ("、".join(raw[:3]) if raw else question)
            ordered = sorted(conflict_group, key=lambda o: o["doc_id"])
            conflict = {"topic": topic, "options": ordered}
            brief = ";".join(
                f"{o['doc_id']}《{o['title']}》(v{o['version_date']})为「{o['value']}」" for o in ordered
            )
            answer = (
                f"不同文档对「{topic}」的规定不一致:{brief}。"
                "在你确认适用制度前,我无法给出单一结论。"
            )
            return self._finish(
                status="needs_confirmation",
                thought=f"多个文档给出不同数值({', '.join(sorted({o['value'] for o in ordered}))}),列出冲突并请用户确认",
                answer=answer,
                citations=[{"doc_id": o["doc_id"], "section": o["section"], "quote": o["quote"]} for o in ordered],
                conflicts=[conflict],
                gaps=["文档未注明各自适用范围与优先级,无法自动判定应适用哪一份"],
                next_q=f"以上文档均未注明适用范围与优先级,请确认您适用的制度(如 {ordered[0]['doc_id']} 或 {ordered[-1]['doc_id']}),我再给出确定答案。",
                topics=raw,
            )

        # -- 追问引入了新主题,但命中文档条款与新主题(含同义词)毫无交集 → 如实澄清,不答非所问 --
        q_expanded = list(q_raw)
        for t in q_raw:
            for s in self.rules.get("synonyms", {}).get(t, []):
                if s not in q_expanded:
                    q_expanded.append(s)
        if primary and q_expanded and (
            count_distinct_terms(primary["heading"], q_expanded) == 0
            and count_distinct_terms(primary["quote"], q_expanded) == 0
        ):
            topic = "、".join(q_raw)
            return self._finish(
                status="clarification_needed",
                thought="指定文档中未见与新主题相关的条款,如实澄清而非引用无关条款作答",
                answer=None,
                citations=[],
                gaps=[f"文档 {primary['doc_id']} 中未找到与「{topic}」相关的条款"],
                next_q=f"「{topic}」可能记录在其他文档中,请指定文档编号(如已知),或换个说法再问。",
                topics=raw,
            )

        # -- 单一数值证据:取与问题最相关的条款回答 --
        if options:
            best = max(options.values(), key=lambda o: (o.get("score", 0), o["doc_id"]))
            gaps = []
            if best["evidence"] == "snippet":
                gaps.append("文档原文读取失败,以上回答基于检索返回的片段证据")
            return self._finish(
                status="answered",
                thought="已从文档中找到对应数值条款,引用原文作答",
                answer=f"{best['quote']} 结论:{best['value']}。",
                citations=[{"doc_id": best["doc_id"], "section": best["section"], "quote": best["quote"]}],
                conflicts=[],
                gaps=gaps,
                topics=raw,
            )

        # -- 依据已读文档的相关条款回答(无数值) --
        if primary:
            return self._finish(
                status="answered",
                thought="已从文档原文找到对应条款,引用原文作答",
                answer=primary["quote"],
                citations=[{"doc_id": primary["doc_id"], "section": primary["heading"], "quote": primary["quote"]}],
                conflicts=[],
                gaps=[],
                topics=raw,
            )

        # -- 读到文档但没有对应条款 --
        if ok_reads and sentence_only:
            entry = next(iter(sentence_only.values()))
            return self._finish(
                status="answered",
                thought="文档中存在相关条款但无量化数值,引用原文说明",
                answer=entry["quote"],
                citations=[{"doc_id": entry["doc_id"], "section": entry["section"], "quote": entry["quote"]}],
                gaps=[],
                topics=raw,
            )

        return self._finish(
            status="clarification_needed",
            thought="命中文档中未找到与问题直接对应的条款,请用户澄清",
            answer=None,
            gaps=["命中的文档未包含与问题直接对应的条款"],
            next_q="能否换一种说法,或补充说明您想了解的具体事项?",
            topics=raw,
        )

    # ------------------------------------------------------------------ #
    # 动作构造
    # ------------------------------------------------------------------ #
    def _search(self, query: str, thought: str) -> Dict[str, Any]:
        # top_k 不在此指定:交由工具层的默认值(来自 --top-k 配置),保证参数全链路生效
        return {"thought": thought, "tool": TOOL_SEARCH, "params": {"query": query}}

    def _read(self, doc_id: str, thought: str) -> Dict[str, Any]:
        return {"thought": thought, "tool": TOOL_READ, "params": {"doc_id": doc_id}}

    def _finish(
        self,
        status: str,
        thought: str,
        answer: Optional[str] = None,
        citations: Optional[List[Dict[str, str]]] = None,
        conflicts: Optional[List[Dict[str, Any]]] = None,
        gaps: Optional[List[str]] = None,
        next_q: Optional[str] = None,
        topics: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "status": status,
            "answer": answer,
            "citations": citations or [],
            "conflicts": conflicts or [],
            "gaps": gaps or [],
            "next_question_to_user": next_q,
            "topics": topics or [],
        }
        return {"thought": thought, "tool": TOOL_FINISH, "params": params}

    def _finish_out_of_scope(self, question: str, raw: List[str], tried: List[str]) -> Dict[str, Any]:
        tried_text = "、".join(f"「{q}」" for q in tried if q) or "(无)"
        return self._finish(
            status="out_of_scope",
            thought="改写检索后仍无命中,如实告知超出资料范围",
            answer=None,
            citations=[],
            gaps=[
                f"当前文档库未收录与问题「{question}」相关的制度或 FAQ",
                f"已尝试的查询:{tried_text}",
            ],
            topics=raw,
        )

    # ------------------------------------------------------------------ #
    # 证据提取
    # ------------------------------------------------------------------ #
    def _extract_from_read(
        self, step: TraceStep, q_terms: List[str], hist_terms: List[str], question: str
    ) -> Optional[Dict[str, Any]]:
        """从 read 观察中提取与问题最相关的句子(及其数值)。

        打分时问题自身的主题词权重高于对话历史携带的主题词,保证追问引入新主题时
        答案跟随新主题而不是沿用上一轮。
        """
        obs = step.observation
        if obs is None or not obs.ok or not obs.data:
            return None
        doc_meta = obs.data.get("doc", {})
        sections = obs.data.get("sections", [])
        best: Optional[Dict[str, Any]] = None
        for sec in sections:
            heading = str(sec.get("heading", ""))
            for sent in split_sentences(str(sec.get("text", ""))):
                score = self._score_sentence(heading, sent, q_terms, hist_terms, question)
                if best is None or score > best["score"]:
                    best = {
                        "doc_id": str(doc_meta.get("doc_id", "")),
                        "title": str(doc_meta.get("title", "")),
                        "version_date": str(doc_meta.get("version_date", "")),
                        "heading": heading,
                        "quote": sent,
                        "value": extract_value(sent),
                        "score": score,
                    }
        return best

    def _option_from_extract(self, cand: Dict[str, Any], evidence: str) -> Dict[str, Any]:
        return {
            "doc_id": cand["doc_id"],
            "title": cand["title"],
            "version_date": cand["version_date"],
            "section": cand["heading"],
            "quote": cand["quote"],
            "value": cand["value"] or "",
            "evidence": evidence,
            "score": cand["score"],
        }

    def _score_sentence(self, heading: str, sentence: str, q_terms: List[str], hist_terms: List[str], question: str) -> float:
        """句子相关度:新主题词(问题自身)权重 3 倍,历史携带主题词权重 1 倍;
        章节标题命中再乘 2;与问题原文的 bigram 重叠做微调。"""
        q_feats = set(bigram_counter(question))
        return (
            3 * count_distinct_terms(heading, q_terms)
            + count_distinct_terms(heading, hist_terms)
            + 3 * count_distinct_terms(sentence, q_terms)
            + count_distinct_terms(sentence, hist_terms)
            + 0.01 * len(q_feats & set(bigram_counter(sentence)))
        )

    def _find_conflict_group(self, options: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """同一单位下出现 ≥2 个不同数值 → 返回该组选项;否则返回空。

        不同单位(如 天 vs 元)代表问题的不同方面,不构成冲突。
        """
        by_unit: Dict[str, List[Dict[str, Any]]] = {}
        for o in options.values():
            if not o["value"]:
                continue
            by_unit.setdefault(_unit(o["value"]), []).append(o)
        for group in by_unit.values():
            values = {o["value"] for o in group}
            if len(values) >= 2:
                return group
        return []

    def _heading_comparable(self, heading: str, raw_terms: List[str]) -> bool:
        """章节标题与问题主题词有交集才参与冲突比较,避免把不同福利误判为冲突。"""
        return count_distinct_terms(heading, raw_terms) > 0

    def _explicit_doc_ref(self, question: str, history: List[HistoryTurn], attempted: set) -> Optional[str]:
        """识别追问中指定的文档编号(如「按 D01」「按D01算」);须出现在历史引用中(可校验、防幻觉),
        且本轮尚未读过(已读过则进入证据汇总,避免重复读取)。

        注意:中文与字母同属 \\w,\\b 词边界在中文语境失效,须用显式 lookaround 断言。"""
        if not history:
            return None
        known = {d for t in history for d in t.cited_doc_ids}
        for match in re.findall(r"(?i)(?<![A-Za-z0-9])d\d+(?![A-Za-z0-9])", question):
            ref = match.upper()
            if ref in known and ref not in attempted:
                return ref
        return None

    def _history_topics(self, history: List[HistoryTurn]) -> List[str]:
        topics: List[str] = []
        for turn in history:
            if turn.topics:
                merged = turn.topics
            else:
                merged = expand_terms(turn.question, [], self.rules)[0]
            for t in merged:
                if t not in topics:
                    topics.append(t)
        return topics
