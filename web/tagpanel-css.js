/**
 * tagpanel-css.js —— 面板样式 (由 JS 注入, ComfyUI 只自动加载 web/ 下的 .js)
 * 注入一次, style#taglib-panel-style; 幂等可重复加载。
 */

const CSS = `
/* ================= TagLibrary 节点面板 ================= */
/* 主题适配: html 根类 dark-theme 由 ComfyUI 前端按当前配色切换
   (arc/dark/github/light/solarized/nord 六套内置主题)。
   面板颜色全部取自 CSS 变量 → 任何主题下都协调。 */
.taglib-widget-holder { all: initial; display: block; font-family: inherit; min-width: 0; width: 100%; height: var(--comfy-widget-height, 60%); min-height: var(--comfy-widget-min-height, 160px); overflow: hidden; box-sizing: border-box; }
.taglib-panel {
  /* 默认 = dark 主题 */
  --tl-bg: rgba(23,23,24,0.94);
  --tl-card: rgba(255,255,255,0.045);
  --tl-border: rgba(255,255,255,0.10);
  --tl-text: #e3e7ee;
  --tl-muted: #8b93a5;
  --tl-accent: #54a0ff;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--tl-border);
  border-radius: 10px;
  background: linear-gradient(180deg, rgba(30,34,44,0.94), var(--tl-bg));
  color: var(--tl-text);
  font: 12px/1.45 "Segoe UI", "Microsoft YaHei", sans-serif;
  user-select: none;
  overflow: hidden;
}
/* ---------- 主题覆盖 (fg/bg 取自各主题声明值, 边框/卡片由明度推算) ---------- */
/* arc: fg #fff, bg #2b2f38, menu #242730 */
html:not(.dark-theme) .taglib-panel,
.taglib-panel[data-theme="arc"] {
  --tl-bg: rgba(36,39,48,0.94);
  --tl-card: rgba(255,255,255,0.05);
}
/* github: fg #e5eaf0, bg #161b22, menu #13171d */
.taglib-panel[data-theme="github"] {
  --tl-bg: rgba(19,23,29,0.94);
}
/* light: fg #222, bg #DDD, menu #FFFFFF — 浅色主题 */
html:not(.dark-theme) .taglib-panel[data-theme="light"],
.taglib-panel.tl-light {
  --tl-bg: rgba(255,255,255,0.96);
  --tl-card: rgba(0,0,0,0.045);
  --tl-border: rgba(0,0,0,0.14);
  --tl-text: #222;
  --tl-muted: #6b7280;
  --tl-accent: #0071e3;
  background: linear-gradient(180deg, #ffffff, rgba(245,245,247,0.96));
}
/* solarized: fg #fdf6e3, bg #002b36, menu #073642 */
.taglib-panel[data-theme="solarized"] {
  --tl-bg: rgba(7,54,66,0.94);
  --tl-card: rgba(253,246,227,0.06);
  --tl-text: #fdf6e3;
  --tl-muted: #93a1a1;
  --tl-accent: #b58900;
}
/* nord: fg #e5eaf0, bg #2e3440, menu #161b22 */
.taglib-panel[data-theme="nord"] {
  --tl-bg: rgba(22,27,34,0.94);
  --tl-accent: #88c0d0;
}
.taglib-panel *, .taglib-panel *::before, .taglib-panel *::after { box-sizing: inherit; }

/* ---------- 头部 ---------- */
.tl-head {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 10px;
  background: rgba(255,255,255,0.03);
  border-bottom: 1px solid var(--tl-border);
}
.tl-logo {
  width: 20px; height: 20px; flex: none;
  display: grid; place-items: center;
  border-radius: 6px;
  background: linear-gradient(135deg, rgba(84,160,255,0.35), rgba(155,89,182,0.30));
  box-shadow: inset 0 0 0 1px rgba(84,160,255,0.4);
  font-size: 12px;
}
.tl-title { font-weight: 600; letter-spacing: .02em; }
.tl-head-spacer { flex: 1; }

.tl-btn {
  display: inline-flex; align-items: center; gap: 4px;
  border: 1px solid var(--tl-border);
  background: var(--tl-card);
  color: var(--tl-text);
  border-radius: 7px;
  font: inherit; font-size: 11px;
  padding: 3px 9px;
  cursor: pointer;
  transition: background .15s, border-color .15s, box-shadow .15s;
}
.tl-btn:hover { background: rgba(84,160,255,.16); border-color: rgba(84,160,255,.45); }
.tl-btn.primary {
  background: linear-gradient(135deg, rgba(84,160,255,.32), rgba(84,160,255,.18));
  border-color: rgba(84,160,255,.55);
}
.tl-btn.primary:hover { box-shadow: 0 0 10px -2px rgba(84,160,255,.5); }
.tl-btn.icon { padding: 3px 6px; }
/* NSFW 二态按钮: 默认关(灰), 开=绿色 */
.tl-nsfw-btn { padding: 3px 8px; font-weight: 600; letter-spacing: .3px; }
.tl-nsfw-btn.on {
  background: linear-gradient(135deg, rgba(46,204,113,.35), rgba(46,204,113,.18));
  border-color: rgba(46,204,113,.65);
  color: #7dffb0;
}
.tl-nsfw-btn.on:hover { box-shadow: 0 0 10px -2px rgba(46,204,113,.55); }
/* 🎲填充标签的分组标题 */
.tl-fill-group {
  flex-basis: 100%;
  text-align: center;
  font-size: 10px;
  color: var(--tl-muted);
  opacity: .85;
  padding: 4px 0 1px;
  user-select: none;
}
/* 手动模式分类范围栏 */
.tl-catbar { padding: 4px 10px 2px; border-bottom: 1px solid var(--tl-border); background: rgba(255,255,255,.02); }
.tl-catbar-row { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.tl-catbar-row + .tl-catbar-row { margin-top: 4px; }
.tl-fillmode {
  border: 1px solid var(--tl-border); background: transparent; color: var(--tl-muted);
  border-radius: 999px; padding: 2px 9px; font-size: 11px; cursor: pointer; transition: all .15s;
}
.tl-fillmode:hover { color: var(--tl-text); border-color: rgba(84,160,255,.5); }
.tl-fillmode.active {
  background: linear-gradient(135deg, rgba(84,160,255,.3), rgba(84,160,255,.15));
  border-color: rgba(84,160,255,.6); color: var(--tl-text);
}
.tl-catchip {
  border: 1px solid var(--tl-border); background: rgba(255,255,255,.03); color: var(--tl-muted);
  border-radius: 999px; padding: 2px 9px; font-size: 11px; cursor: pointer; transition: all .15s;
}
.tl-catchip:hover { color: var(--tl-text); }
.tl-catchip.on {
  background: linear-gradient(135deg, rgba(46,204,113,.28), rgba(46,204,113,.14));
  border-color: rgba(46,204,113,.6); color: #7dffb0;
}
.tl-catbar-hint { font-size: 10px; color: var(--tl-muted); opacity: .7; }

.tl-switch {
  position: relative; width: 30px; height: 16px; flex: none;
  border-radius: 999px;
  background: rgba(255,255,255,0.14);
  border: 1px solid var(--tl-border);
  cursor: pointer;
  transition: background .18s;
}
.tl-switch::after {
  content: ""; position: absolute; top: 1px; left: 1px;
  width: 12px; height: 12px; border-radius: 50%;
  background: #aab3c5; transition: transform .18s, background .18s;
}
.tl-switch.on { background: rgba(255,107,107,.4); border-color: rgba(255,107,107,.6); }
.tl-switch.on::after { transform: translateX(14px); background: #ff8787; }

/* ---------- 工具行 ---------- */
.tl-toolbar { display: flex; align-items: center; gap: 6px; padding: 7px 10px 2px; }
.tl-search {
  flex: 1; min-width: 40px;
  background: rgba(0,0,0,0.38);
  border: 1px solid var(--tl-border);
  border-radius: 7px;
  color: var(--tl-text);
  font: inherit; font-size: 11px;
  padding: 4px 9px;
  outline: none;
}
.tl-search:focus { border-color: rgba(84,160,255,.6); box-shadow: 0 0 0 2px rgba(84,160,255,.12); }
.tl-search::placeholder { color: var(--tl-muted); }

.tl-seg { display: inline-flex; border: 1px solid var(--tl-border); border-radius: 7px; overflow: hidden; }
.tl-seg button {
  border: none; background: transparent; color: var(--tl-muted);
  font: inherit; font-size: 10.5px;
  padding: 4px 8px; cursor: pointer;
  transition: background .13s, color .13s;
}
.tl-seg button + button { border-left: 1px solid var(--tl-border); }
.tl-seg button:hover { color: var(--tl-text); background: rgba(255,255,255,.05); }
.tl-seg button.active { color: #fff; background: rgba(84,160,255,.30); }

/* ---------- 分类条 ---------- */
.tl-cats {
  display: flex; flex-wrap: wrap; gap: 4px;
  padding: 6px 10px 4px;
}
.tl-cat-pill {
  display: inline-flex; align-items: center; gap: 5px;
  border-radius: 999px;
  border: 1px solid var(--tl-border);
  background: var(--tl-card);
  font-size: 11px;
  padding: 3px 10px;
  cursor: pointer;
  transition: all .14s ease;
}
.tl-cat-pill:hover { filter: brightness(1.25); }
.tl-cat-pill.active { border-color: currentColor; background: color-mix(in srgb, currentColor 16%, transparent); }
.tl-cat-pill .tl-badge {
  font-size: 9.5px; min-width: 16px; text-align: center;
  background: color-mix(in srgb, currentColor 30%, rgba(0,0,0,.35));
  border-radius: 999px; padding: 0 5px; line-height: 1.5;
}
.tl-nsfw-pill {
  display: inline-flex; align-items: center; gap: 4px;
  margin-left: auto;
}

/* ---------- chips 区 ---------- */
.tl-chipzone {
  margin: 4px 10px 6px;
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 9px;
  background: rgba(0,0,0,0.22);
  padding: 7px;
  flex: 1;
  min-height: 58px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,.18) transparent;
}
.tl-sub-head {
  display: flex; align-items: baseline; gap: 6px;
  font-size: 10px; color: var(--tl-muted);
  letter-spacing: .04em;
  margin: 5px 0 4px;
}
.tl-sub-head:first-child { margin-top: 0; }
.tl-sub-head::after { content: ""; flex: 1; height: 1px; align-self: center;
  background: linear-gradient(to right, rgba(255,255,255,.14), transparent); }
.tl-sub-name { color: var(--tl-text); font-weight: 600; }
.tl-chips { display: flex; flex-wrap: wrap; gap: 4px; }

.tl-chip {
  --c: #54a0ff;
  display: inline-flex; align-items: center; gap: 4px;
  border: 1px solid color-mix(in srgb, var(--c) 28%, rgba(255,255,255,0.14));
  background: color-mix(in srgb, var(--c) 9%, rgba(255,255,255,0.04));
  color: var(--tl-text);
  border-radius: 7px;
  font-size: 11px;
  line-height: 1.4;
  padding: 2.5px 8px;
  cursor: pointer;
  transition: all .12s ease;
}
.tl-chip:hover {
  background: color-mix(in srgb, var(--c) 20%, transparent);
  border-color: color-mix(in srgb, var(--c) 55%, transparent);
  transform: translateY(-1px);
}
.tl-chip.sel {
  color: #fff;
  background: color-mix(in srgb, var(--c) 32%, transparent);
  border-color: var(--c);
  box-shadow: 0 0 8px -3px var(--c), inset 0 0 0 1px color-mix(in srgb, var(--c) 60%, transparent);
}
.tl-chip.sel::before { content: "✓"; font-size: 9px; opacity: .95; }
.tl-chip.nsfw:not(.sel) { opacity: .68; }
.tl-chip .tl-n { font-size: 10px; color: #ffb3b3; }

.tl-empty { color: var(--tl-muted); font-size: 11px; padding: 12px 4px; text-align: center; }

/* ---------- 已选区 ---------- */
.tl-selzone { padding: 0 10px 4px; }
.tl-zone-label {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 10px; color: var(--tl-muted);
  margin-bottom: 4px;
}
.tl-clearbtn { cursor: pointer; }
.tl-clearbtn:hover { color: #ff9a9a; }
.tl-selected {
  display: flex; flex-wrap: wrap; gap: 4px;
  min-height: 30px;
  border: 1px dashed rgba(255,255,255,0.16);
  border-radius: 9px;
  background: rgba(0,0,0,0.18);
  padding: 5px;
}
.tl-sel-tag {
  --c: #888;
  display: inline-flex; align-items: center; gap: 4px;
  border-radius: 7px;
  padding: 2px 7px;
  font-size: 11px;
  cursor: grab;
  color: #fff;
  background: color-mix(in srgb, var(--c) 26%, rgba(255,255,255,0.06));
  border: 1px solid color-mix(in srgb, var(--c) 55%, transparent);
}
.tl-sel-tag.dragging { opacity: .35; }
.tl-sel-tag.drop-target { outline: 1px dashed var(--c); outline-offset: 1px; }
.tl-pin { cursor: pointer; font-size: 10px; opacity: .38; transition: all .12s; }
.tl-pin:hover { opacity: .85; }
.tl-pin.pinned { opacity: 1; filter: drop-shadow(0 0 3px gold); }
.tl-x { cursor: pointer; opacity: .5; padding: 0 1px; }
.tl-x:hover { opacity: 1; color: #ff9a9a; }

/* ---------- 已添加标签 (Added view): 灰=停用, 绿=启用 ---------- */
.tl-ttag {
  display: inline-flex; align-items: center; gap: 5px;
  border-radius: var(--taglib-chip-radius, 7px);
  font-size: var(--taglib-chip-font, inherit);
  padding: calc(2.5px * var(--taglib-chip-scale, 1)) calc(8px * var(--taglib-chip-scale, 1));
  cursor: pointer;
  user-select: none;
  transition: all .13s ease;
}
.tl-ttag b { font-weight: 600; }
.tl-ttag .t-zh { font-style: normal; opacity: .55; font-size: .82em; }

/* 停用: 灰色 */
.tl-ttag {
  background: rgba(255,255,255,.05);
  border: 1px solid rgba(255,255,255,.16);
  color: #99a2b3;
}

/* 启用: 绿色 */
.tl-ttag.on {
  background: color-mix(in srgb, #2ecc71 20%, transparent);
  border-color: rgba(46,204,113,.65);
  color: #d9ffe8;
  box-shadow: 0 0 6px -2px rgba(46,204,113,.5);
}
.tl-ttag.on:hover { background: color-mix(in srgb, #2ecc71 30%, transparent); }
.tl-ttag.nsfw:not(.on) { border-color: rgba(255,107,107,.35); color: #d9a0a0; }
.tl-ttag.nsfw.on {
  background: color-mix(in srgb, #ff4757 22%, transparent);
  border-color: rgba(255,71,87,.7);
  color: #ffdada;
  box-shadow: 0 0 6px -2px rgba(255,71,87,.55);
}

/* ---------- 底部预览 ---------- */
.tl-preview-row {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 10px 8px;
}
.tl-preview {
  flex: 1;
  font-size: 10.5px;
  color: var(--tl-muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  background: rgba(0,0,0,0.25);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 7px;
  padding: 4px 8px;
}
.tl-roll-btn {
  display: inline-flex; align-items: center; gap: 5px;
  border: 1px solid rgba(84,160,255,.5);
  background: linear-gradient(135deg, rgba(84,160,255,.30), rgba(84,160,255,.14));
  color: #fff;
  border-radius: 8px;
  font: inherit; font-size: 11px; font-weight: 600;
  padding: 4px 12px;
  cursor: pointer;
  transition: all .15s ease;
}
.tl-roll-btn:hover { box-shadow: 0 0 12px -2px rgba(84,160,255,.55); transform: translateY(-1px); }
.tl-roll-btn:active { transform: translateY(0); }

/* NSFW 开关行内提示 */
.tl-hint { font-size: 10px; color: var(--tl-muted); }
`;

export function injectPanelStyle() {
  if (document.getElementById("taglib-panel-style")) return;
  const el = document.createElement("style");
  el.id = "taglib-panel-style";
  el.textContent = CSS;
  document.head.appendChild(el);
}
