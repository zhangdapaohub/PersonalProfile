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
    const b = document.createElement("button");
    b.className = "tab" + (p.identity_id === state.current ? " active" : "");
    b.textContent = p.name;
    b.title = p.identity_id;
    b.onclick = () => selectPerson(p.identity_id);
    nav.appendChild(b);
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
