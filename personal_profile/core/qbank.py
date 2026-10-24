"""提问库模块（Question Bank）。

职责单一：题库的加载 / 校验 / 展平 / 进度推导 / 答案载荷构造。
- 独立于展示层（时间轴/详情）与存储层（Archive）：本模块不做任何写盘，
  也不 import Archive；落库由调用方（web/qbank_api 或 CLI）执行。
- 指标的 path/中文名/单位以 question_bank.json 为唯一权威定义；
  to_registry() 可将其导出为与 dimensions.json 同构的分组，供 /api/schema 合并。
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

from personal_profile.paths import QBANK_PATH

# 允许的题型与输入控件
QUESTION_TYPES = ("fact", "story", "eval")
INPUT_TYPES = ("text", "textarea", "number", "date", "select", "rating")

_PATH_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")

_cache: dict | None = None


class QbankError(ValueError):
    """题库数据或用法错误。"""


def load_qbank(force: bool = False) -> dict:
    """加载题库（模块级缓存；force=True 重新读盘，便于运行期改题后刷新）。"""
    global _cache
    if _cache is not None and not force:
        return _cache
    try:
        with open(QBANK_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise QbankError(f"题库文件不可读: {e}") from e
    if not isinstance(data.get("domains"), list):
        raise QbankError("题库格式错误：缺少 domains 数组")
    _cache = data
    return data


def iter_metrics(qbank: dict) -> Iterator[dict]:
    """展平指标：yield {domain, domain_name, dimension, dimension_name, **metric}。"""
    for dom in qbank.get("domains", []):
        for dim in dom.get("dimensions", []):
            for m in dim.get("metrics", []):
                yield {
                    **m,
                    "domain": dom["key"],
                    "domain_name": dom.get("name") or dom["key"],
                    "dimension": dim["key"],
                    "dimension_name": dim.get("name") or dim["key"],
                }


def validate(qbank: dict | None = None, registry_paths: set[str] | None = None) -> list[str]:
    """静态校验，返回错误列表（空列表 = 通过）。

    - path / id 唯一且格式合法
    - type / input / options / volatile 合法
    - 若给 registry_paths：path 应已注册（dimensions.json 或 qbank 自身注册表）
    """
    errors: list[str] = []
    qbank = qbank if qbank is not None else load_qbank()
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    for m in iter_metrics(qbank):
        path = m.get("path")
        if not path or not _PATH_RE.match(path):
            errors.append(f"非法 path: {path!r}")
            continue
        if path in seen_paths:
            errors.append(f"path 重复: {path}")
        seen_paths.add(path)
        q = m.get("q") or {}
        qid = q.get("id") or f"q:{path}"
        if qid in seen_ids:
            errors.append(f"问题 id 重复: {qid}")
        seen_ids.add(qid)
        if m.get("type") not in QUESTION_TYPES:
            errors.append(f"{path}: type 非法 {m.get('type')!r}")
        if m.get("input") not in INPUT_TYPES:
            errors.append(f"{path}: input 非法 {m.get('input')!r}")
        if m.get("input") == "select" and not m.get("options"):
            errors.append(f"{path}: select 缺 options")
        if not (q.get("text") or "").strip():
            errors.append(f"{path}: 缺问题文本 q.text")
        if registry_paths is not None and path not in registry_paths:
            errors.append(f"{path}: 未在指标注册表中注册")
    return errors


def metric_index(qbank: dict | None = None) -> dict[str, dict]:
    """path → 指标定义（含领域/维度上下文）。"""
    qbank = qbank if qbank is not None else load_qbank()
    return {m["path"]: m for m in iter_metrics(qbank)}


def progress(qbank: dict | None, answered_paths: set[str]) -> dict:
    """进度推导（零状态）：answered = 已答指标 path 集合（一般取快照 overrides 键）。

    返回 {domains: [{key, name, total, answered, pct}], total, answered, pct}
    """
    qbank = qbank if qbank is not None else load_qbank()
    domains: list[dict] = []
    g_total = g_answered = 0
    for dom in qbank.get("domains", []):
        paths = [m["path"] for d in dom.get("dimensions", []) for m in d.get("metrics", [])]
        ans = sum(1 for p in paths if p in answered_paths)
        total = len(paths)
        g_total += total
        g_answered += ans
        domains.append({
            "key": dom["key"], "name": dom.get("name") or dom["key"],
            "total": total, "answered": ans,
            "pct": round(ans / total * 100) if total else 0,
        })
    return {
        "domains": domains,
        "total": g_total, "answered": g_answered,
        "pct": round(g_answered / g_total * 100) if g_total else 0,
    }


def answer_payload(metric: dict, value: Any) -> dict:
    """按注册表定义构造落库载荷：name/unit 以题库为准，调用方不得自带。"""
    payload = {"path": metric["path"], "value": value, "name": metric.get("name")}
    if metric.get("unit"):
        payload["unit"] = metric["unit"]
    return payload


def to_registry(qbank: dict | None = None) -> dict:
    """导出为与 dimensions.json 同构的分组（顶层 key=领域），供 /api/schema 合并。"""
    qbank = qbank if qbank is not None else load_qbank()
    out: dict = {}
    for dom in qbank.get("domains", []):
        children: dict = {}
        for dim in dom.get("dimensions", []):
            leaves = {m["path"].rsplit(".", 1)[-1]: {"name": m.get("name") or "",
                                                     "unit": m.get("unit")}
                      for m in dim.get("metrics", [])}
            children[dim["key"]] = {"name": dim.get("name") or dim["key"], "children": leaves}
        out[dom["key"]] = {"name": dom.get("name") or dom["key"], "children": children}
    return out
