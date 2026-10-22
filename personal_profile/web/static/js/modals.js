/* 模态弹窗动态填充（打开前灌入当前人物的快照/配置数据） */

import { state } from "./state.js";
import { toast, openModal, esc } from "./util.js";
import { loadConfig } from "./actions.js";

export function openSnapshotModal() {
  if (!state.current) return toast("请先选择人物", true);
  const sel = document.getElementById("snapInherits");
  sel.innerHTML = '<option value="">自动继承上一个（推荐）</option>' +
    '<option value="__root__">独立根态（不继承）</option>' +
    state.tree.snapshots.map(s =>
      `<option value="${esc(s.id)}">${esc(s.label)}（${esc(s.id)}）</option>`).join("");
  document.getElementById("snapTs").value = new Date().toISOString().slice(0, 10);
  openModal("snapshotModal");
}

/* 按快照填充属性路径 datalist（该快照合并视图中的全部维度路径） */
function fillPathDatalist(datalistId, sid) {
  const dl = document.getElementById(datalistId);
  const snap = state.tree.snapshots.find(s => s.id === sid);
  dl.innerHTML = snap
    ? Object.keys(snap.resolved).map(p => `<option value="${esc(p)}">`).join("")
    : "";
}

export function openLinkModal() {
  if (!state.current) return toast("请先选择人物", true);
  if (!state.tree.snapshots.length) return toast("请先创建快照", true);
  const opts = state.tree.snapshots.map(s =>
    `<option value="${esc(s.id)}">${esc(s.timestamp)} · ${esc(s.label)}</option>`).join("");
  document.getElementById("linkFrom").innerHTML = opts;
  document.getElementById("linkTo").innerHTML = opts;
  // 属性 datalist 随快照选择联动
  fillPathDatalist("linkFromPaths", state.tree.snapshots[0].id);
  fillPathDatalist("linkToPaths", state.tree.snapshots[0].id);
  document.getElementById("linkFrom").onchange = e => fillPathDatalist("linkFromPaths", e.target.value);
  document.getElementById("linkTo").onchange = e => fillPathDatalist("linkToPaths", e.target.value);
  document.getElementById("linkFromPath").value = "";
  document.getElementById("linkToPath").value = "";
  // 默认勾选：继承/因果链接需要目标快照继承自起点
  document.getElementById("linkAutoInherit").checked = true;
  openModal("linkModal");
}

export function openCollectModal() {
  if (!state.current) return toast("请先选择人物", true);
  const dl = document.getElementById("collectSnapList");
  dl.innerHTML = state.tree.snapshots.map(s =>
    `<option value="${esc(s.id)}">${esc(s.timestamp)} · ${esc(s.label)}</option>`).join("");
  document.getElementById("collectResult").hidden = true;
  openModal("collectModal");
  loadConfig().then(cfg => {
    // 已配置模型则默认选 openai-compatible，否则默认 stub
    const engine = document.getElementById("collectEngine");
    const ready = cfg.base_url && cfg.model;
    engine.value = (ready && !engine.value) || ready ? "openai-compatible" : engine.value;
  });
}
