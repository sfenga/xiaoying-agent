"""检索:字符 bigram TF-IDF 余弦相似度(纯 Python、确定性、中文友好)。

设计要点(取舍详见 docs/02-solution.md):
- 不依赖分词库与向量库:中文制度文本用字符 bigram 即可获得稳定召回;
- 查询扩展:domain_terms 提取主题词 + aliases 口语映射 + synonyms 同义词改写,
  属于"合成规则",换掉文档内容后规则依然成立;
- 命中门槛:片段必须包含至少一个扩展词,或相似度达到阈值,过滤弱相关结果。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from .store import Doc, DocStore, Section
from .textutils import bigram_counter, contains_any, count_distinct_terms, split_sentences, tokenize

SCORE_SCALE = 100.0
WEAK_SCORE_THRESHOLD = 10.0  # 不含任何扩展词时,余弦相似度须 >= 0.10 才算命中


@dataclass
class Hit:
    doc_id: str
    title: str
    version_date: str
    applies_to: str
    heading: str
    score: float
    snippet: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "version_date": self.version_date,
            "applies_to": self.applies_to,
            "heading": self.heading,
            "score": round(self.score, 3),
            "snippet": self.snippet,
        }


@dataclass
class _Chunk:
    doc: Doc
    section: Section
    counter: Dict[str, float]  # 加权(标题/章节名加倍)后的词频
    norm: float


def expand_terms(question: str, history_topics: Sequence[str], rules: dict) -> Tuple[List[str], List[str]]:
    """返回 (原始主题词, 扩展词表)。

    原始主题词 = 问题中出现的 domain_terms + 命中的 aliases 规范词 + 历史主题词;
    扩展词表   = 原始主题词 + 其 synonyms(供无结果时改写与召回加权)。
    """
    domain_terms: List[str] = rules.get("domain_terms", [])
    aliases: Dict[str, str] = rules.get("aliases", {})
    synonyms: Dict[str, List[str]] = rules.get("synonyms", {})

    raw: List[str] = []
    for t in domain_terms:
        if t in question and t not in raw:
            raw.append(t)
    for spoken, canonical in aliases.items():
        if spoken in question and canonical not in raw:
            raw.append(canonical)
    for t in history_topics:
        if t and t not in raw:
            raw.append(t)

    expanded: List[str] = list(raw)
    for t in raw:
        for s in synonyms.get(t, []):
            if s not in expanded:
                expanded.append(s)
    return raw, expanded


class RetrievalIndex:
    def __init__(self, store: DocStore, rules: dict | None = None):
        self.store = store
        self.rules = rules or {}
        self._chunks: List[_Chunk] = []
        self._df: Dict[str, int] = {}
        self._build()

    # ---- 索引构建 ----
    def _build(self) -> None:
        counters: List[Dict[str, float]] = []
        for doc in self.store.all():
            for section in doc.sections:
                text = f"{doc.title} {doc.title} {section.heading} {section.heading} {section.text}"
                counter: Dict[str, float] = {}
                for feat, tf in bigram_counter(text).items():
                    counter[feat] = counter.get(feat, 0.0) + float(tf)
                counters.append(counter)
                self._chunks.append(_Chunk(doc=doc, section=section, counter=counter, norm=0.0))
        # 文档频率
        for counter in counters:
            for feat in counter:
                self._df[feat] = self._df.get(feat, 0) + 1
        # IDF 加权并归一化
        n = len(counters)
        for chunk in self._chunks:
            weighted: Dict[str, float] = {}
            for feat, tf in chunk.counter.items():
                idf = math.log((n + 1) / (self._df[feat] + 1)) + 1.0
                weighted[feat] = tf * idf
            chunk.counter = weighted
            chunk.norm = math.sqrt(sum(v * v for v in weighted.values())) or 1.0

    # ---- 查询 ----
    def search(self, terms: List[str], top_k: int = 4, question: str = "") -> List[Hit]:
        """按扩展词表检索;terms 为空时退化为问题原文的 bigram 检索。"""
        if not terms and question:
            terms = [question]
        # 查询向量:所有扩展词等权(命中质量主要由下方"包含扩展词才命中"的门槛保证)
        q_counter: Dict[str, float] = {}
        for term in terms:
            for feat in tokenize(term):
                q_counter[feat] = q_counter.get(feat, 0.0) + 1.0
        if not q_counter:
            return []
        q_norm = math.sqrt(sum(v * v for v in q_counter.values())) or 1.0

        scored: List[Tuple[float, int]] = []
        for i, chunk in enumerate(self._chunks):
            overlap = sum(
                qv * chunk.counter[feat]
                for feat, qv in q_counter.items()
                if feat in chunk.counter
            )
            score = overlap / (q_norm * chunk.norm) * SCORE_SCALE
            contains_term = contains_any(
                f"{chunk.doc.title} {chunk.section.heading} {chunk.section.text}", terms
            )
            if contains_term or score >= WEAK_SCORE_THRESHOLD:
                scored.append((score, i))

        scored.sort(key=lambda x: (-x[0], self._chunks[x[1]].doc.doc_id, x[1]))
        hits: List[Hit] = []
        for score, i in scored[: max(1, top_k)]:
            chunk = self._chunks[i]
            hits.append(
                Hit(
                    doc_id=chunk.doc.doc_id,
                    title=chunk.doc.title,
                    version_date=chunk.doc.version_date,
                    applies_to=chunk.doc.applies_to,
                    heading=chunk.section.heading,
                    score=round(score, 3),
                    snippet=self._best_snippet(chunk, terms),
                )
            )
        return hits

    def _best_snippet(self, chunk: _Chunk, terms: List[str]) -> str:
        """从章节正文中挑选与查询词最相关的句子,逐字返回(保证引用可校验)。"""
        sentences = split_sentences(chunk.section.text)
        if not sentences:
            return chunk.section.text
        best, best_score = sentences[0], -1
        for sent in sentences:
            raw_hits = sum(1 for t in terms if t in sent)
            score = raw_hits * 2 + (1 if raw_hits else 0)
            if score > best_score:
                best, best_score = sent, score
        return best
