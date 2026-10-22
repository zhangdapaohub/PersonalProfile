/* 时间轴渲染：节点卡片 + SVG 连贯性连线 */

import { api } from "./api.js";
import { state, LINK_STYLE } from "./state.js";
import { esc, fmtVal, displayLabel, toast, sortByOrder } from "./util.js";
import { renderDetail, renderLinkDetail } from "./detail.js";
import { reorderSnapshot } from "./actions.js";

export function renderTimeline() {
  const tl = document.getElementById("timeline");
  const empty = document.getElementById("timelineEmpty");
  const tree = state.tree;
  document.getElementById("personTitle").textContent =
    tree.person ? `${tree.person.name} · 时间轴` : "时间轴";
  tl.innerHTML = "";
  empty.style.display = tree.snapshots.length ? "none" : "";

  /* 链接端点索引："sid|path" → 该端参与的第一条链接样式（属性行圆点用） */
  const endpointStyle = {};
  for (const lk of tree.continuity_links) {
    const st = LINK_STYLE[lk.type] || LINK_STYLE["继承"];
    if (lk.from_path && !(lk.from + "|" + lk.from_path in endpointStyle))
      endpointStyle[lk.from + "|" + lk.from_path] = st;
    if (lk.to_path && !(lk.to + "|" + lk.to_path in endpointStyle))
      endpointStyle[lk.to + "|" + lk.to_path] = st;
  }

  for (const s of tree.snapshots) {
    const el = document.createElement("div");
    const isBreak = !s.inherits_from && tree.snapshots.length > 1;
    el.className = "snap" + (s.inherits_from ? " inherits" : "") + (isBreak ? " brk" : "") + (s.id === state.selected ? " selected" : "");
    el.dataset.sid = s.id;

    /* 值预览：前 4 项 + 所有作为链接端点但未入选的属性（保证锚点可见） */
    const entries = Object.entries(s.resolved);
    const picked = new Map(entries.slice(0, 4));
    for (const [p, leaf] of entries) {
      if (s.id + "|" + p in endpointStyle) picked.set(p, leaf);
    }
    const vals = sortByOrder([...picked.entries()], s.order);
    const more = entries.length - vals.length;

    el.innerHTML = `
      <span class="snap-node" title="${s.inherits_from ? "继承态" : (isBreak ? "独立态" : "根态")}"></span>
      <span class="snap-connector"></span>
      <div class="snap-body">
        <div class="snap-head">
          <span class="ts">${esc(s.timestamp)}</span>
          <b>${esc(s.label)}</b>
          <button class="snap-del" title="重命名此时间态" onclick="event.stopPropagation(); renameSnapshot('${s.id}', '${esc(s.label).replace(/'/g, "\\'")}')">✎</button>
          ${s.inherits_from ? "" : '<span class="badge ' + (isBreak ? "brk" : "root") + '">' + (isBreak ? "独立态" : "根态") + "</span>"}
          <span class="badge">本态覆盖 ${s.own_overrides} 项</span>
          <button class="snap-del push" title="删除此时间态（含相关链接，继承链自动衔接）" onclick="event.stopPropagation(); deleteSnapshot('${s.id}')">✕</button>
        </div>
        <div class="snap-meta">${esc(s.id)}${s.inherits_from ? " · 继承自 " + esc(s.inherits_from) : ""} · 合并后 ${Object.keys(s.resolved).length} 项</div>
        <div class="mini-vals">
          ${vals.map(([p, leaf]) => {
            const st = endpointStyle[s.id + "|" + p];
            return `<span class="mini-val${st ? " linked" : ""}" data-path="${esc(p)}"${st ? ` style="--lc:${st.color}"` : ""}>${st ? '<i class="ldot"></i>' : ""}${esc(displayLabel(p, leaf))} = <b>${esc(fmtVal(leaf.value))}</b>${leaf.unit ? " " + esc(leaf.unit) : ""}</span>`;
          }).join("")}
          ${more > 0 ? `<span class="mini-more">…还有 ${more} 项，点击查看</span>` : ""}
        </div>
      </div>`;
    el.onclick = () => selectSnapshot(s.id);
    tl.appendChild(el);
    enableDrag(el, s.id);
  }
  requestAnimationFrame(drawLinks);
}

/* 卡项内属性值拖拽排序：拖动 .mini-val 调整顺序，松手后持久化到快照的 order */
function enableDrag(card, sid) {
  const items = () => [...card.querySelectorAll(".mini-val")];
  let dragEl = null;
  items().forEach(it => {
    it.setAttribute("draggable", "true");
    it.addEventListener("dragstart", (e) => {
      dragEl = it;
      e.stopPropagation();
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", it.dataset.path); } catch { /* 某些浏览器要求 */ }
    });
    it.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = "move";
    });
    it.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!dragEl || dragEl === it) return;
      const box = card.querySelector(".mini-vals");
      const rect = it.getBoundingClientRect();
      const after = (e.clientY - rect.top) > rect.height / 2;
      if (after) box.insertBefore(dragEl, it.nextSibling);
      else box.insertBefore(dragEl, it);
      dragEl = null;
      reorderSnapshot(sid, items().map(x => x.dataset.path));
    });
  });
}

export async function selectSnapshot(sid) {
  clearLinkSelection();
  state.selected = sid;
  document.querySelectorAll(".snap").forEach(el =>
    el.classList.toggle("selected", el.dataset.sid === sid));
  try {
    const d = await api(`/api/persons/${encodeURIComponent(state.current)}/snapshots/${encodeURIComponent(sid)}`);
    renderDetail(d);
  } catch (e) { toast(e.message, true); }
}

export function drawLinks() {
  const svg = document.getElementById("linkLayer");
  const wrap = document.getElementById("timelineWrap");
  const rw = wrap.getBoundingClientRect();
  svg.setAttribute("width", rw.width);
  svg.setAttribute("height", Math.max(rw.height, 1));
  svg.setAttribute("viewBox", `0 0 ${rw.width} ${Math.max(rw.height, 1)}`);
  while (svg.childNodes.length > 1) svg.removeChild(svg.lastChild); // 保留 defs

  const cards = {};
  wrap.querySelectorAll(".snap").forEach(el => (cards[el.dataset.sid] = el));

  /* 端点定位：优先取该快照内属性行（mini-val）的垂直中心，取不到回退卡片中心 */
  const anchor = (card, sid, path) => {
    const r = card.getBoundingClientRect();
    const row = path && card.querySelector(`.mini-val[data-path="${CSS.escape(path)}"]`);
    if (row) {
      const rr = row.getBoundingClientRect();
      return { x: r.right - rw.left - 1, y: rr.top - rw.top + rr.height / 2, ok: true };
    }
    return { x: r.right - rw.left - 4, y: r.top - rw.top + r.height / 2, ok: false };
  };

  state.tree.continuity_links.forEach((lk, i) => {
    const a = cards[lk.from], b = cards[lk.to];
    if (!a || !b) return;
    const p1 = anchor(a, lk.from, lk.from_path);
    const p2 = anchor(b, lk.to, lk.to_path);
    const bend = 46 + i * 18;
    const st = LINK_STYLE[lk.type] || LINK_STYLE["继承"];
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M ${p1.x} ${p1.y} C ${p1.x + bend} ${p1.y}, ${p2.x + bend} ${p2.y}, ${p2.x} ${p2.y}`);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", st.color);
    path.setAttribute("stroke-width", "2.2");
    if (st.dash) path.setAttribute("stroke-dasharray", st.dash);
    path.setAttribute("marker-end", `url(#${st.marker})`);
    path.setAttribute("opacity", "0.85");
    path.style.cursor = "pointer";
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `${lk.type}：${lk.from}${lk.from_path ? "." + lk.from_path : ""} → ${lk.to}${lk.to_path ? "." + lk.to_path : ""}${lk.note ? " · " + lk.note : ""}（点击查看详情）`;
    path.appendChild(title);
    svg.appendChild(path);

    /* 悬停连线：高亮两端属性行，直观看到"哪个属性连到哪个属性" */
    const endSel = (sid, p) =>
      p ? wrap.querySelector(`.snap[data-sid="${CSS.escape(sid)}"] .mini-val[data-path="${CSS.escape(p)}"]`) : null;
    path.addEventListener("mouseenter", () => {
      if (!path.classList.contains("link-sel")) path.setAttribute("stroke-width", "4");
      for (const el of [endSel(lk.from, lk.from_path), endSel(lk.to, lk.to_path)])
        if (el) el.classList.add("linked-hit");
    });
    path.addEventListener("mouseleave", () => {
      if (!path.classList.contains("link-sel")) path.setAttribute("stroke-width", "2.2");
      wrap.querySelectorAll(".mini-val.linked-hit").forEach(el => el.classList.remove("linked-hit"));
    });
    /* 点击连线：在右侧卡片显示链接详情，并持久高亮两端属性行 */
    path.addEventListener("click", () => {
      clearLinkSelection();
      path.classList.add("link-sel");
      for (const el of [endSel(lk.from, lk.from_path), endSel(lk.to, lk.to_path)])
        if (el) el.classList.add("linked-sel");
      renderLinkDetail(lk);
    });
  });
}

/* 清除连线选中态（点击快照或切换连线时调用） */
function clearLinkSelection() {
  document.querySelectorAll("#linkLayer path.link-sel").forEach(p => p.classList.remove("link-sel"));
  document.querySelectorAll(".mini-val.linked-sel").forEach(el => el.classList.remove("linked-sel"));
}
/* 供详情卡片"定位起点/终点"按钮调用（复用快照详情渲染） */
window.selectSnapshotFromLink = (sid) => selectSnapshot(sid);
