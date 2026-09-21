/**
 * taglib-common —— 面板与挑选器共享的原语 (1.7.0 自 taglibrary.js 拆出)。
 *
 * 内容: HTML 转义 / toast / ComfyUI 设置读写 / 主题判定 / 全局偏好轮询同步 /
 * 两级库缓存 (面板轻量索引 + 挑选器全量库) / 节点 selection_state 读写与
 * NSFW·性别语义。导出的 let 变量是 ESM 活绑定 —— applyPanelIndex 在本模块内
 * 重新赋值, 所有导入方立刻看到新值。
 */

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/* 轻量提示条。
   注意: 本模块原先有 13 处 toast() 调用但从无定义 (manager.js 里那个是 IIFE 内
   局部函数, 不是全局) —— 每次调用都会抛 ReferenceError。后果不止提示不显示:
   `toast(...)` 之后的语句会被中断, 例如保存冲突规则后紧跟的 renderCfView()
   不会执行, 列表要重开页签才更新。这里补上模块级实现。 */
let _toastTimer = null;
function toast(msg, isErr = false) {
  let el = document.getElementById("taglib-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "taglib-toast";
    el.className = "tl-scope";   // 复用面板主题变量
    el.style.cssText =
      "position:fixed;left:50%;bottom:56px;transform:translateX(-50%);z-index:100000;" +
      "padding:8px 18px;border-radius:10px;font-size:13px;pointer-events:none;" +
      "border:1px solid var(--tl-border-2);background:var(--tl-bg-solid);" +
      "box-shadow:0 6px 24px rgba(0,0,0,.35);opacity:0;transition:opacity .2s;";
    document.body.appendChild(el);
  }
  const { pid, isLight } = currentTheme();
  el.dataset.theme = pid;
  el.classList.toggle("tl-light", isLight);
  el.textContent = msg;
  el.style.color = isErr ? "var(--tl-danger)" : "var(--tl-text)";
  el.style.opacity = "1";
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.style.opacity = "0"; }, 2400);
}
/* 带「撤销」的提示条 —— 专给破坏性操作。
   🎲 填充会清掉用户手动挑的词且不可逆, 必须给退路; 普通 toast 是
   pointer-events:none, 放不了按钮, 所以单独一支。同时只保留一条。 */
let _undoTimer = null;
let _undoFn = null;
function hideUndoToast() {
  const el = document.getElementById("taglib-undo-toast");
  if (el) el.style.opacity = "0";
  _undoFn = null;
  clearTimeout(_undoTimer);
}
function undoToast(msg, onUndo, ms = 7000) {
  let el = document.getElementById("taglib-undo-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "taglib-undo-toast";
    el.className = "tl-scope";
    el.style.cssText =
      "position:fixed;left:50%;bottom:56px;transform:translateX(-50%);z-index:100001;" +
      "display:flex;align-items:center;gap:12px;padding:8px 12px 8px 16px;border-radius:10px;" +
      "font-size:13px;border:1px solid var(--tl-border-2);background:var(--tl-bg-solid);" +
      "box-shadow:0 6px 24px rgba(0,0,0,.35);opacity:0;transition:opacity .2s;";
    const span = document.createElement("span");
    span.id = "taglib-undo-msg";
    const btn = document.createElement("button");
    btn.id = "taglib-undo-btn";
    btn.type = "button";
    btn.textContent = "撤销";
    btn.style.cssText =
      "border:1px solid var(--tl-border-2);background:var(--tl-input-bg);" +
      "color:var(--tl-accent-text);font:inherit;font-size:12px;padding:3px 10px;" +
      "border-radius:6px;cursor:pointer;flex:0 0 auto;";
    btn.onclick = () => { const f = _undoFn; hideUndoToast(); if (f) f(); };
    el.append(span, btn);
    document.body.appendChild(el);
  }
  const { pid, isLight } = currentTheme();
  el.dataset.theme = pid;
  el.classList.toggle("tl-light", isLight);
  el.querySelector("#taglib-undo-msg").textContent = msg;
  el.style.color = "var(--tl-text)";
  el.style.opacity = "1";
  _undoFn = onUndo || null;
  clearTimeout(_undoTimer);
  _undoTimer = setTimeout(hideUndoToast, ms);
}
const MANAGER_URL = "/taglib?embed=1";
const SETTING_PREFIX = "TagLibrary.";

/* settings keys */
const SET_DEFAULT_MODE = SETTING_PREFIX + "default_mode";
const SET_DEFAULT_NSFW = SETTING_PREFIX + "default_nsfw";
const SET_SCALE = SETTING_PREFIX + "chip_scale";
const SET_LANG = SETTING_PREFIX + "display_lang";

/* 两级缓存 ——
   面板级 (轻量, 启动即拉): 分类名/图标 + en→树路径 + 性别/NSFW 标记。
     /taglib/api/panel-index 只有索引, 无标签正文 (实测约为全量库的 1/5)。
   挑选器级 (全量, 懒加载): 含标签正文的完整库, 只在打开挑选器时拉。 */
let LIB_CACHE = null;        // 全量库 (仅挑选器用)
let LIB_FETCHING = null;
let PANEL_CATS = [];         // [{name, icon, color}] 面板分组标题与类目排序
let PANEL_NSFW = new Set();  // NSFW 词表 (executed 回显反查)
let LIB_PATH = new Map();    // en_l -> [大类名, 子分类名, 孙分类名|null]
let LIB_GENDER = new Map();  // en_l -> "female"|"male"
let PANEL_CAPS = new Map();  // "大类/子类" -> [下限, 上限] = 引擎内置槽位配额 (slotpolicy.SLOT_MAX)
let INDEX_FETCHING = null;

function applyPanelIndex(d) {
  PANEL_CATS = d.cats || [];
  // 路径是 (子分类下标, 孙分类下标) 二元组 -> 还原成 [大类名, 子类名, 孙类名|null]
  const subs = d.subs || [];
  const groups = d.groups || [];
  const m = new Map();
  for (const [en, idxPair] of Object.entries(d.paths || {})) {
    const pair = subs[idxPair[0]] || ["", ""];
    const gi = idxPair[1];
    m.set(en, [pair[0], pair[1], gi >= 0 ? (groups[gi] ?? null) : null]);
  }
  LIB_PATH = m;
  LIB_GENDER = new Map(Object.entries(d.gender || {}));
  PANEL_NSFW = new Set(d.nsfw || []);
  // 引擎内置槽位配额: 与 subs 同序的 [下限, 上限]
  const caps = d.caps || [];
  PANEL_CAPS = new Map();
  subs.forEach((pair, i) => {
    const c = caps[i];
    if (pair && c) PANEL_CAPS.set(`${pair[0]}/${pair[1]}`, c);
  });
}

/* 槽位配额 (引擎内置值)。挑标签面板用它做数字框的默认显示 —— 显示 1/1 而引擎按
   5/3 或 2 走, 用户按面板理解必然算错 (2026-09-21 修)。 */
function panelSlotCap(key) {
  const hit = PANEL_CAPS.get(key);
  return hit ? { min: hit[0], max: hit[1] } : { min: 1, max: 1 };
}

// 标签有效性别: state 里带的 gender 优先; 旧选择数据缺字段时回查库
function tagGender(t) {
  const g = String(t.gender || "").toLowerCase();
  if (g === "female" || g === "male") return g;
  return LIB_GENDER.get(String(t.en).toLowerCase()) || "";
}

/* 面板索引 (轻量): 面板初始化 / 库变更后刷新时调用 */
async function fetchPanelIndex() {
  if (INDEX_FETCHING) return INDEX_FETCHING;
  INDEX_FETCHING = fetch("/taglib/api/panel-index")
    .then((r) => r.json())
    .then((d) => { applyPanelIndex(d || {}); return d; })
    .finally(() => { INDEX_FETCHING = null; });
  return INDEX_FETCHING;
}

/* 全量库 (含标签正文): 仅挑选器需要, 打开时才加载 */
async function fetchLibrary() {
  if (LIB_CACHE) return LIB_CACHE;
  if (!LIB_FETCHING) {
    LIB_FETCHING = fetch("/taglib/api/library")
      .then((r) => r.json())
      .then((data) => {
        LIB_CACHE = data.library || { categories: [] };
        return LIB_CACHE;
      })
      .finally(() => { LIB_FETCHING = null; });
  }
  return LIB_FETCHING;
}

function invalidateLibraryCache() {
  LIB_CACHE = null;
  PANEL_CATS = [];
  PANEL_NSFW = new Set();
  PANEL_CAPS = new Map();
  LIB_PATH = new Map();
  LIB_GENDER = new Map();
}

/* ---------------------------------------------------- settings helpers */

function getSetting(id, fallback) {
  try {
    const v = app.extensionManager?.setting?.get?.(id);
    if (v !== undefined && v !== null) return v;
  } catch {}
  try {
    const raw = localStorage.getItem("taglib." + id);
    if (raw !== null) return JSON.parse(raw);
  } catch {}
  return fallback;
}

function setSetting(id, value) {
  try {
    app.extensionManager?.setting?.set?.(id, value);
    return;
  } catch {}
  try { localStorage.setItem("taglib." + id, JSON.stringify(value)); } catch {}
}

/* 当前主题: ComfyUI 用 html.dark-theme 类区分明暗, 具体配色 id 在设置里。
   面板/挑选器/管理弹窗共用同一份判断, 保证三处配色一致。 */
function currentTheme() {
  let pid = getSetting("Comfy.ColorPalette", "dark");
  if (typeof pid !== "string") pid = pid?.id || "dark";
  const isLight = !document.documentElement.classList.contains("dark-theme");
  return { pid, isLight };
}

/* 管理页 URL: 带上主题参数, 让 iframe 内独立文档也能拿到当前配色
   (iframe 不继承父页面的 html 类, 必须显式传)。 */
function managerUrl() {
  const { pid, isLight } = currentTheme();
  return `${MANAGER_URL}&theme=${encodeURIComponent(pid)}&light=${isLight ? 1 : 0}`;
}

/* 把主题同步给已打开弹窗内的 iframe (URL 参数只覆盖首次加载) */
function pushThemeToFrames(root) {
  const { pid, isLight } = currentTheme();
  for (const fr of root.querySelectorAll("iframe")) {
    try { fr.contentWindow?.postMessage({ type: "taglib-theme", theme: pid, light: isLight }, "*"); } catch {}
  }
}

/* ---------------------------------------------------- 全局偏好同步 (单例轮询)
   本版本前端没有可用的 settings change 事件面, 只能轮询兜底。
   做成模块级单例: 无论画布上有几个标签库节点, 只有一个 2s 定时器在跑;
   比对到变化才回调各面板 —— 旧实现是每个节点各起一个定时器。 */
const SYNC_KEYS = [
  SET_DEFAULT_MODE, SET_DEFAULT_NSFW, SET_SCALE, SET_LANG,
  SETTING_PREFIX + "chip_font_size", SETTING_PREFIX + "chip_radius",
];
const _panelSyncers = new Set();
let _syncTimer = null;
let _syncLast = new Map(SYNC_KEYS.map((k) => [k, getSetting(k, null)]));

function _tickPanelSync() {
  let changed = false;
  for (const k of SYNC_KEYS) {
    const v = getSetting(k, null);
    if (v !== _syncLast.get(k)) { _syncLast.set(k, v); changed = true; }
  }
  if (!changed) return;
  for (const fn of [..._panelSyncers]) {
    try { fn(); } catch {}
  }
}

function registerPanelSync(fn) {
  _panelSyncers.add(fn);
  if (!_syncTimer) _syncTimer = setInterval(_tickPanelSync, 2000);
  return () => {
    _panelSyncers.delete(fn);
    if (!_panelSyncers.size && _syncTimer) {
      clearInterval(_syncTimer);
      _syncTimer = null;
    }
  };
}

/* ---------------------------------------------------- state */

function defaultState() {
  return {
    // 面板只显示这里 —— "已添加到本节点" 的标签, 每条:
    // { en, zh?, nsfw?, enabled:bool, pinned?:true }
    tags: [],
    // 排除的类目 (轴名数组): 唯一的范围控制 —
    // 随机抽不到、🎲填充不填也不清空该分类的已填标签
    // 画师默认关闭: 它是"选定"而不是"随机"的维度, 引擎随机抽一个画师只会毁掉整体观感。
    // 想用时在侧栏把「画师」勾上, 或直接手动往节点里加 @画师名。
    exclude_categories: ["画师"],
    avoid_conflicts: true,
    nsfw: null,
  };
}

function getState(node) {
  const w = node.widgets?.find((x) => x.name === "selection_state");
  let st = { ...defaultState(), tags: [] };
  try {
    const raw = JSON.parse(w.value || "{}");
    st = { ...st, ...raw, tags: Array.isArray(raw.tags) ? raw.tags : [] };
  } catch {}
  // nsfw 只允许显式布尔: null/缺失就地物化为当前全局默认 ——
  // 否则面板按全局默认显示 NSFW 词、后端却按 false 过滤 (预览≠生成)。
  if (st.nsfw !== true && st.nsfw !== false) {
    st.nsfw = !!getSetting(SET_DEFAULT_NSFW, false);
  }
  return st;
}

function getNsfwEffective(node) {
  return getState(node).nsfw === true;
}

function getGender(node) {
  const g = String(getState(node).gender || "off");
  return GENDER_SEQ.includes(g) ? g : "off";
}

const GENDER_SEQ = ["off", "female", "male"];
const GENDER_LABEL = { off: "⚥ 双性", female: "♀ 仅女性", male: "♂ 仅男性" };
const GENDER_TITLE = {
  off: "性别过滤: 关闭 (男女性专属标签都保留)",
  female: "性别过滤: 女性 (剔除男性专属标签, 如 1boy/multiple boys)",
  male: "性别过滤: 男性 (剔除女性专属标签, 如 1girl/milf)",
};

function setState(node, patch) {
  const w = node.widgets?.find((x) => x.name === "selection_state");
  if (!w) return;
  w.value = JSON.stringify({ ...getState(node), ...patch });
  node.setDirtyCanvas?.(true, true);
}


export {
  escapeHtml, toast, undoToast, hideUndoToast, MANAGER_URL, SETTING_PREFIX, SET_DEFAULT_MODE, SET_DEFAULT_NSFW,
  SET_SCALE, SET_LANG, LIB_CACHE, PANEL_CATS, PANEL_NSFW, LIB_PATH, LIB_GENDER,
  tagGender, fetchPanelIndex, fetchLibrary, invalidateLibraryCache, panelSlotCap,
  getSetting, setSetting, currentTheme, managerUrl, pushThemeToFrames,
  registerPanelSync, defaultState, getState, setState, getNsfwEffective, getGender,
  GENDER_SEQ, GENDER_LABEL, GENDER_TITLE,
};
