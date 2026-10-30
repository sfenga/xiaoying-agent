"""共享 fixture:构建 Mock 引擎 agent(测试全部离线、确定性,不依赖真实模型)。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.kb_agent.cli import build_agent
from src.kb_agent.config import Config
from src.kb_agent.schemas import AgentResult, HistoryTurn

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "data" / "documents.json"
RULES_PATH = PROJECT_ROOT / "data" / "rules.json"


def make_config(data_path=None, rules_path=None, inject="", max_steps=8, top_k=4) -> Config:
    return Config(
        engine="mock",
        engine_request="mock",
        data_path=data_path or DATA_PATH,
        rules_path=rules_path or RULES_PATH,
        inject_failure=inject,
        max_steps=max_steps,
        top_k=top_k,
    )


@pytest.fixture()
def agent_factory():
    def _make(data_path=None, rules_path=None, inject="", max_steps=8, top_k=4):
        agent, _store = build_agent(
            make_config(data_path, rules_path, inject, max_steps, top_k)
        )
        return agent

    return _make


@pytest.fixture()
def agent(agent_factory):
    return agent_factory()


def make_history(result: AgentResult) -> list:
    return [
        HistoryTurn(
            question=result.question,
            answer=result.answer or "",
            status=result.status,
            cited_doc_ids=[c.doc_id for c in result.citations],
            topics=result.topics,
        )
    ]


def write_docs_variant(tmp_path: Path, mutations) -> Path:
    """复制 documents.json 并按 mutations(doc_id -> [(heading, old, new)]) 替换原文。"""
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    for doc in payload["documents"]:
        for heading, old, new in mutations.get(doc["doc_id"], []):
            for sec in doc["sections"]:
                if sec["heading"] == heading:
                    assert old in sec["text"], f"替换目标不存在: {doc['doc_id']} {heading} {old!r}"
                    sec["text"] = sec["text"].replace(old, new)
    out = tmp_path / "documents_variant.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
