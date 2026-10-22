/* 通用工具：转义 / 格式化 / toast */

export function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function parseValue(raw) {
  try { return JSON.parse(raw); } catch { return raw; }
}

export function fmtVal(v) {
  if (Array.isArray(v)) return v.join("、");
  return String(v);
}

let toastTimer = null;
export function toast(msg, isErr = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast" + (isErr ? " err" : "");
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 2600);
}

/* 弹窗开关（HTML hidden + CSS .modal-mask[hidden]） */
export function openModal(id) { document.getElementById(id).hidden = false; }
export function closeModal(id) { document.getElementById(id).hidden = true; }

/* 展示名优先：leaf.name 存在且不是 path 末段兜底值时使用，否则退回路径形式 */
export function displayLabel(path, leaf) {
  const lastSeg = path.split(".").pop();
  return leaf && leaf.name && leaf.name !== lastSeg ? leaf.name : path;
}
