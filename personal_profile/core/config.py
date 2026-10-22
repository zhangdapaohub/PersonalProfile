"""采集模型配置：data/config.json（本地明文存储，勿提交版本库）。

字段：base_url（OpenAI 兼容端点）、api_key、model。
Web 与 CLI 共用本模块读写。
"""

from __future__ import annotations

import json
import os
import tempfile

from personal_profile.paths import CONFIG_PATH

_KEYS = ("base_url", "api_key", "model")


def _clean(cfg: dict) -> dict:
    return {k: str(cfg.get(k) or "").strip() for k in _KEYS}


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            cfg = {}
        if isinstance(cfg, dict):
            return _clean(cfg)
    return {k: "" for k in _KEYS}


def save_config(cfg: dict) -> dict:
    clean = _clean(cfg)
    d = os.path.dirname(os.path.abspath(CONFIG_PATH))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return clean


def masked(cfg: dict) -> dict:
    """对外展示用：不回传完整 api_key。"""
    key = cfg.get("api_key") or ""
    return {
        "base_url": cfg.get("base_url", ""),
        "model": cfg.get("model", ""),
        "api_key_masked": (key[:4] + "****" + key[-4:]) if len(key) > 8 else ("已保存" if key else ""),
        "has_key": bool(key),
    }
