/* 提问库独立前端（与展示页 JS 模块完全隔离，不 import 任何展示模块）。
   数据流：GET /api/qbank/tree → 渲染领域进度与当前题 → POST /api/qbank/answer。 */

const $ = (id) => document.getElementById(id);

const state = {
  person: null,
  snapshot: null,
  persons: [],
  snapshots: [],
  tree: null,       // /api/qbank/tree 响应
  flat: [],         // 展平的题目（引用 tree 内 metric 对象，附 domain/dimension 名）
  cur: 0,
  draft: null,      // 当前题的未提交输入（rating/select 需要）
};

/* ---------- 基础工具 ---------- */

async function api(url, opts) {
  const r = await fetch(url, {
    headers: { "Content-Type": "application/json" }, ...opts,
    body: opts?.body ? JSON.stringify(opts.body) : undefined,
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}

function toast(msg, err = false) {
  const t = $("qbToast");
  t.textContent = msg;
  t.className = "qb-toast" + (err ? " err" : "");
  t.hidden = false;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.hidden = true; }, 2600);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------- 数据加载 ---------- */

async function boot() {
  const u = new URL(location.href);
  state.person = u.searchParams.get("person");

  const { persons } = await api("/api/persons");
  state.persons = persons;
  const sel = $("qbPerson");
  sel.innerHTML = persons.map(p =>
    `<option value="${esc(p.identity_id)}">${esc(p.name)}（${p.snapshot_count} 态）</option>`).join("");
  if (!state.person && persons.length) state.person = persons[0].identity_id;
  if (state.person) sel.value = state.person;
  sel.onchange = () => { state.person = sel.value; state.snapshot = null; loadSnapshots(); };

  await loadSnapshots();
}

async function loadSnapshots() {
  if (!state.person) return;
  const u = new URL(location.href);
  state.snapshot = u.searchParams.get("snapshot");
  const tree = await api(`/api/persons/${state.person}`);
  state.snapshots = tree.snapshots || [];
  const sel = $("qbSnapshot");
  sel.innerHTML = state.snapshots.map(s =>
    `<option value="${esc(s.id)}">${esc(s.timestamp)} · ${esc(s.label)}</option>`).join("")
    + `<option value="__new__">➕ 新建时间态采集</option>`;
  if (!state.snapshot && state.snapshots.length) state.snapshot = state.snapshots.at(-1).id;
  if (state.snapshot) sel.value = state.snapshot;
  sel.onchange = () => {
    state.snapshot = sel.value === "__new__" ? null : sel.value;
    loadTree();
  };
  await loadTree();
}

async function loadTree() {
  if (!state.person || !state.snapshot) {
    $("qbMeta").textContent = "请选择人物与时间态";
    return;
  }
  state.tree = await api(`/api/qbank/tree?person=${state.person}&snapshot=${state.snapshot}`);
  $("qbMeta").textContent = `${state.tree.label || ""} · v${state.tree.version || "?"}`;

  // 展平题目
  state.flat = [];
  for (const dom of state.tree.domains) {
    for (const dim of dom.dimensions) {
      for (const m of dim.metrics) {
        state.flat.push({ ...m, domain_key: dom.key, domain_name: dom.name,
                          dimension_name: dim.name });
      }
    }
  }
  render();
}

/* ---------- 渲染 ---------- */

function render() {
  renderProgress();
  renderDomains();
  renderQuestion();
}

function renderProgress() {
  const p = state.tree.progress;
  $("qbProgressFill").style.width = p.pct + "%";
  $("qbProgressText").textContent = `已答 ${p.answered} / ${p.total}（${p.pct}%）`;
}

function renderDomains() {
  const box = $("qbDomains");
  const firstUn = state.flat[state.cur]?.domain_key;
  box.innerHTML = state.tree.progress.domains.map(d => `
    <div class="qb-dom ${d.key === firstUn ? "act" : ""} ${d.pct === 100 ? "done" : ""}"
         data-dom="${esc(d.key)}">
      <div class="qb-dom-head"><span>${esc(d.name)}</span>
        <span class="qb-dom-pct">${d.answered}/${d.total}</span></div>
      <div class="qb-dom-bar"><div class="qb-dom-fill" style="width:${d.pct}%"></div></div>
    </div>`).join("");
  box.querySelectorAll(".qb-dom").forEach(el => {
    el.onclick = () => {
      const i = state.flat.findIndex(m => m.domain_key === el.dataset.dom);
      if (i >= 0) { state.cur = i; render(); }
    };
  });
}

function fmtVal(leaf) {
  if (!leaf) return "";
  const v = leaf.value;
  const unit = leaf.unit ? " " + leaf.unit : "";
  if (typeof v === "string" && v.length > 60) return esc(v.slice(0, 60)) + "…" + unit;
  return esc(v) + unit;
}

function renderQuestion() {
  if (state.cur < 0) state.cur = 0;
  if (state.cur >= state.flat.length) { renderFinish(); return; }
  const m = state.flat[state.cur];
  state.draft = null;

  const badges = [
    `<span class="qb-badge">${esc(m.type === "fact" ? "事实" : m.type === "story" ? "叙述" : "评价")}</span>`,
    m.volatile ? `<span class="qb-badge vol" title="时间敏感：建议新建时间态采集">随时间变化</span>` : "",
    m.perspective === "other" ? `<span class="qb-badge other">他评视角</span>` : "",
    m.answered ? `<span class="qb-badge done">已答</span>` : "",
  ].join("");

  $("qbCrumb").innerHTML =
    `${esc(m.domain_name)} › ${esc(m.dimension_name)} ${badges}`;
  $("qbQuestion").textContent = m.q?.text || m.name;
  $("qbHints").innerHTML = (m.q?.probe || []).map(p => `<span>${esc(p)}</span>`).join("");

  renderInput(m);

  const cur = m.current;
  $("qbCurrent").className = "qb-current" + (cur ? " show" : "");
  $("qbCurrent").innerHTML = cur
    ? `当前值：<b>${fmtVal(cur)}</b>${m.unit && typeof cur.value !== "string" ? " " + esc(m.unit) : ""}（再次提交将覆盖本态）`
    : "该指标在当前时间态还没有值。";
  $("qbClear").hidden = !cur;

  $("qbPrev").disabled = state.cur === 0;
}

function renderInput(m) {
  const box = $("qbInputArea");
  const cur = m.current?.value;

  if (m.input === "textarea") {
    box.innerHTML = `<textarea id="qbVal" placeholder="写下你的回答…">${esc(cur ?? "")}</textarea>`;
  } else if (m.input === "number") {
    box.innerHTML = `<input type="number" id="qbVal" step="any" value="${esc(cur ?? "")}"
      placeholder="${m.unit ? "单位：" + esc(m.unit) : "输入数值"}">`;
  } else if (m.input === "date") {
    box.innerHTML = `<input type="date" id="qbVal" value="${esc(cur ?? "")}">`;
  } else if (m.input === "select") {
    box.innerHTML = `<select id="qbVal">
      <option value="">— 请选择 —</option>
      ${(m.options || []).map(o =>
        `<option value="${esc(o)}" ${cur === o ? "selected" : ""}>${esc(o)}</option>`).join("")}
    </select>`;
  } else if (m.input === "rating") {
    box.innerHTML = `<div class="qb-rating">${[1, 2, 3, 4, 5].map(n =>
      `<button data-v="${n}" class="${cur === n ? "on" : ""}">${n}</button>`).join("")}</div>`;
    box.querySelectorAll("button").forEach(b => {
      b.onclick = () => {
        state.draft = Number(b.dataset.v);
        box.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
      };
    });
  } else {
    box.innerHTML = `<input type="text" id="qbVal" value="${esc(cur ?? "")}" placeholder="输入…">`;
  }
  if (m.input !== "rating") state.draft = null;
}

function renderFinish() {
  $("qbCrumb").innerHTML = "";
  $("qbQuestion").innerHTML = "";
  $("qbHints").innerHTML = "";
  $("qbInputArea").innerHTML = "";
  $("qbCurrent").className = "qb-current";
  $("qbCard").innerHTML = `
    <div class="qb-finish">
      <div class="qb-finish-icon">🎉</div>
      <h2>本场题目已走完</h2>
      <p>总进度 ${state.tree.progress.answered}/${state.tree.progress.total}。
        可在左侧切换领域补答，或返回档案查看。</p>
      <a class="qb-btn primary" style="text-decoration:none" href="/">返回档案</a>
    </div>`;
}

/* ---------- 提交 ---------- */

function readInput() {
  const m = state.flat[state.cur];
  if (m.input === "rating") return state.draft;
  const el = $("qbVal");
  if (!el) return undefined;
  let v = el.value;
  if (typeof v === "string") v = v.trim();
  if (m.input === "number" && v !== "") v = Number(v);
  return v === "" ? undefined : v;
}

async function submit({ skip = false } = {}) {
  const m = state.flat[state.cur];
  if (!m) return;
  if (!skip) {
    const v = readInput();
    if (v === undefined || v === null) return toast("请作答后再提交（或点跳过）", true);
    const useNew = state.snapshot === null || (m.volatile && state.snapshot === null);
    const body = {
      person: state.person, snapshot: state.snapshot,
      path: m.path, value: v,
    };
    if (!state.snapshot) { body.new_snapshot = true; }
    else if (m.volatile) {
      // 时间敏感指标：提示可新开时间态（当前快照的值会被本态覆盖）
      if (!confirm(`「${m.name}」随时间变化。\n\n确定 = 写入当前时间态（${state.snapshots.find(s => s.id === state.snapshot)?.label || ""}）\n取消 = 保持不动`)) return;
    }
    try {
      const r = await api("/api/qbank/answer", { method: "POST", body });
      if (r.created_snapshot) {
        state.snapshot = r.created_snapshot.id;
        $("qbSnapshot").innerHTML += ""; // 触发下拉刷新
        await loadSnapshots();
        $("qbSnapshot").value = state.snapshot;
        toast(`已为「${m.name}」新建时间态并写入`);
      } else {
        toast(`已写入：${m.name}`);
      }
    } catch (e) { return toast(e.message, true); }
  }
  // 跳到下一道未答题
  let i = state.cur + 1;
  while (i < state.flat.length && state.flat[i].answered) i++;
  if (i >= state.flat.length) i = Math.min(state.cur + 1, state.flat.length - 1);
  state.cur = i;
  await loadTree();
}

async function clearAnswer() {
  const m = state.flat[state.cur];
  if (!m?.current) return;
  if (!confirm(`清除「${m.name}」在当前时间态的本态覆盖？（继承值不受影响）`)) return;
  try {
    await api("/api/value", {
      method: "DELETE",
      body: { person: state.person, snapshot: state.snapshot, path: m.path },
    });
    toast(`已清除：${m.name}`);
    await loadTree();
  } catch (e) { toast(e.message, true); }
}

/* ---------- 挂载 ---------- */

$("qbSubmit").onclick = () => submit();
$("qbSkip").onclick = () => submit({ skip: true });
$("qbPrev").onclick = () => { state.cur = Math.max(0, state.cur - 1); render(); };
$("qbClear").onclick = clearAnswer;
document.addEventListener("keydown", (e) => {
  if (e.target.matches("textarea")) return;
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
  if (e.key === "ArrowLeft" && e.altKey) $("qbPrev").click();
});

boot().catch((e) => toast("初始化失败: " + e.message, true));
