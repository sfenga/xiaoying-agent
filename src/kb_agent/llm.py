"""模型接入:OpenAI 兼容 HTTP 客户端 + 动作 JSON 解析。"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests


class LLMError(Exception):
    """模型服务调用失败(网络、鉴权、返回格式等)。"""


class OpenAICompatLLM:
    """最小实现的 OpenAI 兼容 chat/completions 客户端(仅依赖 requests)。

    支持任何兼容服务:OpenAI / 智谱 GLM / DeepSeek / Moonshot / vLLM 等。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.1,
        timeout: float = 60.0,
        max_retries: int = 2,
    ):
        if not base_url or not api_key or not model:
            raise LLMError("OpenAICompatLLM 需要 base_url / api_key / model 三项配置")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    def chat(self, system: str, user: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                last_error = LLMError(f"模型服务暂时不可用(HTTP {resp.status_code}),已重试")
                continue
            if resp.status_code != 200:
                raise LLMError(f"模型服务返回 HTTP {resp.status_code}: {resp.text[:300]}")
            try:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError) as exc:
                raise LLMError(f"模型服务返回格式异常: {resp.text[:300]}") from exc
            if not isinstance(content, str) or not content.strip():
                raise LLMError("模型服务返回了空内容")
            return content
        raise LLMError(f"模型服务调用失败(重试 {self.max_retries} 次后): {last_error!r}")


def parse_action(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出中解析动作 JSON。容错:代码围栏、前后说明文字。解析失败返回 None。"""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
