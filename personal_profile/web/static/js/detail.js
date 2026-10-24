/* 详情面板：合并值展示（多层树状分组 + 拖动排序）+ 写值/删值/链接管理 */

import { api } from "./api.js";
import { state, LINK_STYLE } from "./state.js";
import { esc, fmtVal, displayLabel, toast } from "./util.js";
import { selectSnapshot } from "./timeline.js";

/* ---------- 维度模板解析：按段取每层中文名 ---------- */

function tmplAt(segments) {
  let node = { children: state.schema };
  for (const seg of segments) {
    if (!node || !node.children) return null;
    node = node.children[seg] || null;
  }
  return node;
}

/* ---------- 多层树构建：path 拆段 → 嵌套节点；按快照 order 排序 ---------- */

function buildTree(trace, order) {
  const idx = new Map((order || []).map((p, i) => [p, i]));
  const keyOf = p => (idx.has(p) ? idx.get(p) : Number.MAX_SAFE_INTEGER);

  const root = { segs: [], children: new Map(), leaves: [] };
  for (const [path, item] of Object.entries(trace)) {
    const segs = path.split(".");
    let cur = root;
    for (let i = 0; i < segs.length - 1; i++) {
      if (!cur.children.has(segs[i])) {
        cur.children.set(segs[i], { segs: segs.slice(0, i + 1), children: new Map(), leaves: [] });
      }
      cur = cur.children.get(segs[i]);
    }
    cur.leaves.push([path, item]);
  }
  /* 排序：叶子按 order 位置；分组按其子树最小叶子位置（保持拖动后的相对顺序） */
  const sortNode = n => {
    n.leaves.sort((a, b) => keyOf(a[0]) - keyOf(b[0]));
    for (const c of n.children.values()) {
      sortNode(c);
      c.orderKey = Math.min(
        c.leaves.length ? keyOf(c.leaves[0][0]) : Infinity,
        ...[...c.children.values()].map(x => x.orderKey),
      );
    }
    n.children = new Map([...n.children.entries()]
      .sort((a, b) => a[1].orderKey - b[1].orderKey));
  };
  sortNode(root);
  return root;
}

const countLeaves = n =>
  n.leaves.length + [...n.children.values()].reduce((s, c) => s + countLeaves(c), 0);

/* 子树内本态覆盖的叶子数：为 0 说明整个节点全是继承值，不该出现删除节点按钮 */
const countOwn = (n, sid) =>
  n.leaves.filter(([, it]) => it.source === sid).length +
  [...n.children.values()].reduce((s, c) => s + countOwn(c, sid), 0);

/* ---------- 行渲染 ---------- */

function leafRow(path, item, sid) {
  const own = item.source === sid;
  const short = path.split(".").slice(1).join(".") || path;
  const label = displayLabel(path, item.leaf) === path ? short : displayLabel(path, item.leaf);
  return `<div class="val-row" draggable="true" data-path="${esc(path)}">
    <span class="drag-handle" title="拖动排序">⋮⋮</span>
    <span class="val-path" title="${esc(path)}">${esc(label)}</span>
    <span class="val-data" title="${esc(path)} = ${esc(fmtVal(item.leaf.value))}">${esc(fmtVal(item.leaf.value))}</span>
    ${item.leaf.unit ? `<span class="val-unit">${esc(item.leaf.unit)}</span>` : ""}
    <span class="src ${own ? "own" : "inh"}" title="值来源快照">${own ? "本态" : "← " + esc(item.source)}</span>
    <span class="val-ops">
      ${own ? `<button class="btn mini" onclick="prefillForm('${esc(path)}')">改</button>
      <button class="btn mini danger" onclick="delValue('${esc(path)}')">删</button>` : ""}
      <button class="btn mini warn" title="断裂：本快照仍显示该值，下一个快照起不再继承显示" onclick="setBreak('${esc(path)}', true)">断</button>
    </span>
  </div>`;
}

function renderGroup(node, sid) {
  const t = tmplAt(node.segs);
  const name = (t && t.name) || node.segs[node.segs.length - 1];
  const prefix = node.segs.join(".");
  const ownLeaves = countOwn(node, sid);
  return `<details open class="tree-group">
    <summary class="tree-title">${esc(name)} <span class="tree-cnt">${countLeaves(node)}</span>
      ${ownLeaves ? `<button class="btn mini danger node-del" title="删除整个节点（该子树全部本态覆盖；继承项不删）"
        onclick="event.preventDefault(); event.stopPropagation(); delNode('${esc(prefix)}')">🗑</button>` : ""}
    </summary>
    <div class="tree-body">
      ${[...node.children.values()].map(c => renderGroup(c, sid)).join("")}
      ${node.leaves.map(([p, it]) => leafRow(p, it, sid)).join("")}
    </div>
  </details>`;
}

/* ---------- 主渲染 ---------- */

export function renderDetail(d) {
  const panel = document.getElementById("detailPanel");
  if (!d) {
    panel.innerHTML = '<div class="empty">← 点击时间轴上的快照<br>查看该时间态的完整档案</div>';
    return;
  }
  state.lastTrace = d.trace; // 供"改"按钮预填当前值
  const s = d.snapshot;
  const myLinks = d.links.filter(l => l.from === s.id || l.to === s.id);

  const root = buildTree(d.trace, s.order);
  const treeHtml = root.children.size || root.leaves.length ? `
    ${[...root.children.values()].map(c => renderGroup(c, s.id)).join("")}
    ${root.leaves.map(([p, it]) => leafRow(p, it, s.id)).join("")}
  ` : '<div class="empty">该时间态暂无任何值</div>';

  panel.innerHTML = `
    <div class="detail-head">
      <h2>${esc(s.label)}</h2>
      <span class="ts">${esc(s.timestamp)}</span>
      ${s.inherits_from ? '<span class="src inh">继承 ' + esc(s.inherits_from) + "</span>" : '<span class="src own">独立根态</span>'}
    </div>
    <div class="detail-sub">${esc(s.id)} · 合并 ${Object.keys(d.trace).length} 项（本态 ${Object.keys(s.overrides).length} 项覆盖） · 拖动 ⋮⋮ 可排序</div>
    <div id="treeWrap">${treeHtml}</div>
    ${s.broken && s.broken.length ? `
      <div class="group-title">已断裂（下一个快照起不再继承）</div>
      <div class="break-list">
        ${s.broken.map(p => `
          <div class="val-row">
            <span class="val-path" title="${esc(p)}">${esc(p)}</span>
            <span class="src brk">断裂</span>
            <span class="val-ops">
              <button class="btn mini" onclick="setBreak('${esc(p)}', false)">恢复</button>
            </span>
          </div>`).join("")}
      </div>` : ""}
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
      <label class="field">维度路径<input id="vPath" placeholder="inbody.composition.weight"></label>
      <label class="field">值（支持 JSON）<input id="vValue" placeholder='175 或 ["a","b"]'></label>
      <label class="field">单位<input id="vUnit" placeholder="cm（可选）"></label>
      <label class="field">展示名<input id="vName" placeholder="默认取模板名"></label>
    </div>
    <div class="form-actions"><button class="btn primary" onclick="submitValue()">保存到本态</button></div>
  `;

  enableRowDrag(panel, s.id);
  enableHoverCard(panel, d.trace, s.id);
}

/* ---------- 整节点删除：prefix 及全部子路径的本态覆盖（继承项跳过） ---------- */

export async function delNode(prefix) {
  const sid = state.selected;
  if (!sid) return toast("请先选择时间态", true);
  const trace = state.lastTrace || {};
  const total = Object.keys(trace).filter(p => p === prefix || p.startsWith(prefix + ".")).length;
  const own = Object.keys(trace).filter(p =>
    (p === prefix || p.startsWith(prefix + ".")) && trace[p].source === sid).length;
  if (!total) return toast("该节点下没有值", true);
  const msg = own > 0
    ? `删除节点「${prefix}」下共 ${total} 项？\n其中本态覆盖 ${own} 项将被删除；继承项 ${total - own} 项不受影响。`
    : `节点「${prefix}」下 ${total} 项全部为继承值，删除操作不会移除任何数据。\n仍要继续吗？`;
  if (!confirm(msg)) return;
  try {
    const r = await api("/api/node", {
      method: "DELETE",
      body: JSON.stringify({ person: state.current, snapshot: sid, prefix }),
    });
    toast(`已删除 ${r.removed} 项`);
    await selectSnapshot(sid);
  } catch (e) { toast(e.message, true); }
}

/* ---------- 悬浮卡片：鼠标悬停显示指标完整信息（路径过长截断时的兜底） ---------- */

function enableHoverCard(panel, trace, sid) {
  const card = document.getElementById("hoverCard");
  if (!card) return;
  const snapLabel = id => {
    const s = state.tree && state.tree.snapshots.find(x => x.id === id);
    return s ? `${s.label} (${id})` : id;
  };
  const show = (row, e) => {
    const path = row.dataset.path;
    const item = trace[path];
    if (!item) return;
    const leaf = item.leaf || {};
    const own = item.source === sid;
    card.innerHTML = `
      <div class="hc-name">${esc(leaf.name || path.split(".").pop())}</div>
      <div class="hc-row"><span>路径</span><b>${esc(path)}</b></div>
      <div class="hc-row"><span>值</span><b>${esc(fmtVal(leaf.value))}${leaf.unit ? " " + esc(leaf.unit) : ""}</b></div>
      ${leaf.name ? `<div class="hc-row"><span>展示名</span><b>${esc(leaf.name)}</b></div>` : ""}
      <div class="hc-row"><span>来源</span><b>${own ? "本态覆盖" : "← 继承自 " + esc(snapLabel(item.source))}</b></div>
    `;
    card.hidden = false;
    move(e);
  };
  const move = e => {
    const pad = 14, w = card.offsetWidth, h = card.offsetHeight;
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + w > window.innerWidth - 8) x = e.clientX - w - pad;
    if (y + h > window.innerHeight - 8) y = e.clientY - h - pad;
    card.style.left = Math.max(8, x) + "px";
    card.style.top = Math.max(8, y) + "px";
  };
  const hide = () => { card.hidden = true; };
  panel.querySelectorAll(".val-row[data-path]").forEach(row => {
    row.addEventListener("mouseenter", e => show(row, e));
    row.addEventListener("mousemove", move);
    row.addEventListener("mouseleave", hide);
  });
}

/* ---------- 详情行拖动排序：同组内拖动，落点后按全面板 DFS 顺序持久化 order ---------- */

function enableRowDrag(panel, sid) {
  const rows = () => [...panel.querySelectorAll(".tree-body .val-row[data-path]")];
  let dragEl = null;
  rows().forEach(row => {
    row.addEventListener("dragstart", e => {
      dragEl = row;
      row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", row.dataset.path); } catch { /* 某些浏览器要求 */ }
    });
    row.addEventListener("dragend", () => {
      row.classList.remove("dragging");
      dragEl = null;
    });
    row.addEventListener("dragover", e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
    });
    row.addEventListener("drop", e => {
      e.preventDefault();
      if (!dragEl || dragEl === row) return;
      const parent = row.parentElement;
      const rect = row.getBoundingClientRect();
      const after = (e.clientY - rect.top) > rect.height / 2;
      if (after) parent.insertBefore(dragEl, row.nextSibling);
      else parent.insertBefore(dragEl, row);
      dragEl = null;
      applyOrder(sid, rows().map(el => el.dataset.path));
    });
  });
}

async function applyOrder(sid, order) {
  try {
    await api("/api/order", {
      method: "POST",
      body: JSON.stringify({ person: state.current, snapshot: sid, order }),
    });
    toast("已排序");
    await selectSnapshot(sid); // 重取详情（带新 order）重渲染
  } catch (e) { toast(e.message, true); }
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

/* 点击时间轴连线后在右侧卡片展示链接详情（属性级：从某态某属性 → 另一态某属性） */
export function renderLinkDetail(lk) {
  const panel = document.getElementById("detailPanel");
  const st = LINK_STYLE[lk.type] || LINK_STYLE["继承"];
  const snapFrom = state.tree.snapshots.find(s => s.id === lk.from);
  const snapTo = state.tree.snapshots.find(s => s.id === lk.to);
  const fromLeaf = lk.from_path && snapFrom ? snapFrom.resolved[lk.from_path] : null;
  const toLeaf = lk.to_path && snapTo ? snapTo.resolved[lk.to_path] : null;

  const attrRow = (snap, path, leaf) => {
    if (!path)
      return `<div class="val-row muted"><span class="val-path">快照级链接（无具体属性）</span></div>`;
    return `<div class="val-row">
      <span class="val-path" title="${esc(path)}">${esc(displayLabel(path, leaf))}</span>
      <span class="val-data" title="${esc(path)} = ${leaf ? esc(fmtVal(leaf.value)) : ""}">${leaf ? esc(fmtVal(leaf.value)) : "—"}</span>
      ${leaf && leaf.unit ? `<span class="val-unit">${esc(leaf.unit)}</span>` : ""}
      <span class="src inh" title="来源快照">${esc(snap ? snap.label : "")}</span>
    </div>`;
  };

  panel.innerHTML = `
    <div class="detail-head">
      <h2>连贯性链接</h2>
      <span class="src inh" style="color:${st.color}">${esc(lk.type)}</span>
    </div>
    <div class="detail-sub">从「${esc(snapFrom ? snapFrom.label : lk.from)}」的属性指向「${esc(snapTo ? snapTo.label : lk.to)}」的属性</div>

    <div class="group-title">起点属性</div>
    ${attrRow(snapFrom, lk.from_path, fromLeaf)}

    <div class="link-mid" style="color:${st.color}">↓ ${esc(lk.type)}</div>

    <div class="group-title">终点属性</div>
    ${attrRow(snapTo, lk.to_path, toLeaf)}

    ${lk.note ? `<div class="group-title">说明</div><div class="link-note">${esc(lk.note)}</div>` : ""}

    <div class="form-actions">
      <button class="btn" onclick="selectSnapshotFromLink('${esc(lk.from)}')">定位起点</button>
      <button class="btn" onclick="selectSnapshotFromLink('${esc(lk.to)}')">定位终点</button>
      ${lk.link_id ? `<button class="btn danger" onclick="delLink('${esc(lk.link_id)}')">删除此链接</button>` : ""}
    </div>
  `;
}
