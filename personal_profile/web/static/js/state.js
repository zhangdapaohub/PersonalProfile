/* 全局状态与链接样式 */

export const state = {
  persons: [],
  current: null,   // 当前人物 identity_id
  tree: null,      // 当前人物时间轴视图
  selected: null,  // 当前选中快照 id
  dimNames: {},    // 维度模板：key → 中文名
  lastTrace: null, // 最近一次详情 trace，供"改"按钮预填
};

/* 连贯性链接视觉样式（颜色与 SVG marker 对应 index.html defs） */
export const LINK_STYLE = {
  "继承":   { color: "#2563eb", marker: "arr-blue",   dash: null },
  "因果":   { color: "#059669", marker: "arr-green",  dash: null },
  "断裂":   { color: "#dc2626", marker: "arr-red",   dash: "7 5" },
  "主动重塑": { color: "#7c3aed", marker: "arr-purple", dash: "2 4" },
};
