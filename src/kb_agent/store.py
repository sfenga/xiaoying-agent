"""文档库:加载合成制度/FAQ 文档,供检索与读取工具使用。

文档结构(见 data/documents.json):
  doc_id / title / version_date / applies_to(可为 null,表示未注明适用范围) / tags / sections[{heading, text}]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class Section:
    heading: str
    text: str


@dataclass
class Doc:
    doc_id: str
    title: str
    version_date: str
    applies_to: str = ""   # 空串表示文档未注明适用范围
    tags: List[str] = field(default_factory=list)
    sections: List[Section] = field(default_factory=list)

    def full_text(self) -> str:
        """标题 + 全部章节标题与正文,用于引用逐字校验。"""
        parts = [self.title]
        for sec in self.sections:
            parts.append(sec.heading)
            parts.append(sec.text)
        return "\n".join(parts)


class DocStore:
    def __init__(self, docs: List[Doc]):
        self._docs: List[Doc] = docs
        self._by_id = {d.doc_id: d for d in docs}
        if len(self._by_id) != len(docs):
            raise ValueError("documents.json 中存在重复 doc_id")

    @classmethod
    def load(cls, path: str | Path) -> "DocStore":
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"文档库不存在: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        docs: List[Doc] = []
        for i, raw in enumerate(payload.get("documents", [])):
            missing = {"doc_id", "title", "version_date", "sections"} - set(raw)
            if missing:
                raise ValueError(f"documents.json 第 {i} 篇缺少字段: {sorted(missing)}")
            docs.append(
                Doc(
                    doc_id=str(raw["doc_id"]),
                    title=str(raw["title"]),
                    version_date=str(raw["version_date"]),
                    applies_to=str(raw.get("applies_to") or ""),
                    tags=list(raw.get("tags") or []),
                    sections=[Section(heading=str(s["heading"]), text=str(s["text"])) for s in raw["sections"]],
                )
            )
        if not docs:
            raise ValueError("documents.json 未包含任何文档")
        return cls(docs)

    def get(self, doc_id: str) -> Doc:
        """不存在时抛 KeyError,由工具层转为错误观察。"""
        return self._by_id[doc_id]

    def all(self) -> List[Doc]:
        return list(self._docs)

    def __len__(self) -> int:
        return len(self._docs)
