"""真实模型路径端到端集成测试:本地桩 OpenAI 兼容服务器,验证 HTTP→解析→循环→引用校验全链路。

无需真实模型凭据即可证明 LLMReActModel 的协议路径可用:
请求格式(system/user 消息、鉴权头)、动作 JSON 解析、错误反馈与自我修正、引用核验。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.kb_agent.agent import ReActAgent
from src.kb_agent.llm import OpenAICompatLLM
from src.kb_agent.real_model import LLMReActModel
from src.kb_agent.retrieval import RetrievalIndex
from src.kb_agent.store import DocStore
from src.kb_agent.tools import ReadDocumentTool, SearchDocumentsTool, ToolBox

from .conftest import DATA_PATH, RULES_PATH


def _make_server(responses):
    """启动桩 chat/completions 服务:按序返回预设动作;记录请求体与鉴权头。"""
    log = {"requests": [], "auth": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            log["requests"].append(json.loads(self.rfile.read(length)))
            log["auth"].append(self.headers.get("Authorization", ""))
            action = responses.pop(0) if responses else {
                "thought": "no scripted response left",
                "tool": "finish",
                "params": {"status": "unfinished", "gaps": ["桩响应耗尽"]},
            }
            payload = json.dumps(
                {"choices": [{"message": {"content": json.dumps(action, ensure_ascii=False)}}]}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, log


def _make_agent(base_url: str) -> ReActAgent:
    store = DocStore.load(DATA_PATH)
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    index = RetrievalIndex(store, rules)
    toolbox = ToolBox(SearchDocumentsTool(index, rules=rules), ReadDocumentTool(store))
    llm = OpenAICompatLLM(base_url, "test-key", "fake-model", timeout=5, max_retries=0)
    return ReActAgent(LLMReActModel(llm), toolbox, store, max_steps=6, engine="real", model_name="fake-model")


@pytest.fixture()
def server_factory():
    made = []

    def _make(responses):
        server, log = _make_server(responses)
        made.append(server)
        return server, log

    yield _make
    for s in made:
        s.shutdown()
        s.server_close()


def test_real_model_happy_path(server_factory):
    """search → read → finish(answered):全链路走通,引用通过逐字校验。"""
    responses = [
        {"thought": "先检索补贴相关条款", "tool": "search", "params": {"query": "餐补 补贴"}},
        {"thought": "读取最相关文档", "tool": "read", "params": {"doc_id": "D04"}},
        {
            "thought": "依据原文作答",
            "tool": "finish",
            "params": {
                "status": "answered",
                "answer": "工作日午餐补贴为每月 300 元,随当月工资发放。",
                "citations": [
                    {"doc_id": "D04", "section": "餐补", "quote": "工作日午餐补贴为每月 300 元,随当月工资发放;"}
                ],
                "conflicts": [],
                "gaps": [],
                "next_question_to_user": None,
                "topics": ["餐补", "补贴"],
            },
        },
    ]
    server, log = server_factory(responses)
    agent = _make_agent(f"http://127.0.0.1:{server.server_address[1]}")
    result = agent.run("每个月吃饭有补贴吗?能补多少?")

    assert result.status == "answered"
    assert result.engine == "real"
    assert [c.doc_id for c in result.citations] == ["D04"]
    assert [s.tool for s in result.trace] == ["search", "read", "finish"]
    assert len(log["requests"]) == 3
    assert all(a == "Bearer test-key" for a in log["auth"])
    first = log["requests"][0]
    assert first["model"] == "fake-model"
    assert first["messages"][0]["role"] == "system"
    assert "search" in first["messages"][0]["content"]  # 系统提示词含动作协议
    assert "每个月吃饭有补贴吗" in first["messages"][-1]["content"]


def test_real_model_self_correction_on_invalid_finish(server_factory):
    """非法 finish → 循环把校验错误作为观察反馈 → 模型修正后正常结束。"""
    responses = [
        {"thought": "试试偷懒", "tool": "finish", "params": {"status": "totally-wrong"}},
        {"thought": "收到格式错误反馈,先检索", "tool": "search", "params": {"query": "餐补 补贴"}},
        {"thought": "读取原文", "tool": "read", "params": {"doc_id": "D04"}},
        {
            "thought": "修正为合法交付",
            "tool": "finish",
            "params": {
                "status": "answered",
                "answer": "餐补为每月 300 元。",
                "citations": [
                    {"doc_id": "D04", "section": "餐补", "quote": "工作日午餐补贴为每月 300 元,随当月工资发放;"}
                ],
            },
        },
    ]
    server, log = server_factory(responses)
    agent = _make_agent(f"http://127.0.0.1:{server.server_address[1]}")
    result = agent.run("每个月吃饭有补贴吗?")

    assert result.status == "answered"
    assert [s.tool for s in result.trace] == ["finish", "search", "read", "finish"]
    assert result.trace[0].observation.ok is False
    assert "status 非法" in result.trace[0].observation.error
    assert result.trace[0].next_action.startswith("search")  # 错误反馈触发了修正动作
    assert len(log["requests"]) == 4


def test_real_model_drops_fabricated_citation(server_factory):
    """真实模型给出编造引用时被循环剔除并记录;无引用的 answered 被拒绝并反馈修正。"""
    responses = [
        {"thought": "t", "tool": "search", "params": {"query": "餐补 补贴"}},
        {
            "thought": "t",
            "tool": "finish",
            "params": {
                "status": "answered",
                "answer": "编造引用的回答",
                "citations": [{"doc_id": "D04", "section": "餐补", "quote": "这句原文里不存在"}],
            },
        },
    ]
    server, log = server_factory(responses)
    agent = _make_agent(f"http://127.0.0.1:{server.server_address[1]}")
    result = agent.run("每个月吃饭有补贴吗?")

    assert result.status == "unfinished"  # 引用被剔光后 answered 不满足状态约束 → 反馈继续,响应耗尽
    assert any("至少一条可核验引用" in (s.observation.error or "") for s in result.trace if not s.observation.ok)
    assert result.dropped_citations
