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

/* ---------- 人物重命名 / 删除 ---------- */

export async function renamePerson(pid, oldName) {
  const name = prompt("重命名人物为：", oldName || "");
  if (name === null) return;            // 取消
  const n = name.trim();
  if (!n) return toast("名称不能为空", true);
  try {
    await api("/api/persons/" + encodeURIComponent(pid), {
      method: "PUT",
      body: JSON.stringify({ name: n }),
    });
    toast("已重命名为：" + n);
    await loadPersons();
  } catch (e) { toast(e.message, true); }
}

export async function deletePerson(pid, name) {
  if (!confirm(`确认删除人物「${name}」及其全部快照与链接？此操作不可恢复。`)) return;
  try {
    await api("/api/persons/" + encodeURIComponent(pid), { method: "DELETE" });
    toast("已删除：" + name);
    state.current = null;
    await loadPersons();
  } catch (e) { toast(e.message, true); }
}

/* ---------- 快照 ---------- */

export async function renameSnapshot(sid, oldLabel) {
  const label = prompt("重命名时间态为：", oldLabel || "");
  if (label === null) return;           // 取消
  const n = label.trim();
  if (!n) return toast("标签不能为空", true);
  try {
    await api(`/api/persons/${encodeURIComponent(state.current)}/snapshots/${encodeURIComponent(sid)}`, {
      method: "PUT",
      body: JSON.stringify({ label: n }),
    });
    toast("已重命名为：" + n);
    await selectPerson(state.current);
    if (state.selected === sid) await selectSnapshot(sid);
  } catch (e) { toast(e.message, true); }
}

export async function submitSnapshot() {
  const timestamp = document.getElementById("snapTs").value;
  const label = document.getElementById("snapLabel").value.trim();
  if (!timestamp || !label) return toast("请填写时间与标签", true);
  const sel = document.getElementById("snapInherits").value;
  let inherits_from = null, break_chain = false;
  if (sel === "__root__") break_chain = true;       // 显式独立根态
  else if (sel) inherits_from = sel;                 // 显式指定父态
  // 否则（""）= 默认自动继承上一个
  try {
    await api("/api/snapshots", {
      method: "POST",
      body: JSON.stringify({ person: state.current, timestamp, label, inherits_from, break_chain }),
    });
    closeModal("snapshotModal");
    toast("快照已创建：" + label);
    await selectPerson(state.current);
    state.selected = null;
  } catch (e) { toast(e.message, true); }
}

/* ---------- 快照删除 ---------- */

export async function deleteSnapshot(sid) {
  const label = state.tree.snapshots.find(s => s.id === sid)?.label || sid;
  if (!confirm(`确认删除时间态「${label}」(${sid}) 及其相关链接？\n继承链将自动衔接，此操作不可恢复。`)) return;
  try {
    await api(`/api/persons/${encodeURIComponent(state.current)}/snapshots/${encodeURIComponent(sid)}`, {
      method: "DELETE",
    });
    toast("已删除：" + label);
    if (state.selected === sid) state.selected = null;
    await selectPerson(state.current);
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
  const sid = state.selected;  // 先捕获，selectPerson 会把它置 null
  const path = document.getElementById("vPath").value.trim();
  const raw = document.getElementById("vValue").value;
  const unit = document.getElementById("vUnit").value.trim() || null;
  const name = document.getElementById("vName").value.trim() || null;
  if (!path || !raw) return toast("请填写路径与值", true);
  if (!sid) return toast("请先在时间轴上选择一个时间态", true);
  try {
    await api("/api/value", {
      method: "POST",
      body: JSON.stringify({
        person: state.current, snapshot: sid,
        path, value: parseValue(raw), unit, name,
      }),
    });
    toast("已写入：" + path);
    await selectPerson(state.current);
    await selectSnapshot(sid);
  } catch (e) { toast(e.message, true); }
}

export async function delValue(path) {
  const sid = state.selected;  // 先捕获，selectPerson 会把它置 null
  if (!sid) return toast("请先在时间轴上选择一个时间态", true);
  try {
    await api("/api/value", {
      method: "DELETE",
      body: JSON.stringify({ person: state.current, snapshot: sid, path }),
    });
    toast("已删除本态覆盖：" + path);
    await selectPerson(state.current);
    await selectSnapshot(sid);
  } catch (e) { toast(e.message, true); }
}

/* ---------- 属性级断裂（中断继承） ---------- */

export async function setBreak(path, on) {
  const sid = state.selected;  // 先捕获，selectPerson 会把它置 null
  if (!sid) return toast("请先在时间轴上选择一个时间态", true);
  try {
    await api("/api/break", {
      method: "POST",
      body: JSON.stringify({ person: state.current, snapshot: sid, path, on }),
    });
    toast(on ? `已断裂：${path}（后续卡项不再继承）` : `已恢复继承：${path}`);
    await selectPerson(state.current);
    await selectSnapshot(sid);
  } catch (e) { toast(e.message, true); }
}

/* ---------- 卡项内属性值展示排序 ---------- */

export async function reorderSnapshot(sid, order) {
  try {
    await api("/api/order", {
      method: "POST",
      body: JSON.stringify({ person: state.current, snapshot: sid, order }),
    });
    const snap = state.tree.snapshots.find(s => s.id === sid);
    if (snap) snap.order = order;  // 本地同步，避免整树重渲染
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

/* ---------- 人物导入 / 导出 ---------- */

export async function exportPerson(pid, name) {
  const id = pid || state.current;
  if (!id) return toast("请先选择要导出的人物", true);
  const persona = state.persons.find(p => p.identity_id === id);
  const fname = (name || persona?.name || id) + ".json";
  try {
    const d = await api("/api/persons/" + encodeURIComponent(id) + "/export");
    const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast("已导出：" + fname);
  } catch (e) { toast(e.message, true); }
}

export async function importPersonFile(file) {
  if (!file) return;
  try {
    const text = await file.text();
    const data = JSON.parse(text);
    const d = await api("/api/persons/import", {
      method: "POST",
      body: JSON.stringify(data),
    });
    toast("已导入：" + d.name + (d.renamed ? "（重映射）" : ""));
    await loadPersons();
    selectPerson(d.identity_id);
  } catch (e) {
    toast("导入失败：" + e.message, true);
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
