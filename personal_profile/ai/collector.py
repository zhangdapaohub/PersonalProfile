"""AI 采集层：抽象接口、实现注册表与模型调用。

新增采集器只需：
1) 继承 Collector 实现 collect()；
2) 在 COLLECTORS 注册。
采集器只负责把 prompt 解析为 {path: value}，落库一律经 Archive.set_value。

模型接入（零依赖，urllib 直连 OpenAI 兼容 /chat/completions）：
  腾讯混元  https://api.hunyuan.cloud.tencent.com/v1   模型如 hunyuan-turbos-latest
  DeepSeek  https://api.deepseek.com/v1                模型如 deepseek-chat
  本地 Ollama http://127.0.0.1:11434/v1                模型如 qwen2.5
配置存于 data/config.json（Web 页面『模型设置』或 CLI 可写）。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

SYSTEM_PROMPT = """你是个人档案系统的信息抽取器。根据用户描述，抽取结构化字段写入档案。
规则：
1. 只输出一个 JSON 对象，禁止输出任何解释文字或代码块标记。
2. 格式：{"维度路径": 值}。路径用点分层，常用：physical.body_shape.height、physical.body_shape.weight、
   mental.cognitive.thoughts、mental.tendency.preferences、timeline.life_stage、timeline.role、timeline.milestone。
3. 值只能是字符串、数字、布尔，或字符串数组；不确定的字段不要输出。
示例：{"physical.body_shape.height": 175, "mental.tendency.preferences": ["简洁", "务实"]}"""


class Collector(ABC):
    """采集器接口：把自然语言 prompt 解析为 {path: value} 字段更新。"""

    @abstractmethod
    def collect(self, prompt: str, context: dict) -> dict:
        """context 含 person/snapshot、已解析叶子 resolved、时间上下文。
        返回 {path: value}；由调用方经 Archive.set_value 逐条落库。"""


class StubCollector(Collector):
    """占位实现：不接真实模型，返回空更新。"""

    def collect(self, prompt: str, context: dict) -> dict:
        return {}


class OpenAICompatibleCollector(Collector):
    """OpenAI 兼容 /chat/completions 采集器（混元 / DeepSeek / Ollama 等通用）。"""

    def __init__(self, base_url: str = "", api_key: str = "", model: str = "", timeout: int = 60):
        if not base_url or not model:
            raise ValueError(
                "未配置模型：请在 Web 端『AI 采集 → 模型设置』填写 Base URL 与模型名并保存"
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    # ---------- 模型调用 ----------

    def _chat(self, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            raise ValueError(f"模型接口 HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            raise ValueError(f"无法连接模型接口 {self.base_url}: {e.reason}")
        except json.JSONDecodeError:
            raise ValueError("模型接口返回的不是合法 JSON")

    @staticmethod
    def _parse_updates(content: str) -> dict:
        text = content.strip()
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(f"模型未返回 JSON 对象: {content[:120]}")
        try:
            obj = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            raise ValueError(f"模型返回的 JSON 无法解析: {content[:120]}")
        if not isinstance(obj, dict):
            raise ValueError("模型返回的 JSON 不是对象")
        return obj

    # ---------- Collector 接口 ----------

    def collect(self, prompt: str, context: dict) -> dict:
        resolved: dict = (context or {}).get("resolved") or {}
        snapshot = (context or {}).get("snapshot", "")
        lines = []
        for path, leaf in resolved.items():
            val = leaf.get("value") if isinstance(leaf, dict) else leaf
            lines.append(f"- {path}: {val}")
        user_text = (
            "【该时间态已有档案值】\n" + ("\n".join(lines) or "（空）") +
            f"\n\n【当前时间态】{snapshot}" +
            f"\n\n【用户描述】\n{prompt}\n\n请输出 JSON 字段更新。"
        )
        data = self._chat({
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.2,
        })
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ValueError(f"模型响应结构异常: {json.dumps(data, ensure_ascii=False)[:200]}")
        return self._parse_updates(content)


COLLECTORS: dict = {
    "stub": StubCollector,
    "openai-compatible": OpenAICompatibleCollector,
}


def get_collector(name: str = "stub", config: dict | None = None) -> Collector:
    cls = COLLECTORS.get(name)
    if cls is None:
        raise ValueError(f"未知 collector: {name}（可选: {', '.join(COLLECTORS)}）")
    if name == "openai-compatible":
        cfg = config or {}
        return cls(
            base_url=cfg.get("base_url", ""),
            api_key=cfg.get("api_key", ""),
            model=cfg.get("model", ""),
        )
    return cls()
