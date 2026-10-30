"""配置:环境变量 + .env 自动加载 + CLI 覆盖。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ENV_ENGINE = "AGENT_MODEL_ENGINE"
ENV_BASE_URL = "AGENT_LLM_BASE_URL"
ENV_API_KEY = "AGENT_LLM_API_KEY"
ENV_MODEL = "AGENT_LLM_MODEL"
ENV_MAX_STEPS = "AGENT_MAX_STEPS"
ENV_DATA_PATH = "AGENT_DATA_PATH"
ENV_RULES_PATH = "AGENT_RULES_PATH"
ENV_INJECT = "AGENT_INJECT_TOOL_FAILURE"
ENV_TOP_K = "AGENT_TOP_K"

ENGINE_AUTO = "auto"
ENGINE_MOCK = "mock"
ENGINE_REAL = "real"
VALID_ENGINES = {ENGINE_AUTO, ENGINE_MOCK, ENGINE_REAL}

VALID_INJECT_MODES = {"", "read_once", "search_once", "read_all"}

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ConfigError(Exception):
    """配置错误(如强制 real 引擎但未提供模型配置)。"""


def load_dotenv(path: Optional[Path] = None) -> None:
    """极简 .env 加载:仅设置尚未存在的环境变量,不覆盖已有值。"""
    env_path = path or (Path.cwd() / ".env")
    if not env_path.is_file():
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _has_real_model_config(cfg: "Config") -> bool:
    return bool(cfg.api_key and cfg.model and cfg.base_url)


@dataclass
class Config:
    engine: str = ENGINE_AUTO          # resolved engine: mock / real
    engine_request: str = ENGINE_AUTO  # 用户请求的引擎(auto/mock/real)
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    max_steps: int = 8
    top_k: int = 4
    data_path: Path = PROJECT_ROOT / "data" / "documents.json"
    rules_path: Path = PROJECT_ROOT / "data" / "rules.json"
    inject_failure: str = ""

    def __post_init__(self) -> None:
        # 直接构造(而非 from_env)时同样完成引擎解析;engine 已是终态时不重复处理
        if self.engine not in (ENGINE_MOCK, ENGINE_REAL) or self.engine != self.engine_request:
            self.engine = self._resolve_engine(self)

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        engine_request = os.environ.get(ENV_ENGINE, ENGINE_AUTO).strip().lower()
        if engine_request not in VALID_ENGINES:
            raise ConfigError(f"{ENV_ENGINE} 取值无效: {engine_request!r}(应为 auto/mock/real)")
        inject = os.environ.get(ENV_INJECT, "").strip().lower()
        if inject not in VALID_INJECT_MODES:
            raise ConfigError(f"{ENV_INJECT} 取值无效: {inject!r}(应为空/read_once/search_once/read_all)")
        cfg = cls(
            engine_request=engine_request,
            base_url=os.environ.get(ENV_BASE_URL, "").strip().rstrip("/"),
            api_key=os.environ.get(ENV_API_KEY, "").strip(),
            model=os.environ.get(ENV_MODEL, "").strip(),
            max_steps=_int_env(ENV_MAX_STEPS, 8, minimum=1),
            top_k=_int_env(ENV_TOP_K, 4, minimum=1),
            data_path=Path(os.environ.get(ENV_DATA_PATH) or (PROJECT_ROOT / "data" / "documents.json")),
            rules_path=Path(os.environ.get(ENV_RULES_PATH) or (PROJECT_ROOT / "data" / "rules.json")),
            inject_failure=inject,
        )
        cfg.engine = cls._resolve_engine(cfg)
        return cfg

    @staticmethod
    def _resolve_engine(cfg: "Config") -> str:
        if cfg.engine_request == ENGINE_MOCK:
            return ENGINE_MOCK
        if cfg.engine_request == ENGINE_REAL:
            if not _has_real_model_config(cfg):
                raise ConfigError(
                    "AGENT_MODEL_ENGINE=real 但未配置 AGENT_LLM_BASE_URL / AGENT_LLM_API_KEY / AGENT_LLM_MODEL"
                )
            return ENGINE_REAL
        # auto:配置了真实模型就用真实模型,否则回退 Mock(调用方负责打印边界警告)
        return ENGINE_REAL if _has_real_model_config(cfg) else ENGINE_MOCK

    def apply_overrides(
        self,
        engine: Optional[str] = None,
        max_steps: Optional[int] = None,
        top_k: Optional[int] = None,
        data_path: Optional[str] = None,
        rules_path: Optional[str] = None,
        inject: Optional[str] = None,
    ) -> None:
        if engine is not None:
            engine = engine.strip().lower()
            if engine not in VALID_ENGINES:
                raise ConfigError(f"--engine 取值无效: {engine!r}(应为 auto/mock/real)")
            self.engine_request = engine
        if max_steps is not None:
            self.max_steps = max(1, max_steps)
        if top_k is not None:
            self.top_k = max(1, top_k)
        if data_path:
            self.data_path = Path(data_path)
        if rules_path:
            self.rules_path = Path(rules_path)
        if inject is not None:
            inject = inject.strip().lower()
            if inject == "none":
                inject = ""
            if inject not in VALID_INJECT_MODES:
                raise ConfigError(f"--inject 取值无效: {inject!r}(应为 none/read_once/search_once/read_all)")
            self.inject_failure = inject
        self.engine = self._resolve_engine(self)


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数,当前为 {raw!r}") from exc
