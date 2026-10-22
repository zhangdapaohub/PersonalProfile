/* 写操作：人物 / 快照 / 链接 / 值 / AI 采集 / 模型配置 */

import { api } from "./api.js";
import { state } from "./state.js";
import { toast, parseValue, openModal, closeModal } from "./util.js";
import { selectPerson, loadPersons } from "./view.js";
import { selectSnapshot } from "./timeline.js";

/* ---------- 人物 ---------- */

export async function submitPerson() {
  const name = document.getElementById("personName").value.trim();
  if (!name) return toast("请填写人物名称", true);
  try {
    const d = await api("/api/persons", { method: "POST", body: JSON.stringify({ name }) });
    closeModal("personModal");
    document.getElementById("personName").value = "";
    toast("已创建：" + name);
    await loadPersons();
    selectPerson(d.identity_id);
  } catch (e) { toast(e.message, true); }
}

/* ---------- 快照 ---------- */

export async function submitSnapshot() {
  const timestamp = document.getElementById("snapTs").value;
  const label = document.getElementById("snapLabel").value.trim();
  const inherits_from = document.getElementById("snapInherits").value || null;
  if (!timestamp || !label) return toast("请填写时间与标签", true);
  try {
    await api("/api/snapshots", {
      method: "POST",
      body: JSON.stringify({ person: state.current, timestamp, label, inherits_from }),
    });
    closeModal("snapshotModal");
    toast("快照已创建：" + label);
    await selectPerson(state.current);
    state.selected = null;
  } catch (e) { toast(e.message, true); }
}

/* ---------- 继承关系 ---------- */

export async function setInherits(snapshot, parent) {
  try {
    await api("/api/snapshots/inherits", {
      method: "POST",
      body: JSON.stringify({ person: state.current, snapshot, inherits_from: parent }),
    });
    toast(parent ? `继承关系已建立: ${snapshot} → ${parent}` : "已改为独立根态");
    await selectPerson(state.current);
    await selectSnapshot(snapshot);
  } catch (e) { toast(e.message, true); }
}

/* ---------- 链接 ---------- */

export async function submitLink() {
  const body = {
    person: state.current,
    from: document.getElementById("linkFrom").value,
    from_path: document.getElementById("linkFromPath").value.trim(),
    to: document.getElementById("linkTo").value,
    to_path: document.getElementById("linkToPath").value.trim(),
    type: document.getElementById("linkType").value,
    note: document.getElementById("linkNote").value.trim(),
    auto_inherit: document.getElementById("linkAutoInherit").checked,
  };
  if (!body.from || !body.to) return toast("请选择起止快照", true);
  if (body.from === body.to) return toast("起止快照不能相同", true);
  if (!body.from_path || !body.to_path) return toast("请填写起始属性与目标属性的维度路径", true);
  try {
    await api("/api/links", { method: "POST", body: JSON.stringify(body) });
    closeModal("linkModal");
    toast("属性链接已创建");
    await selectPerson(state.current);
  } catch (e) { toast(e.message, true); }
}

export async function delLink(linkId) {
  try {
    await api("/api/links", {
      method: "DELETE",
      body: JSON.stringify({ person: state.current, link_id: linkId }),
    });
    toast("链接已删除");
    await selectPerson(state.current);
    if (state.selected) await selectSnapshot(state.selected);
  } catch (e) { toast(e.message, true); }
}

/* ---------- 值 ---------- */

export async function submitValue() {
  const path = document.getElementById("vPath").value.trim();
  const raw = document.getElementById("vValue").value;
  const unit = document.getElementById("vUnit").value.trim() || null;
  const name = document.getElementById("vName").value.trim() || null;
  if (!path || !raw) return toast("请填写路径与值", true);
  try {
    await api("/api/value", {
      method: "POST",
      body: JSON.stringify({
        person: state.current, snapshot: state.selected,
        path, value: parseValue(raw), unit, name,
      }),
    });
    toast("已写入：" + path);
    await selectPerson(state.current);
    await selectSnapshot(state.selected);
  } catch (e) { toast(e.message, true); }
}

export async function delValue(path) {
  try {
    await api("/api/value", {
      method: "DELETE",
      body: JSON.stringify({ person: state.current, snapshot: state.selected, path }),
    });
    toast("已删除本态覆盖：" + path);
    await selectPerson(state.current);
    await selectSnapshot(state.selected);
  } catch (e) { toast(e.message, true); }
}

/* ---------- AI 采集 ---------- */

export async function submitCollect() {
  const raw = document.getElementById("collectSnap").value.trim();
  const prompt = document.getElementById("collectPrompt").value.trim();
  const engine = document.getElementById("collectEngine").value;
  if (!raw) return toast("请填写目标快照", true);
  const snap = state.tree.snapshots.find(s => s.id === raw) ||
               state.tree.snapshots.find(s => s.label === raw);
  if (!snap) return toast(`快照不存在：${raw}（可输入 id 或从下拉选择）`, true);
  if (!prompt) return toast("请填写采集描述", true);
  const snapshot = snap.id;
  const out = document.getElementById("collectResult");
  out.hidden = false;
  out.textContent = "调用模型采集中…（超时默认 60s）";
  try {
    const d = await api("/api/collect", {
      method: "POST",
      body: JSON.stringify({ person: state.current, snapshot, prompt, collector: engine }),
    });
    let text = JSON.stringify(d, null, 2);
    if (d.errors && d.errors.length) text += "\n\n⚠ 以下字段写入失败：\n" +
      d.errors.map(e => `${e.path}: ${e.error}`).join("\n");
    out.textContent = text;
    if (Object.keys(d.applied).length) {
      toast(`已落库 ${Object.keys(d.applied).length} 项`);
      await selectPerson(state.current);
      await selectSnapshot(snapshot);
    } else if (!d.errors || !d.errors.length) {
      toast(d.note || "未抽取到字段");
    } else {
      toast("存在写入失败的字段，详见结果", true);
    }
  } catch (e) {
    out.textContent = "错误：" + e.message;
    toast(e.message, true);
  }
}

/* ---------- 模型配置 ---------- */

export async function loadConfig() {
  try {
    const cfg = await api("/api/config");
    document.getElementById("cfgBase").value = cfg.base_url || "";
    document.getElementById("cfgModel").value = cfg.model || "";
    document.getElementById("cfgKey").value = "";
    document.getElementById("cfgKey").placeholder = cfg.has_key
      ? `已保存（${cfg.api_key_masked}），留空不修改` : "sk-...";
    return cfg;
  } catch { return {}; }
}

export async function saveConfig() {
  const body = {
    base_url: document.getElementById("cfgBase").value.trim(),
    model: document.getElementById("cfgModel").value.trim(),
  };
  const key = document.getElementById("cfgKey").value.trim();
  if (key) body.api_key = key; // 不填则不传字段 = 保留已保存的 key
  if (!body.base_url || !body.model) return toast("Base URL 与模型名必填", true);
  try {
    const d = await api("/api/config", { method: "POST", body: JSON.stringify(body) });
    toast("模型配置已保存");
    document.getElementById("cfgKey").value = "";
    document.getElementById("cfgKey").placeholder = d.has_key
      ? `已保存（${d.api_key_masked}），留空不修改` : "sk-...";
  } catch (e) { toast(e.message, true); }
}
