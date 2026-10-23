/* 入口：初始化 + 将交互函数挂载到 window（index.html 内联 onclick 使用） */

import { state } from "./state.js";
import { api } from "./api.js";
import { openModal, closeModal } from "./util.js";
import { loadPersons, selectPerson } from "./view.js";
import { drawLinks } from "./timeline.js";
import { prefillForm, renderDetail, delNode } from "./detail.js";
import {
  submitPerson, submitSnapshot, setInherits, submitLink, delLink,
  submitValue, delValue, submitCollect, loadConfig, saveConfig,
  renamePerson, deletePerson, deleteSnapshot, renameSnapshot, exportPerson, importPersonFile,
  setBreak, reorderSnapshot,
} from "./actions.js";
import { openSnapshotModal, openLinkModal, openCollectModal } from "./modals.js";

/* 内联 onclick 处理器挂载 */
Object.assign(window, {
  openModal, closeModal,
  openSnapshotModal, openLinkModal, openCollectModal,
  submitPerson, submitSnapshot, submitLink, submitValue,
  delValue, delLink, prefillForm, submitCollect, saveConfig, delNode,
  renamePerson, deletePerson, deleteSnapshot, renameSnapshot,
  exportPerson, importPersonFile,
  setBreak, reorderSnapshot,
});

/* 导入文件选择 */
const importFileEl = document.getElementById("importFile");
if (importFileEl) {
  importFileEl.addEventListener("change", e => {
    const file = e.target.files && e.target.files[0];
    if (file) importPersonFile(file);
    e.target.value = "";
  });
}

/* 点击遮罩关闭模态 */
document.addEventListener("click", e => {
  if (e.target.classList && e.target.classList.contains("modal-mask")) {
    e.target.hidden = true;
  }
});

window.addEventListener("resize", () => state.tree && drawLinks());

/* 维度模板名（分组标题用中文名，如 physical → 物理维度） */
api("/api/schema").then(d => {
  const dims = (d && d.dimensions) || {};
  state.schema = dims;
  for (const [k, v] of Object.entries(dims)) {
    state.dimNames[k] = (v && v.name) || k;
  }
  if (state.selected) selectPerson(state.current); // 已打开详情则刷新标题
}).catch(() => {});

loadPersons();
