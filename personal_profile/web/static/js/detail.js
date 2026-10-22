/* 详情面板：合并值展示（来源标注）+ 写值/删值/链接管理 */

import { state, LINK_STYLE } from "./state.js";
import { esc, fmtVal, displayLabel } from "./util.js";

export function renderDetail(d) {
  const panel = document.getElementById("detailPanel");
  if (!d) {
    panel.innerHTML = '<div class="empty">← 点击时间轴上的快照<br>查看该时间态的完整档案</div>';
    return;
  }
  state.lastTrace = d.trace; // 供"改"按钮预填当前值
  const s = d.snapshot;
  const groups = {};
  for (const [path, item] of Object.entries(d.trace)) {
    const g = path.split(".")[0];
    (groups[g] = groups[g] || []).push([path, item]);
  }
  const myLinks = d.links.filter(l => l.from === s.id || l.to === s.id);

  panel.innerHTML = `
    <div class="detail-head">
      <h2>${esc(s.label)}</h2>
      <span class="ts">${esc(s.timestamp)}</span>
      ${s.inherits_from ? '<span class="src inh">继承 ' + esc(s.inherits_from) + "</span>" : '<span class="src own">独立根态</span>'}
    </div>
    <div class="detail-sub">${esc(s.id)} · 合并 ${Object.keys(d.trace).length} 项（本态 ${Object.keys(s.overrides).length} 项覆盖）</div>
    ${Object.entries(groups).map(([g, items]) => `
      <div class="group-title">${esc(state.dimNames[g] || g)}</div>
      ${items.map(([path, item]) => {
        const own = item.source === s.id;
        const short = path.split(".").slice(1).join(".") || path;
        const label = displayLabel(path, item.leaf) === path ? short : displayLabel(path, item.leaf);
        return `<div class="val-row">
          <span class="val-path" title="${esc(path)}">${esc(label)}</span>
          <span class="val-data" title="${esc(path)} = ${esc(fmtVal(item.leaf.value))}">${esc(fmtVal(item.leaf.value))}</span>
          ${item.leaf.unit ? `<span class="val-unit">${esc(item.leaf.unit)}</span>` : ""}
          <span class="src ${own ? "own" : "inh"}" title="值来源快照">${own ? "本态" : "← " + esc(item.source)}</span>
          <span class="val-ops">
            <button class="btn mini" onclick="prefillForm('${esc(path)}')">改</button>
            ${own ? `<button class="btn mini danger" onclick="delValue('${esc(path)}')">删</button>` : ""}
          </span>
        </div>`;
      }).join("")}
    `).join("") || '<div class="empty">该时间态暂无任何值</div>'}
    ${myLinks.length ? `
      <div class="group-title">关联关系</div>
      <div class="links-in-detail">
        ${myLinks.map(l => {
          const attr = l.from_path && l.to_path
            ? `${l.from === s.id ? "本态." + displayLabel(l.from_path, (state.lastTrace || {})[l.from_path]?.leaf) : l.from + "." + l.from_path}`
              + ` → ${l.to === s.id ? "本态." + displayLabel(l.to_path, (state.lastTrace || {})[l.to_path]?.leaf) : l.to + "." + l.to_path}`
            : `${l.from} → ${l.to}`;
          return `
          <div class="link-chip">
            <span class="t" style="color:${(LINK_STYLE[l.type] || {}).color || "#333"}">${esc(l.type)}</span>
            <span class="n" title="${esc(l.from + "." + (l.from_path || "") + " → " + l.to + "." + (l.to_path || ""))}${l.note ? " · " + esc(l.note) : ""}">${esc(attr)}${l.note ? " · " + esc(l.note) : ""}</span>
            <button class="btn mini danger" onclick="delLink('${esc(l.link_id)}')">删</button>
          </div>`;
        }).join("")}
      </div>` : ""}
    <div class="group-title">写入值（copy-on-write，覆盖即编辑）</div>
    <div class="form-row">
      <label class="field">维度路径<input id="vPath" placeholder="physical.body_shape.height"></label>
      <label class="field">值（支持 JSON）<input id="vValue" placeholder='175 或 ["a","b"]'></label>
      <label class="field">单位<input id="vUnit" placeholder="cm（可选）"></label>
      <label class="field">展示名<input id="vName" placeholder="默认取模板名"></label>
    </div>
    <div class="form-actions"><button class="btn primary" onclick="submitValue()">保存到本态</button></div>
  `;
}

export function prefillForm(path) {
  const rows = state.lastTrace || {};
  const it = rows[path];
  document.getElementById("vPath").value = path;
  document.getElementById("vValue").value = it ? JSON.stringify(it.leaf.value) : "";
  document.getElementById("vUnit").value = it && it.leaf.unit ? it.leaf.unit : "";
  document.getElementById("vName").value = it && it.leaf.name && it.leaf.name !== path.split(".").pop()
    ? it.leaf.name : "";
  document.getElementById("vPath").focus();
}
