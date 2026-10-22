"""Web 端服务：localhost 静态页 + JSON API，零第三方依赖。

启动：python -m personal_profile.web.server   →  http://127.0.0.1:8765
环境变量：PP_DATA（数据文件路径）、PP_PORT（端口）。

API 一览：
  GET    /api/persons                             人物列表
  POST   /api/persons                             新增人物 {name, id?}
  GET    /api/persons/<pid>                       时间轴全量视图（快照+合并叶子+链接）
  GET    /api/persons/<pid>/export                 导出人物为自包含 JSON（含全部快照与链接）
  POST   /api/persons/import                       导入人物 JSON（body 即导出结构；冲突自动重映射）
  GET    /api/persons/<pid>/snapshots/<sid>       快照详情（含值来源标注 trace）
  PUT    /api/persons/<pid>/snapshots/<sid>       快照改名 {label}
  DELETE /api/persons/<pid>/snapshots/<sid>       删除快照（含相关链接，继承链自动衔接）
  POST   /api/snapshots                           新增快照 {person, timestamp, label, inherits_from?, break_chain?, id?}（默认自动继承上一个）
  POST   /api/snapshots/inherits                  设置/清除继承 {person, snapshot, inherits_from|null}
  GET    /api/value?person=&snapshot=&path=       取值（沿链合并）
  POST   /api/value                               写值 {person, snapshot, path, value, unit?, name?}
  DELETE /api/value                               删本态覆盖 {person, snapshot, path}
  POST   /api/links                               新增链接 {person, from, to, type, note?, auto_inherit?}
  DELETE /api/links                               删链接 {person, link_id}
  POST   /api/collect                             AI 采集 {person, snapshot, prompt, collector?}
  GET    /api/config                              模型配置（掩码）
  POST   /api/config                              保存模型配置 {base_url, api_key?, model}
  GET    /api/schema                              维度模板
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from personal_profile.ai.collector import get_collector  # noqa: E402
from personal_profile.core import config as pp_config  # noqa: E402
from personal_profile.core.logutil import get_logger  # noqa: E402
from personal_profile.core.store import INHERIT_REQUIRED_LINKS, Archive, ArchiveError  # noqa: E402
from personal_profile.paths import DATA_PATH, SCHEMA_PATH  # noqa: E402

log = get_logger("web")  # 运行日志：logs/web.log（自动轮转）+ 控制台

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_TPL_DIR = os.path.join(_WEB_DIR, "templates")
_STATIC_DIR = os.path.join(_WEB_DIR, "static")
DATA_FILE = os.path.normpath(DATA_PATH)
HOST = "127.0.0.1"
PORT = int(os.environ.get("PP_PORT", "8765"))


def _load_schema() -> dict:
    """维度模板（key → {name, children...}），供前端展示维度中文名。"""
    try:
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            tpl = json.load(f)
        return tpl if isinstance(tpl, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


SCHEMA = _load_schema()

archive = Archive(DATA_FILE).load()
_LOCK = threading.Lock()  # 写操作互斥，避免并发写坏 JSON

_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    # ---------- 输出工具 ----------

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if self.path.startswith("/api/"):
            log.info("%s %s -> %d", self.command, self.path, code)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, payload=None) -> None:
        self._json(200, payload if payload is not None else {"ok": True})

    def _fail(self, code: int, msg: str) -> None:
        log.warning("%s %s -> %d 失败原因: %s", self.command, self.path, code, msg)
        self._json(code, {"error": msg})

    @staticmethod
    def _safe_body(b: dict) -> str:
        """请求体摘要（脱敏：含 key/token/secret/password 的字段只留是否非空）。"""
        parts = []
        for k, v in b.items():
            if any(s in k.lower() for s in ("key", "token", "secret", "password")):
                parts.append(f"{k}={'***' if v else ''}")
            else:
                s = json.dumps(v, ensure_ascii=False)
                parts.append(f"{k}={s if len(s) <= 120 else s[:120] + '...'}")
        return " ".join(parts)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("请求体不是合法 JSON")
        return data if isinstance(data, dict) else {}

    def _static(self, path: str) -> None:
        if path in ("/", ""):
            file_path = os.path.join(_TPL_DIR, "index.html")
        elif path.startswith("/static/"):
            file_path = os.path.normpath(os.path.join(_STATIC_DIR, path[len("/static/"):]))
        else:
            return self._fail(404, "not found")
        if not file_path.startswith(_STATIC_DIR) and not file_path.startswith(_TPL_DIR):
            return self._fail(404, "not found")
        if not os.path.isfile(file_path):
            return self._fail(404, "not found")
        ctype = _STATIC_TYPES.get(os.path.splitext(file_path)[1], "application/octet-stream")
        with open(file_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- 路由 ----------

    def do_GET(self) -> None:  # noqa: N802
        try:
            u = urlparse(self.path)
            parts = [p for p in u.path.split("/") if p]
            if not u.path.startswith("/api/"):
                return self._static(u.path)
            if parts == ["api", "persons"]:
                return self._ok({"kind": "persons", "persons": archive.list_persons()})
            if len(parts) == 3 and parts[:2] == ["api", "persons"]:
                return self._ok({**archive.tree(parts[2]), "kind": "tree"})
            if len(parts) == 4 and parts[:2] == ["api", "persons"] and parts[3] == "export":
                return self._ok({**archive.export_person(parts[2]), "kind": "person-export"})
            if len(parts) == 5 and parts[:2] == ["api", "persons"] and parts[3] == "snapshots":
                pid, sid = parts[2], parts[4]
                return self._ok({
                    "kind": "snapshot-detail",
                    "snapshot": archive.get_snapshot(pid, sid),
                    "trace": archive.resolve_trace(pid, sid),
                    "links": archive.list_links(pid),
                })
            if u.path == "/api/value":
                q = parse_qs(u.query)
                try:
                    pid, sid, path = q["person"][0], q["snapshot"][0], q["path"][0]
                except KeyError as e:
                    raise ValueError(f"缺少查询参数: {e}")
                leaf = archive.resolve_value(pid, sid, path)
                if leaf is None:
                    raise ArchiveError(f"未找到值: {path}")
                return self._ok({"kind": "value", "leaf": leaf})
            if u.path == "/api/config":
                return self._ok(pp_config.masked(pp_config.load_config()))
            if u.path == "/api/schema":
                return self._ok({"kind": "schema", "dimensions": SCHEMA})
            return self._fail(404, "unknown api")
        except ArchiveError as e:
            return self._fail(400, str(e))
        except ValueError as e:
            return self._fail(400, str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("未捕获异常 %s %s", self.command, self.path)
            return self._fail(500, f"internal: {type(e).__name__}: {e}")

    def do_POST(self) -> None:  # noqa: N802
        try:
            u = urlparse(self.path)
            b = self._body()
            log.info("WRITE POST %s | %s", u.path, self._safe_body(b))
            if u.path == "/api/persons":
                with _LOCK:
                    pid = archive.add_person(b.get("name") or "", b.get("id"))
                    archive.save()
                return self._ok({"identity_id": pid})
            if u.path == "/api/persons/import":
                with _LOCK:
                    res = archive.import_person(b)
                    archive.save()
                return self._ok(res)
            if u.path == "/api/snapshots":
                with _LOCK:
                    sid = archive.add_snapshot(
                        b["person"], b["timestamp"], b.get("label") or "",
                        b.get("inherits_from"), b.get("id"),
                        break_chain=bool(b.get("break_chain", False)),
                    )
                    archive.save()
                return self._ok({"snapshot_id": sid})
            if u.path == "/api/snapshots/inherits":
                parent = b.get("inherits_from") or None  # 空串/null = 清除
                with _LOCK:
                    snap = archive.set_inherits(b["person"], b["snapshot"], parent)
                    archive.save()
                return self._ok({
                    "snapshot": snap["id"],
                    "inherits_from": snap["inherits_from"],
                    "note": "已改为独立根态" if parent is None else "继承关系已建立",
                })
            if u.path == "/api/value":
                with _LOCK:
                    leaf = archive.set_value(
                        b["person"], b["snapshot"], b["path"],
                        b.get("value"), b.get("unit"), b.get("name"),
                    )
                    archive.save()
                return self._ok({"leaf": leaf})
            if u.path == "/api/break":
                with _LOCK:
                    archive.set_break(
                        b["person"], b["snapshot"], b["path"], bool(b.get("on", True)),
                    )
                    archive.save()
                return self._ok()
            if u.path == "/api/order":
                with _LOCK:
                    archive.set_order(
                        b["person"], b["snapshot"], b.get("order") or [],
                    )
                    archive.save()
                return self._ok()
            if u.path == "/api/links":
                with _LOCK:
                    # auto_inherit：继承/因果链接且继承关系未建立时，先自动补建
                    if (b.get("auto_inherit") and b["type"] in INHERIT_REQUIRED_LINKS
                            and archive.get_snapshot(b["person"], b["to"])["inherits_from"] != b["from"]):
                        archive.set_inherits(b["person"], b["to"], b["from"])
                    lid = archive.add_link(
                        b["person"], b["from"], b["to"], b["type"], b.get("note") or "",
                        from_path=b.get("from_path"), to_path=b.get("to_path"),
                    )
                    archive.save()
                return self._ok({"link_id": lid})
            if u.path == "/api/collect":
                name = b.get("collector") or "stub"
                if name == "openai-compatible":
                    collector = get_collector(name, pp_config.load_config())
                else:
                    collector = get_collector(name)
                context = {
                    "person": b["person"],
                    "snapshot": b["snapshot"],
                    "resolved": archive.resolved_leaves(b["person"], b["snapshot"]),
                }
                updates = collector.collect(b.get("prompt") or "", context)
                if not isinstance(updates, dict):
                    raise ArchiveError("collector 返回必须为 {path: value} 字典")
                applied, errors = {}, []
                with _LOCK:
                    for path, value in updates.items():
                        try:
                            applied[path] = archive.set_value(b["person"], b["snapshot"], path, value)
                        except ArchiveError as e:
                            errors.append({"path": path, "error": str(e)})
                    if applied:
                        archive.save()
                note = None
                if not applied and not errors:
                    note = "模型未抽取到任何字段"
                return self._ok({
                    "applied": applied, "errors": errors, "note": note,
                    "collector": name,
                })
            if u.path == "/api/config":
                old = pp_config.load_config()
                # 不传 api_key 字段 = 保留旧值；显式传空串 = 清除
                api_key = old["api_key"]
                if "api_key" in b:
                    api_key = str(b.get("api_key") or "").strip()
                saved = pp_config.save_config({
                    "base_url": b.get("base_url", old["base_url"]),
                    "api_key": api_key,
                    "model": b.get("model", old["model"]),
                })
                return self._ok({"saved": True, **pp_config.masked(saved)})
            return self._fail(404, "unknown api")
        except ArchiveError as e:
            return self._fail(400, str(e))
        except KeyError as e:
            return self._fail(400, f"缺少字段: {e}")
        except ValueError as e:
            return self._fail(400, str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("未捕获异常 %s %s", self.command, self.path)
            return self._fail(500, f"internal: {type(e).__name__}: {e}")

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            u = urlparse(self.path)
            b = self._body()
            log.info("WRITE DELETE %s | %s", u.path, self._safe_body(b) if b else "")
            parts = [p for p in u.path.split("/") if p]
            if len(parts) == 3 and parts[:2] == ["api", "persons"]:
                with _LOCK:
                    archive.delete_person(parts[2])
                    archive.save()
                return self._ok()
            if len(parts) == 5 and parts[:2] == ["api", "persons"] and parts[3] == "snapshots":
                with _LOCK:
                    archive.delete_snapshot(parts[2], parts[4])
                    archive.save()
                return self._ok()
            if u.path == "/api/value":
                with _LOCK:
                    archive.del_value(b["person"], b["snapshot"], b["path"])
                    archive.save()
                return self._ok()
            if u.path == "/api/links":
                with _LOCK:
                    archive.rm_link(b["person"], b["link_id"])
                    archive.save()
                return self._ok()
            return self._fail(404, "unknown api")
        except ArchiveError as e:
            return self._fail(400, str(e))
        except KeyError as e:
            return self._fail(400, f"缺少字段: {e}")
        except Exception as e:  # noqa: BLE001
            log.exception("未捕获异常 %s %s", self.command, self.path)
            return self._fail(500, f"internal: {type(e).__name__}: {e}")

    def do_PUT(self) -> None:  # noqa: N802
        try:
            u = urlparse(self.path)
            b = self._body()
            log.info("WRITE PUT %s | %s", u.path, self._safe_body(b))
            parts = [p for p in u.path.split("/") if p]
            if len(parts) == 3 and parts[:2] == ["api", "persons"]:
                with _LOCK:
                    archive.rename_person(parts[2], b.get("name") or "")
                    archive.save()
                return self._ok()
            if len(parts) == 5 and parts[:2] == ["api", "persons"] and parts[3] == "snapshots":
                with _LOCK:
                    archive.rename_snapshot(parts[2], parts[4], b.get("label") or "")
                    archive.save()
                return self._ok()
            return self._fail(404, "unknown api")
        except ArchiveError as e:
            return self._fail(400, str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("未捕获异常 %s %s", self.command, self.path)
            return self._fail(500, f"internal: {type(e).__name__}: {e}")

    def log_message(self, fmt, *args) -> None:  # 标准访问日志走 debug（仅落文件，不刷控制台）
        log.debug("%s - %s", self.address_string(), fmt % args)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("========== PersonalProfile Web 启动 http://%s:%d | 数据: %s ==========", HOST, PORT, DATA_FILE)
    print(f"PersonalProfile Web running at http://{HOST}:{PORT}  (日志: logs/web.log)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("========== PersonalProfile Web 停止 ==========")
        server.server_close()


if __name__ == "__main__":
    main()
