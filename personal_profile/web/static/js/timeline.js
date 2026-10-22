/* 时间轴渲染：节点卡片 + SVG 连贯性连线 */

import { api } from "./api.js";
import { state, LINK_STYLE } from "./state.js";
import { esc, fmtVal, displayLabel, toast } from "./util.js";
import { renderDetail } from "./detail.js";

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
    el.className = "snap" + (s.inherits_from ? " inherits" : "") + (s.id === state.selected ? " selected" : "");
    el.dataset.sid = s.id;

    /* 值预览：前 4 项 + 所有作为链接端点但未入选的属性（保证锚点可见） */
    const entries = Object.entries(s.resolved);
    const picked = new Map(entries.slice(0, 4));
    for (const [p, leaf] of entries) {
      if (s.id + "|" + p in endpointStyle) picked.set(p, leaf);
    }
    const vals = [...picked.entries()];
    const more = entries.length - vals.length;

    el.innerHTML = `
      <span class="dot"></span>
      <div class="snap-body">
        <div class="snap-head">
          <span class="ts">${esc(s.timestamp)}</span>
          <b>${esc(s.label)}</b>
          ${s.inherits_from ? "" : '<span class="badge ' + (isBreak ? "brk" : "root") + '">' + (isBreak ? "独立态" : "根态") + "</span>"}
          <span class="badge">本态覆盖 ${s.own_overrides} 项</span>
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
  }
  requestAnimationFrame(drawLinks);
}

export async function selectSnapshot(sid) {
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
    const attrLabel = lk.from_path && lk.to_path
      ? `${shortPath(lk.from_path)} → ${shortPath(lk.to_path)}` : "";
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `${lk.type}：${lk.from}${lk.from_path ? "." + lk.from_path : ""} → ${lk.to}${lk.to_path ? "." + lk.to_path : ""}${lk.note ? " · " + lk.note : ""}`;
    path.appendChild(title);
    svg.appendChild(path);

    /* 悬停连线：高亮两端属性行，直观看到"哪个属性连到哪个属性" */
    const endSel = (sid, p) =>
      p ? wrap.querySelector(`.snap[data-sid="${CSS.escape(sid)}"] .mini-val[data-path="${CSS.escape(p)}"]`) : null;
    path.addEventListener("mouseenter", () => {
      path.setAttribute("stroke-width", "4");
      for (const el of [endSel(lk.from, lk.from_path), endSel(lk.to, lk.to_path)])
        if (el) el.classList.add("linked-hit");
    });
    path.addEventListener("mouseleave", () => {
      path.setAttribute("stroke-width", "2.2");
      wrap.querySelectorAll(".mini-val.linked-hit").forEach(el => el.classList.remove("linked-hit"));
    });

    if (attrLabel) {
      // 连线中点标注属性（贝塞尔中点近似取 t=0.5）
      const mx = (p1.x + 3 * (p1.x + bend) + 3 * (p2.x + bend) + p2.x) / 8;
      const my = (p1.y + 3 * p1.y + 3 * p2.y + p2.y) / 8;
      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("x", mx);
      text.setAttribute("y", my - 5);
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("font-size", "10.5");
      text.setAttribute("fill", st.color);
      text.setAttribute("opacity", "0.9");
      text.setAttribute("style", "paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round;");
      text.textContent = attrLabel;
      svg.appendChild(text);
    }
  });
}

/* 属性短标签：取维度路径末两级，避免连线标注过长 */
function shortPath(p) {
  const segs = p.split(".");
  return segs.slice(-2).join(".");
}
