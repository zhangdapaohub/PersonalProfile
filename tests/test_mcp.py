"""MCP 模块端到端测试（零依赖，直接 python tests/test_mcp.py 运行）。

覆盖：
1. 模块独立性：mcp 包源码禁止 import web/cli/ai；web/core/cli 源码禁止 import mcp。
2. 协议层：initialize / ping / 未知方法错误码 / 解析错误容错。
3. 工具层：6 个只读工具对真实 data/archive.json 的端到端调用（子进程 stdio）。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "personal_profile")

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


# ---------- 1. 模块独立性静态检查 ----------

def test_isolation():
    print("[1] 模块独立性检查")
    forbidden = {
        "mcp": ("personal_profile.web", "personal_profile.cli", "personal_profile.ai"),
        "web": ("personal_profile.mcp",),
        "core": ("personal_profile.web", "personal_profile.cli", "personal_profile.ai",
                 "personal_profile.mcp"),
        "cli": ("personal_profile.web", "personal_profile.mcp"),
    }
    for mod, bad_imports in forbidden.items():
        mod_dir = os.path.join(PKG, mod)
        hits = []
        for dirpath, _, files in os.walk(mod_dir):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                with open(os.path.join(dirpath, fn), encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        # 只认真实 import 语句（docstring/注释里提到模块名不算）
                        if s.startswith("import ") or s.startswith("from "):
                            for bad in bad_imports:
                                if bad in s:
                                    hits.append(f"{fn}:{bad}")
        check(f"{mod} 不依赖 {'/'.join(b.split('.')[-1] for b in bad_imports)}", not hits, "; ".join(hits))


# ---------- 2/3. 子进程端到端 ----------

class StdioClient:
    """测试用 MCP stdio 客户端：写一行 JSON，读一行 JSON（带超时）。"""

    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "personal_profile.mcp"],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        )
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self._id = 0

    def _pump(self):
        for line in self.proc.stdout:
            self.q.put(line.strip())

    def send_raw(self, line: str):
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self.send_raw(json.dumps(msg, ensure_ascii=False))
        return self.recv()

    def recv(self, timeout: float = 10.0) -> dict:
        line = self.q.get(timeout=timeout)
        return json.loads(line)

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.wait(timeout=5)


def _tool_payload(resp: dict) -> dict:
    result = resp["result"]
    assert result["isError"] is False, result["content"][0]["text"]
    return json.loads(result["content"][0]["text"])


def test_protocol(client: StdioClient):
    print("[2] 协议层")
    r = client.request("initialize", {"protocolVersion": "2024-11-05",
                                      "capabilities": {}, "clientInfo": {"name": "test"}})
    check("initialize 回显协议版本与 serverInfo",
          r["result"]["serverInfo"]["name"] == "personal-profile"
          and r["result"]["protocolVersion"] == "2024-11-05")
    client.send_raw(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    r = client.request("ping")
    check("ping -> {}", r["result"] == {})
    r = client.request("tools/list")
    names = {t["name"] for t in r["result"]["tools"]}
    check("tools/list 返回 6 个只读工具",
          names == {"pp_list_persons", "pp_get_profile", "pp_query_path",
                    "pp_timeline", "pp_search", "pp_qbank_progress"}, str(names))
    client.send_raw('{"jsonrpc":"2.0","id":900,"method":"no/such/method"}')
    r = client.recv()
    check("未知方法 -> -32601", r["error"]["code"] == -32601)
    client.send_raw("not-json-at-all")
    r = client.recv()
    check("非法 JSON -> -32700", r["error"]["code"] == -32700)


def test_tools(client: StdioClient):
    print("[3] 工具层（真实数据只读端到端）")
    persons = _tool_payload(client.request("tools/call", {
        "name": "pp_list_persons", "arguments": {}}))["persons"]
    check("pp_list_persons 非空且含最新快照", len(persons) >= 1
          and all("latest_snapshot" in p for p in persons))

    # 用返回的第一个人名走名称解析路径
    name = persons[0]["name"]
    pid = persons[0]["identity_id"]
    prof = _tool_payload(client.request("tools/call", {
        "name": "pp_get_profile", "arguments": {"person": name}}))
    check("pp_get_profile 按人物名取到全量档案", prof["total"] > 0 and prof["person"]["id"] == pid)

    # 选一个档案里确有 inbody 数据的人物来测前缀查询
    target = next((p for p in persons if any(
        pp["person"]["id"] == p["identity_id"] and any(k.startswith("inbody.") for k in pp["profile"])
        for pp in [_tool_payload(client.request("tools/call", {
            "name": "pp_get_profile", "arguments": {"person": p["identity_id"]}}))])),
        None)
    qpid = target["identity_id"] if target else pid
    sid_probe = _tool_payload(client.request("tools/call", {
        "name": "pp_get_profile", "arguments": {"person": qpid}}))
    sid = sid_probe["snapshot"]["id"]
    q = _tool_payload(client.request("tools/call", {
        "name": "pp_query_path", "arguments": {"person": qpid, "paths": ["inbody"]}}))
    check("pp_query_path 前缀命中健康子树",
          q["matched"] > 0 and all(r["path"].startswith("inbody.") for r in q["rows"].values()))

    tl = _tool_payload(client.request("tools/call", {
        "name": "pp_timeline", "arguments": {"person": pid}}))
    check("pp_timeline 快照升序且含继承关系",
          len(tl["snapshots"]) >= 1
          and tl["snapshots"] == sorted(tl["snapshots"], key=lambda s: s["timestamp"]))

    sr = _tool_payload(client.request("tools/call", {
        "name": "pp_search", "arguments": {"person": pid, "keyword": "体重"}}))
    check("pp_search 关键词命中", sr["matched"] >= 1)

    pr = _tool_payload(client.request("tools/call", {
        "name": "pp_qbank_progress", "arguments": {"person": qpid, "snapshot_id": sid}}))
    check("pp_qbank_progress 领域进度 + 缺口样例",
          pr["total"] > 0 and 0 <= pr["pct"] <= 100 and len(pr["missing_sample"]) <= 15)

    r = client.request("tools/call", {"name": "pp_no_such_tool", "arguments": {}})
    check("未知工具 -> isError 带内错误", r["result"]["isError"] is True)
    r = client.request("tools/call", {"name": "pp_get_profile", "arguments": {}})
    check("缺 person -> isError 带内错误", r["result"]["isError"] is True)
    r = client.request("tools/call", {"name": "pp_get_profile",
                                      "arguments": {"person": "p_not_exist"}})
    check("人物不存在 -> isError 带内错误", r["result"]["isError"] is True)

    # 只读性回归：跑完工具后数据文件内容不变（对比前 2KB 哈希 + mtime + size）
    data_file = os.path.join(ROOT, "data", "archive.json")
    before = (os.path.getsize(data_file), os.path.getmtime(data_file))
    _ = _tool_payload(client.request("tools/call", {
        "name": "pp_get_profile", "arguments": {"person": pid}}))
    after = (os.path.getsize(data_file), os.path.getmtime(data_file))
    check("全部工具调用后数据文件未被写（size+mtime 不变）", before == after)


def main():
    print("=" * 60)
    test_isolation()
    print("=" * 60)
    client = StdioClient()
    try:
        test_protocol(client)
        print("-" * 60)
        test_tools(client)
    finally:
        client.close()
    print("=" * 60)
    print(f"总计 {len(PASS) + len(FAIL)} 项：PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        print("失败项：", FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
