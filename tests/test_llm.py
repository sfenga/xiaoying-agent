"""LLM 接入:动作解析容错、服务失败处理、引擎选择逻辑。"""
from __future__ import annotations

import pytest

from src.kb_agent.config import Config, ConfigError
from src.kb_agent.llm import LLMError, OpenAICompatLLM, parse_action
from src.kb_agent.real_model import LLMReActModel


# ---------------- 动作 JSON 解析 ----------------
def test_parse_action_plain():
    obj = parse_action('{"tool": "search", "params": {"query": "报销"}}')
    assert obj["tool"] == "search"


def test_parse_action_fenced():
    text = "```json\n{\"tool\": \"read\", \"params\": {\"doc_id\": \"D01\"}}\n```"
    assert parse_action(text)["params"]["doc_id"] == "D01"


def test_parse_action_with_prose():
    text = '好的,我决定检索。\n{"thought": "t", "tool": "finish", "params": {"status": "answered"}}\n以上。'
    assert parse_action(text)["tool"] == "finish"


def test_parse_action_invalid():
    assert parse_action("完全不是 JSON") is None
    assert parse_action('{"tool": }') is None
    assert parse_action("[1,2,3]") is None
    assert parse_action("") is None


# ---------------- LLM 客户端 ----------------
def test_llm_requires_config():
    with pytest.raises(LLMError):
        OpenAICompatLLM("", "", "")


def test_llm_unreachable_server_raises_llmerror():
    llm = OpenAICompatLLM(
        "http://127.0.0.1:9", "sk-test", "test-model", timeout=1.5, max_retries=0
    )
    with pytest.raises(LLMError):
        llm.chat("system", "user")


def test_llm_http_error_raises():
    class FakeResp:
        status_code = 401
        text = '{"error": "bad key"}'

        def json(self):
            return {}

    class FakeSession:
        def post(self, *a, **k):
            return FakeResp()

    llm = OpenAICompatLLM("http://x", "k", "m", max_retries=0)
    import src.kb_agent.llm as llm_mod

    llm_mod.requests.post = FakeSession().post  # monkey-patch 模块内 requests
    try:
        with pytest.raises(LLMError, match="401"):
            llm.chat("s", "u")
    finally:
        import importlib

        importlib.reload(llm_mod)


# ---------------- 真实模型决策器 ----------------
class _StubLLM:
    def __init__(self, output):
        self.output = output
        self.model = "stub-model"

    def chat(self, system, user):
        return self.output


def test_llm_model_parses_action():
    model = LLMReActModel(_StubLLM('{"thought":"t","tool":"search","params":{"query":"q"}}'))
    action = model.decide("q", [], [], 5)
    assert action["tool"] == "search"


def test_llm_model_invalid_output_returns_invalid_action():
    model = LLMReActModel(_StubLLM("我不会输出 JSON"))
    action = model.decide("q", [], [], 5)
    assert action["tool"] == "__invalid__"  # 循环会将其作为错误观察反馈给模型


# ---------------- 引擎选择 ----------------
def _base_cfg(**kw):
    return dict(base_url="", api_key="", model="")


def test_engine_auto_falls_back_to_mock():
    cfg = Config(engine_request="auto", **_base_cfg())
    assert cfg.engine == "mock"


def test_engine_auto_uses_real_when_configured():
    cfg = Config(engine_request="auto", base_url="http://x/v1", api_key="k", model="m")
    assert cfg.engine == "real"


def test_engine_real_without_config_raises():
    with pytest.raises(ConfigError):
        Config(engine_request="real", **_base_cfg())


def test_engine_mock_forced_even_with_config():
    cfg = Config(engine_request="mock", base_url="http://x/v1", api_key="k", model="m")
    assert cfg.engine == "mock"


def test_apply_overrides_invalid_engine():
    cfg = Config(engine_request="auto")
    with pytest.raises(ConfigError):
        cfg.apply_overrides(engine="bogus")
