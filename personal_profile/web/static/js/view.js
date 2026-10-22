/* 人物与快照选择：加载视图数据并触发渲染 */

import { api } from "./api.js";
import { state } from "./state.js";
import { toast } from "./util.js";
import { renderTimeline } from "./timeline.js";
import { renderDetail } from "./detail.js";

export function renderTabs() {
  const nav = document.getElementById("personTabs");
  nav.innerHTML = "";
  for (const p of state.persons) {
    const wrap = document.createElement("div");
    wrap.className = "tab-wrap" + (p.identity_id === state.current ? " active" : "");

    const b = document.createElement("button");
    b.className = "tab";
    b.textContent = p.name;
    b.title = p.identity_id;
    b.onclick = () => selectPerson(p.identity_id);

    const ren = document.createElement("button");
    ren.className = "tab-act";
    ren.textContent = "✎";
    ren.title = "重命名人物";
    ren.onclick = (e) => { e.stopPropagation(); window.renamePerson(p.identity_id, p.name); };

    const del = document.createElement("button");
    del.className = "tab-act del";
    del.textContent = "✕";
    del.title = "删除人物（含全部快照与链接）";
    del.onclick = (e) => { e.stopPropagation(); window.deletePerson(p.identity_id, p.name); };

    const exp = document.createElement("button");
    exp.className = "tab-act";
    exp.textContent = "⤓";
    exp.title = "导出该人物为 JSON";
    exp.onclick = (e) => { e.stopPropagation(); window.exportPerson(p.identity_id, p.name); };

    wrap.appendChild(b);
    wrap.appendChild(exp);
    wrap.appendChild(ren);
    wrap.appendChild(del);
    nav.appendChild(wrap);
  }
}

export async function loadPersons() {
  const d = await api("/api/persons");
  state.persons = d.persons;
  renderTabs();
  if (!state.current && state.persons.length) {
    selectPerson(state.persons[0].identity_id);
  } else if (!state.persons.length) {
    renderTabs();
  }
}

export async function selectPerson(pid) {
  state.current = pid;
  state.selected = null;
  renderTabs();
  try {
    state.tree = await api("/api/persons/" + encodeURIComponent(pid));
    renderTimeline();
    renderDetail(null);
  } catch (e) { toast(e.message, true); }
}
