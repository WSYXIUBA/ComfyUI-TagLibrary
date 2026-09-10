/**
 * ComfyUI-TagLibrary 节点面板扩展 v2
 *
 * v2: 现代化重设计
 *  - CSS 由 JS 注入 (ComfyUI 只自动加载 web/ 下 .js, 之前 tagpanel.css 根本没被加载)
 *  - 分类 pills + 色彩化 chips(✓选中态) + 已选区拖拽/钉选 + 分段式模式切换 + ROLL 按钮
 *  - NSFW 开关: 设置页有默认值, 节点上有快捷开关, 双向同步, 写进 selection_state
 *  - 设置页注册 (Settings 搜"标签库"): 默认模式 / NSFW 默认值 / 面板高度
 */
import { app } from "../../scripts/app.js";
import { injectPanelStyle } from "./tagpanel-css.js";

const NODE_NAME = "TagLibraryNode";

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

/* chip 右键菜单 —— 单例复用。
   旧实现每次右键都 createElement + appendChild + 挂 document 监听,
   频繁右键会在 body 上反复增删节点。这里只建一次, 之后改内容与位置。 */
let _chipMenuEl = null;
let _chipMenuOff = null;

function closeChipMenu() {
  if (_chipMenuEl) _chipMenuEl.style.display = "none";
  if (_chipMenuOff) {
    document.removeEventListener("click", _chipMenuOff);
    _chipMenuOff = null;
  }
}

function openChipMenu(x, y, { pinned, onPin, onRemove }) {
  closeChipMenu();
  if (!_chipMenuEl) {
    _chipMenuEl = document.createElement("div");
    _chipMenuEl.className = "tl-chip-menu tl-scope";
    _chipMenuEl.style.display = "none";
    document.body.appendChild(_chipMenuEl);
  }
  const menu = _chipMenuEl;
  const { pid, isLight } = currentTheme();
  menu.dataset.theme = pid;
  menu.classList.toggle("tl-light", isLight);
  menu.innerHTML =
    `<button data-a="pin">${pinned ? "📍 取消钉选" : "📌 钉选 (自动/填充不覆盖)"}</button>` +
    `<button data-a="del" class="danger">✕ 移除标签</button>`;
  menu.style.display = "flex";
  const r = menu.getBoundingClientRect();
  menu.style.left = Math.min(x, innerWidth - r.width - 8) + "px";
  menu.style.top = Math.min(y, innerHeight - r.height - 8) + "px";
  menu.querySelector('[data-a="pin"]').onclick = (ev) => {
    ev.stopPropagation(); closeChipMenu(); onPin();
  };
  menu.querySelector('[data-a="del"]').onclick = (ev) => {
    ev.stopPropagation(); closeChipMenu(); onRemove();
  };
  _chipMenuOff = closeChipMenu;
  setTimeout(() => document.addEventListener("click", _chipMenuOff), 0);
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
  return st;
}

function getNsfwEffective(node) {
  // state.nsfw 显式覆盖 > 全局设置
  const st = getState(node);
  if (st.nsfw === true || st.nsfw === false) return st.nsfw;
  return !!getSetting(SET_DEFAULT_NSFW, false);
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

/* ---------------------------------------------------- panel build */

export function buildPanelWidget(node, container) {
  injectPanelStyle();
  // tl-scope = 共享主题变量作用域 (tagpanel-css.js); taglib-panel = 面板自身布局
  container.classList.add("taglib-panel", "tl-scope");
  // 翻译扩展免疫: ComfyUI-DD-Translation 等会按字典把 chip 英文实时改写成中文
  // (night→夜晚), 造成"雨靴雨靴"式重复与观感发灰。p-inputtext 在其 shouldSkipNode
  // 的容器排除链里, 整个面板因此跳过翻译; translate=no/notranslate 约束守规矩的翻译器。
  container.classList.add("p-inputtext");
  container.setAttribute("translate", "no");

  const ui = { activeCat: null, filter: "", mode: "manual", chipsBoxHeight: null,
               previewMode: getState(node).preview_mode || "simple" };
  // activeCat=null -> 显示全部分类的 chips; 点胶囊切换到该分类; 再点取消回全部


  container.innerHTML = `
    <div class="tl-head">
      <span class="tl-logo">🏷</span>
      <span class="tl-title">标签库</span>
      <span class="tl-head-spacer"></span>
      <button class="tl-btn tl-nsfw-btn" data-act="nsfw" title="NSFW: 关=剔除并不显示 NSFW 标签; 开=显示且可输出">NSFW</button>
      <button class="tl-btn icon tl-more-btn" data-act="more" title="更多设置 (性别过滤 / 防冲突 / 显示语言 / 预览模式 / 清空)">⋯<i class="tl-more-dot"></i></button>
      <button class="tl-btn primary" data-act="addtags" title="从标签库挑选标签添加">➕ 添加标签</button>
    </div>
    <div class="tl-toolbar">
      <input class="tl-search" placeholder="🔍 过滤已添加的标签…" />
      <div class="tl-seg tl-mode-seg" title="工作模式">
        <button data-mode="manual">手动</button>
        <button data-mode="auto">自动</button>
      </div>
    </div>
    <div class="tl-chipzone"></div>
    <div class="tl-preview-row">
      <div class="tl-preview"></div>
      <button class="tl-roll-btn" data-act="roll" title="随机抽取标签填入框内 (按当前模式和设置)">🎲 填充</button>
    </div>
    <div class="tl-menu" hidden>
      <button class="tl-menu-item" data-act="gender"><span class="tl-mi-k">性别过滤</span><span class="tl-mi-v tl-gender-val">⚥ 双性</span></button>
      <button class="tl-menu-item" data-act="conflict"><span class="tl-mi-k">防冲突</span><span class="tl-mi-v tl-conflict-val">已开启</span></button>
      <button class="tl-menu-item" data-act="lang"><span class="tl-mi-k">显示语言</span><span class="tl-mi-v tl-lang-val">双语</span></button>
      <button class="tl-menu-item" data-act="pv"><span class="tl-mi-k">预览模式</span><span class="tl-mi-v tl-pv-val">简洁</span></button>
      <button class="tl-menu-item danger" data-act="clear"><span class="tl-mi-k">清空标签</span><span class="tl-mi-v"></span></button>
    </div>
  `;

  const $ = (cls) => container.querySelector(cls);
  const chipzoneEl = $(".tl-chipzone");
  const searchEl = $(".tl-search");
  const previewEl = $(".tl-preview");
  const modeSeg = $(".tl-mode-seg");
  const nsfwBtn = $(".tl-nsfw-btn");
  const genderVal = $(".tl-gender-val");
  const genderItem = $('.tl-menu-item[data-act="gender"]');
  const conflictVal = $(".tl-conflict-val");
  const conflictItem = $('.tl-menu-item[data-act="conflict"]');
  const moreBtn = $(".tl-more-btn");
  const moreMenu = $(".tl-menu");

  /* ---------- mode (二态: 手动 / 自动) — 两模式界面相同, 自动=queue 时引擎填充 ---------- */
  // modeSyncedVal: 上次同步过的 widget 原始值。工作流加载/粘贴/撤销会在面板构建之后
  // 才写入 widget, 这里按值变化做幂等同步 (onDrawBackground 每帧调用, 值没变直接返回)。
  let modeSyncedVal = null;
  function syncModeWidgets() {
    const modeW = node.widgets?.find((x) => x.name === "mode");
    if (modeW) {
      if (modeW.value === modeSyncedVal) return;
      modeSyncedVal = modeW.value;
      ui.mode = modeW.value === "random_mix" ? "auto"
        : modeW.value === "random_by_category" ? "manual" : modeW.value;
    }
    modeSeg.querySelectorAll("button").forEach((b) =>
      b.classList.toggle("active", b.dataset.mode === ui.mode));
  }

  function setMode(m) {
    ui.mode = m;
    const modeW = node.widgets?.find((x) => x.name === "mode");
    if (modeW) { modeW.value = m; modeW.callback?.(m); }
    syncModeWidgets();
    renderAll();
    node.setDirtyCanvas?.(true);
  }

  /* ---------- 清空: 一键清掉当前节点显示的全部标签 ---------- */
  function doClearTags() {
    const st = getState(node);
    if (!(st.tags || []).length) return toast("当前没有标签可清空");
    setState(node, { tags: [] });
    ui.fillGroups = null;
    node._mutexDropped = null;
    renderTags();
    toast("已清空节点标签");
  };

  /* ---------- 预览模式: 简洁 / 带权重 / 调试 (在 ⋯ 菜单里循环) ---------- */
  const PV_MODES = ["simple", "weighted", "debug"];
  const PV_LABEL = { simple: "简洁", weighted: "带权重", debug: "调试" };
  const LANG_LABEL = { bilingual: "双语", en: "英文", zh: "中文" };

  function cyclePvMode() {
    const cur = getState(node).preview_mode || "simple";
    const next = PV_MODES[(PV_MODES.indexOf(cur) + 1) % PV_MODES.length];
    setState(node, { preview_mode: next });
    ui.previewMode = next;
    previewEl.textContent = outputPreview(getState(node).tags, next);
    renderMenuState();
    toast(`预览模式: ${PV_LABEL[next]}`);
  }

  /* ---------- nsfw (二态按钮: 默认关, 开=绿色) ---------- */
  function renderNsfw() {
    const on = getNsfwEffective(node);
    nsfwBtn.classList.toggle("on", on);
    container.dataset.nsfw = on ? "1" : "0";
  }

  function toggleNsfw() {
    const cur = getNsfwEffective(node);
    setState(node, { nsfw: !cur });
    renderNsfw();
    renderAll();
  }
  nsfwBtn.addEventListener("click", toggleNsfw);

  /* ---------- 性别三态 (关闭 ⚥ / 女性 ♀ 剔除男性专属 / 男性 ♂ 剔除女性专属) ---------- */
  function renderGender() {
    const g = getGender(node);
    genderVal.textContent = GENDER_LABEL[g];
    genderItem.title = GENDER_TITLE[g];
    genderItem.classList.toggle("on", g !== "off");
    genderItem.classList.toggle("g-female", g === "female");
    genderItem.classList.toggle("g-male", g === "male");
    container.dataset.gender = g;
  }
  function cycleGender() {
    const cur = getGender(node);
    const next = GENDER_SEQ[(GENDER_SEQ.indexOf(cur) + 1) % GENDER_SEQ.length];
    setState(node, { gender: next });
    renderGender();
    renderAll();
    toast(GENDER_TITLE[next]);
  }

  /* ----------Added-tags view ----------
     chipzone 现在只渲染 state.tags —— 用户从 ➕窗口 添加进来的标签。
     enabled=false -> 灰色停用 (不参与输出/随机); 点击变绿色启用。
  */

  // 缩放比例: 设置页 TagLibrary. chip_scale, 默认 100%
  function getScale() {
    const v = parseFloat(getSetting(SET_SCALE, 100));
    return Number.isNaN(v) ? 1 : Math.min(2, Math.max(0.5, v / 100));
  }

  function applyScale() {
    const s = getScale();
    container.style.fontSize = `${12 * s}px`;
    const fontOverride = parseInt(getSetting(SETTING_PREFIX + "chip_font_size", 0));
    const radius = parseInt(getSetting(SETTING_PREFIX + "chip_radius", 7));
    const root = document.documentElement.style;
    root.setProperty("--taglib-chip-scale", s);
    root.setProperty("--taglib-chip-font",
      (!Number.isNaN(fontOverride) && fontOverride > 0 ? fontOverride : null) || `${12 * s}px`);
    root.setProperty("--taglib-chip-radius", (!Number.isNaN(radius) ? radius : 7) + "px");
  }

  function renderTags() {
    const st = getState(node);
    chipzoneEl.innerHTML = "";
    const q = ui.filter.trim().toLowerCase();
    // 填充分组标题行: 最近一次 🎲填充/自动回显 的标签按大类分组显示。
    // ui.fillGroups 是内存态, 网页刷新后会丢 —— 从持久化在 state 里的 _cat 字段重建,
    // 修复"刷新后标签没有分类"的问题。
    let fillCats = ui.fillGroups instanceof Map && ui.fillGroups.size ? ui.fillGroups : null;
    if (!fillCats) {
      const m = new Map();
      for (const t of st.tags) {
        if (!t._cat) continue;
        if (!m.has(t._cat)) m.set(t._cat, []);
        m.get(t._cat).push(t);
      }
      if (m.size) fillCats = m;
    }
    const filledSet = new Set();
    if (fillCats) for (const list of fillCats.values()) for (const t of list) filledSet.add(t.en.toLowerCase());

    let shown = 0;
    let lastGroup = null;
    st.tags.forEach((t, idx) => {
      if (q && !(
        t.en.toLowerCase().includes(q) ||
        (t.zh || "").toLowerCase().includes(q))) return;
      shown++;
      // 填充标签按大类插入分组标题 (用户手动添加的排前面, 不受影响)
      if (fillCats && filledSet.has(t.en.toLowerCase())) {
        let grp = null;
        for (const [g, list] of fillCats.entries()) {
          if (list.some((x) => x.en.toLowerCase() === t.en.toLowerCase())) { grp = g; break; }
        }
        if (grp && grp !== lastGroup) {
          lastGroup = grp;
          const head = document.createElement("div");
          head.className = "tl-fill-group";
          const catIcon = PANEL_CATS.find((c) => c.name === grp)?.icon || "";
          head.textContent = `── ${catIcon ? catIcon + " " : ""}${grp} ──`;
          chipzoneEl.appendChild(head);
        }
      } else {
        lastGroup = null;
      }
      const el = document.createElement("span");
      const dropped = ui.mode === "auto" && node._mutexDropped?.has(String(t.en).toLowerCase());
      // 性别过滤剔除标记: ♀ 开启时男性专属 chip 灰显+删除线 (与后端输出/随机同规则)
      const gmode = getGender(node);
      const tg = tagGender(t);
      const gdrop = (gmode === "female" && tg === "male") || (gmode === "male" && tg === "female");
      el.className = "tl-ttag" + (t.enabled === false ? "" : " on") + (t.nsfw ? " nsfw" : "")
        + (tg ? " gender" : "") + (dropped ? " tl-dropped" : "") + (gdrop ? " tl-gdrop" : "");
      el.draggable = true;
      el.title = (t.enabled === false
        ? "已停用 — 点击启用"
        : (t.pinned ? "📌 已钉选 (随机/填充不覆盖) · 拖动排序 / ✕移除"
                    : "已启用 · 拖动排序 / 右键📌钉选 / ✕移除"))
        + (gdrop ? `\n⚧ 性别过滤中: 此${tg === "male" ? "男性" : "女性"}专属标签不会参与输出/随机/填充` : "");
      el.innerHTML =
        (t.pinned ? `<span class="tl-pin pinned" title="随机时必含">📌</span>` : ``) +
        `<b>${chipLabel(t)}</b>` +
        `<span class="tl-x" title="移除">✕</span>`;
      const pinEl = el.querySelector(".tl-pin");
      if (pinEl) pinEl.onclick = (e) => { e.stopPropagation(); togglePinIdx(idx); };
      el.querySelector(".tl-x").onclick = (e) => { e.stopPropagation(); removeTagIdx(idx); };
      el.onclick = () => toggleEnabledIdx(idx);
      el.oncontextmenu = (e) => {
        e.preventDefault();
        e.stopPropagation();
        // 右键菜单: 📌 钉选 (自动/填充不覆盖) / ✕ 移除 —— 单例复用, 不每次建 DOM
        openChipMenu(e.clientX, e.clientY, {
          pinned: !!t.pinned,
          onPin: () => togglePinIdx(idx),
          onRemove: () => removeTagIdx(idx),
        });
      };
      el.ondragstart = (e) => { e.dataTransfer.setData("text/plain", String(idx)); el.classList.add("dragging"); };
      el.ondragend = () => { el.classList.remove("dragging"); chipzoneEl.querySelectorAll(".drop-target").forEach((x) => x.classList.remove("drop-target")); };
      el.ondragover = (e) => { e.preventDefault(); el.classList.add("drop-target"); };
      el.ondragleave = () => el.classList.remove("drop-target");
      el.ondrop = (e) => {
        e.preventDefault();
        const from = parseInt(e.dataTransfer.getData("text/plain"));
        if (Number.isNaN(from) || from === idx) return;
        const cur = getState(node).tags.slice();
        const [moved] = cur.splice(from, 1);
        cur.splice(idx, 0, moved);
        setState(node, { tags: cur });
        renderTags();
      };
      chipzoneEl.appendChild(el);
    });

    if (!shown) {
      chipzoneEl.innerHTML = q
        ? `<div class="tl-empty">没有匹配 “${ui.filter}” 的已添加标签</div>`
        : `<div class="tl-empty">还没有添加标签<br/>点右上「➕ 添加标签」从库中挑选</div>`;
    }
    previewEl.textContent = outputPreview(st.tags, ui.previewMode);
  }

  // 当前会真正参与输出的标签 (与后端 _build_impl 同规则):
  // 启用 + NSFW 开 + 性别过滤后未被剔除。排除类目在 simple 预览里另行处理。
  function activeOutputTags(tags) {
    const g = getGender(node);
    const nsfwOn = getNsfwEffective(node);
    return (tags || []).filter((t) => {
      if (t.enabled === false) return false;
      if (t.nsfw && !nsfwOn) return false;
      const tg = tagGender(t);
      if (g === "female" && tg === "male") return false;
      if (g === "male" && tg === "female") return false;
      return true;
    });
  }

  function outputPreview(tags, mode) {
    mode = mode || getState(node).preview_mode || "simple";
    if (mode === "debug") {
      const enabledN = tags.filter((t) => t.enabled !== false).length;
      return `(调试) 共 ${tags.length} · 启用 ${enabledN} · 模式 ${ui.mode}`;
    }
    const act = activeOutputTags(tags);
    const weighted = mode === "weighted";
    const withW = act.filter((t) => t.weight && t.weight !== 1).length;
    if (weighted && withW) {
      const parts = act
        .map((t) => t.weight && t.weight !== 1 ? `${t.en} (×${t.weight})` : t.en);
      return parts.length ? "→ " + parts.join(", ") : "(无启用标签)";
    }
    return outputPreviewSimple(act);
  }

  function outputPreviewSimple(tags) {
    const st = getState(node);
    const ex = new Set(st.exclude_categories || []);
    // 三级排除: "大类" / "大类/子类" / "大类/子类/孙类" (与后端 tag_excluded 同规则)
    function isExcluded(en_l) {
      const path = LIB_PATH.get(en_l);
      if (!path) return false;
      const [cname, sname, gname] = path;
      if (ex.has(cname)) return true;
      if (gname && ex.has(`${cname}/${sname}/${gname}`)) return true;
      if (ex.has(`${cname}/${sname}`)) return true;
      return false;
    }
    const parts = tags
      .filter((t) => !isExcluded(t.en.toLowerCase()))
      .map((t) => t.en);
    return parts.length ? "→ " + parts.join(", ") : "(无启用标签)";
  }

  function toggleEnabledIdx(idx) {
    const st = getState(node);
    if (!st.tags[idx]) return;
    st.tags[idx].enabled = st.tags[idx].enabled === false;
    setState(node, { tags: st.tags });
    renderTags();
  }

  function removeTagIdx(idx) {
    const st = getState(node);
    st.tags.splice(idx, 1);
    setState(node, { tags: st.tags });
    renderTags();
  }

  function togglePinIdx(idx) {
    const st = getState(node);
    if (!st.tags[idx]) return;
    st.tags[idx].pinned = !st.tags[idx].pinned;
    setState(node, { tags: st.tags });
    renderTags();
  }

  /* 按库类目顺序稳定排序 (无类目/手动添加的排最前) — 钉选词不顶置, 随类目走 */
  function catOrderIdx(catName) {
    const i = PANEL_CATS.findIndex((c) => c.name === catName);
    return i === -1 ? 999 : i;
  }
  function tagCatOf(t) {
    if (t._cat) return t._cat;
    const p = LIB_PATH.get(String(t.en).toLowerCase());
    return (p && p[0]) || "";
  }
  function sortByCat(tags) {
    return tags
      .map((t, i) => [t, i])
      .sort((a, b) => {
        const ca = tagCatOf(a[0]);
        const cb = tagCatOf(b[0]);
        const ia = ca ? catOrderIdx(ca) : -1;
        const ib = cb ? catOrderIdx(cb) : -1;
        return ia - ib || a[1] - b[1];
      })
      .map((x) => x[0]);
  }
  function attachCat(t) {
    if (!t._cat) t._cat = tagCatOf(t);
    return t;
  }

  async function rollFill() {
    const st = getState(node);
    const nsfwOn = getNsfwEffective(node);
    const excluded = new Set(st.exclude_categories || []);
    const keepPins = true;  // 钉选必含常开 (设置开关已移除): 📌 标签填充时必保留且占子类目名额
    // ① 清空: 非"排除类目"的已有标签清掉; 📌钉选标签(必含开关开时)与排除类目标签保留
    const keptTags = st.tags.filter((t) => {
      if (keepPins && t.pinned) return true;
      const p = LIB_PATH.get(String(t.en).toLowerCase());
      return p && excluded.has(p[0]);
    }).map(attachCat);
    // 钉选占用所在子分类名额: (大类/子类) -> 已钉个数
    const pinnedBySub = new Map();
    if (keepPins) {
      for (const t of keptTags) {
        if (!t.pinned) continue;
        const p = LIB_PATH.get(String(t.en).toLowerCase());
        if (!p) continue;
        const k = `${p[0]}/${p[1]}`;
        pinnedBySub.set(k, (pinnedBySub.get(k) || 0) + 1);
      }
    }
    // ② 服务端真抽 (1.3.0): /taglib/api/draw 跑的就是节点执行的同一引擎 —
    //    组互斥/资源预算/状态槽/武器束全部后端算账, 面板不再有本地复刻漂移。
    const usedEn = new Set(keptTags.map((t) => t.en.toLowerCase()));
    let drawRes;
    try {
      drawRes = await fetch("/taglib/api/draw", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: { ...st, nsfw: nsfwOn },
                               seed: (getState(node).seed | 0) + Math.floor(Math.random() * 1000) }),
      }).then((r) => r.json());
    } catch (e) { console.warn("[taglib] draw 失败", e); return; }
    if (!drawRes?.ok) { console.warn("[taglib] draw 返回异常", drawRes); return; }
    const picked = [];
    for (const pk of drawRes.picks) {
      const lo = String(pk.en).toLowerCase();
      if (usedEn.has(lo)) continue;
      usedEn.add(lo);
      const item = { en: pk.en, zh: pk.zh || "", _cat: pk.cat || "", _auto: true, enabled: true };
      if (pk.ext) { item._bundle = pk.bundle; }   // 档案束成员 (武器姿势/配件), 芯片特殊标识
      if (pk.src === "implied") item._implied = true;
      picked.push(item);
    }
    if (!picked.length && !keptTags.some((t) => t.pinned)) return;
    // ③ 写回: 全部按库类目顺序排列 (钉选不顶置, 随类目走); 分组标题含钉选保留词
    const pinnedKept = keepPins ? keptTags.filter((t) => t.pinned && t._cat) : [];
    ui.fillGroups = groupByCat([...pinnedKept, ...picked]);
    setState(node, {
      tags: sortByCat([...keptTags, ...picked])
        .map((t) => ({ ...t, _auto: true, enabled: t.enabled !== false })),
    });
    renderTags();
    previewEl.textContent = outputPreview(getState(node).tags, ui.previewMode);
  }

  function groupByCat(tags) {
    // 按大类分组 (填充区显示分组标题)
    const groups = new Map();
    for (const t of tags) {
      const key = t._cat || "其他";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(t);
    }
    return groups;
  }

  /* ---------- 语言显示 ---------- */
  function getLang() { return getSetting(SET_LANG, "bilingual"); }

  function cycleLang() {
    const order = ["bilingual", "en", "zh"];
    const cur = getLang();
    const next = order[(order.indexOf(cur) + 1) % order.length];
    setSetting(SET_LANG, next);
    container.querySelector(".tl-lang-val").textContent = LANG_LABEL[next];
    // 全量重渲染: 已选标签 chip、填充分组、预览全部跟随语言
    renderAll();
  }

  function chipLabel(t) {
    const lang = getLang();
    const tg = tagGender(t);
    const gsym = tg === "female" ? '<span class="tl-gsym g-f">♀</span>'
               : tg === "male" ? '<span class="tl-gsym g-m">♂</span>' : "";
    const bsym = t._bundle ? '<span class="tl-bsym" title="武器档案束成员 (姿势/配件, 随武器出生)">⚔</span>' : "";
    if (lang === "en") return bsym + gsym + t.en;
    if (lang === "zh") return bsym + gsym + (t.zh || t.en);
    return bsym + gsym + `${t.en}${t.zh ? `<span style="opacity:.8;font-size:10px">${t.zh}</span>` : ""}`;
  }

  function renderConflictBtn() {
    const on = getState(node).avoid_conflicts !== false;
    conflictVal.textContent = on ? "已开启" : "已关闭";
    conflictItem.classList.toggle("on", on);
    conflictItem.title = on ? "防冲突已开启 (随机时同组互斥) — 点击关闭"
                            : "防冲突已关闭 — 点击开启";
  }

  function toggleConflict() {
    const cur = getState(node).avoid_conflicts !== false;
    setState(node, { avoid_conflicts: !cur });
    renderConflictBtn(); renderMenuState();
  }

  function renderAll() {
    renderTags(); renderNsfw(); renderGender(); renderConflictBtn(); renderMenuState();
  }

  /* ---------- ⋯ 更多菜单 ----------
     低频操作集中于此 (性别 / 防冲突 / 显示语言 / 预览模式 / 清空),
     同时充当"当前状态"的读数板; ⋯ 上小圆点提示有非默认项。 */
  function renderMenuState() {
    container.querySelector(".tl-lang-val").textContent =
      LANG_LABEL[getSetting(SET_LANG, "bilingual")] || "双语";
    container.querySelector(".tl-pv-val").textContent =
      PV_LABEL[getState(node).preview_mode || "simple"] || "简洁";
    // 语言/预览的效果在 chip 上可见; 性别与防冲突的效果不明显, 用圆点提示
    const dirty = getGender(node) !== "off" || getState(node).avoid_conflicts === false;
    moreBtn.classList.toggle("dirty", dirty);
  }

  function closeMoreMenu() {
    moreMenu.hidden = true;
  }
  moreBtn.onclick = (e) => {
    e.stopPropagation();
    if (moreMenu.hidden) {
      moreMenu.hidden = false;
      // 菜单是面板内的下拉, 关闭时机全部收在面板作用域内 —— 不用 document 级
      // 监听: 画布类页面里同一个 holder 会有多份渲染克隆, 全局监听会互相干扰,
      // 导致"刚打开就被关掉"。面板内 pointerdown 已经覆盖了所有真实操作路径。
      moreBtn.blur();
    } else {
      closeMoreMenu();
    }
  };
  // 点面板别处 / 再次点 ⋯ / 按 Esc -> 关闭
  container.addEventListener("pointerdown", (e) => {
    if (moreMenu.hidden) return;
    if (moreMenu.contains(e.target) || moreBtn.contains(e.target)) return;
    closeMoreMenu();
  });
  container.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !moreMenu.hidden) {
      closeMoreMenu();
      moreBtn.focus();
    }
  });
  moreMenu.querySelectorAll(".tl-menu-item").forEach((b) => {
    b.onclick = () => {
      const act = b.dataset.act;
      if (act === "gender") cycleGender();
      else if (act === "conflict") toggleConflict();
      else if (act === "lang") cycleLang();
      else if (act === "pv") cyclePvMode();
      else if (act === "clear") doClearTags();
      // 语言/预览模式改完留在菜单里, 方便看到值的变化
      if (act !== "lang" && act !== "pv") closeMoreMenu();
    };
  });

  // 全局偏好变更 -> 本节点面板实时跟随。
  // 本版本前端 extensionManager 没有 settings change 事件面 (setting/setting.settings
  // 均非 EventTarget, Pinia $subscribe 也不触发), 所以用轻量轮询兜底。
  // ⚠ 轮询是模块级单例: 一个定时器驱动所有面板, 不再是每个节点各起一个
  //   (旧实现多节点画布下开销线性叠加)。面板脱离 DOM 后自动注销。
  const unregisterSync = registerPanelSync(() => {
    if (!container.isConnected) { unregisterSync(); return; }
    applyScale(); renderAll();
  });

  /* ---------- ➕ 添加标签窗口 (全库挑选器) ---------- */
  async function openTagPicker() {
    // 挑选器需要标签正文 (全量库) -> 首次打开才拉; 面板本身只用轻量索引
    if (!LIB_CACHE) {
      toast("正在加载标签库…");
      try { await fetchLibrary(); } catch (e) { toast(`标签库加载失败: ${e.message}`, true); return; }
    }
    let dlg = document.getElementById("taglib-picker-dialog");
    if (dlg) { dlg.close(); dlg.remove(); }
    dlg = document.createElement("dialog");
    dlg.id = "taglib-picker-dialog";
    dlg.style.cssText =
      "width:min(92vw,1200px);height:min(90vh,860px);border:none;border-radius:14px;" +
      "padding:0;background:var(--tl-bg-solid);color:var(--tl-text);max-width:none;max-height:none;";
    // 翻译免疫 (同面板): 防止挑选器里的标签英文被翻译扩展改写
    dlg.classList.add("p-inputtext", "notranslate", "tl-scope");
    dlg.setAttribute("translate", "no");
    dlg.innerHTML = `<div id="taglib-picker-root" style="width:100%;height:100%;overflow:hidden"></div>`;
    document.body.appendChild(dlg);
    dlg.showModal();
    const handle = mountTagPicker(dlg.querySelector("#taglib-picker-root"), {
      onCancel: () => dlg.close(),
      onConfirm: (picked) => {
        // picked: [{en, zh?, nsfw?}] -> 追加到 state.tags
        const st = getState(node);
        const have = new Set(st.tags.map((t) => t.en.toLowerCase()));
        for (const p of picked) {
          if (!have.has(p.en.toLowerCase())) {
            st.tags.push({ ...p, enabled: true });
            have.add(p.en.toLowerCase());
          }
        }
        setState(node, { tags: st.tags });
        renderTags();
        dlg.close();
      },
      getExisting: () => new Set(getState(node).tags.map((t) => t.en.toLowerCase())),
      getExcluded: () => getState(node).exclude_categories || [],
      setExcluded: (cats) => { setState(node, { exclude_categories: cats }); },
      onNodeState: renderAll,
      onGlobalChange: () => { applyScale(); renderAll(); },
      node,
    });
    // 点弹窗外遮罩 = 关闭 (与管理页一致); 移除与收尾统一走 close 事件
    dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
    dlg.addEventListener("close", () => {
      handle.destroy?.();
      dlg.remove();
      if (handle.libTouched()) {
        // 内嵌管理页可能改过库 -> 刷新缓存, 全部节点面板跟随
        invalidateLibraryCache();
        fetchPanelIndex().then(renderAll);
        window.dispatchEvent(new CustomEvent("taglib-updated"));
      }
    });
  }

  /* ---------- 随机设置 (原 ⚙ 弹窗) 已并入「添加标签 → ⚙ 设置」页签 ---------- */

  /* ---------- events ---------- */
  container.querySelector('[data-act="addtags"]').onclick = openTagPicker;
  container.querySelector('[data-act="roll"]').onclick = rollFill;
  searchEl.oninput = () => { ui.filter = searchEl.value; renderTags(); };
  modeSeg.querySelectorAll("button").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));

  /* ---------- init ---------- */
  applyScale();
  syncModeWidgets();
  // 面板只拉轻量索引 (分类/路径/标记); 含正文的全量库留给挑选器懒加载
  fetchPanelIndex()
    .then(renderAll)
    .catch((err) => { container.innerHTML = `<div class="tl-empty">标签库加载失败: ${err}</div>`; });

  return {
    syncMode: syncModeWidgets,  // 工作流加载/外部改 mode 后, 面板按钮与 widget 重新对齐
    refresh: async (opts = {}) => {
      // reloadLib 仅在库真的变了时用 (管理页保存/热同步导入);
      // 每轮队列的自动回显刷新不重拉, 避免无谓的请求
      if (opts.reloadLib) {
        invalidateLibraryCache();
        await fetchPanelIndex();
      }
      applyScale();
      // executed 回显预存的分组数据 → 应用到 ui.fillGroups
      if (node._taglibPendingGroups instanceof Map) {
        ui.fillGroups = node._taglibPendingGroups;
        node._taglibPendingGroups = null;
      }
      renderAll();
    },
  };
}

/* --------------------------------------------- tag picker (全库挑选器) */

function mountTagPicker(rootEl, { onCancel, onConfirm, onNodeState, onGlobalChange, getExisting, getExcluded, setExcluded, node }) {
  const ui = { activeCat: null, filter: "", picked: [], tab: "pick", libTouched: false };  // pick | exclude | settings

  rootEl.innerHTML = `
    <style>
      /* 颜色全部走 .tl-scope 主题变量 (tagpanel-css.js) —— 深浅主题同一份样式 */
      .tp-wrap { display:flex; flex-direction:column; height:100%; color:var(--tl-text);
                 font:12.5px/1.5 "Segoe UI","Microsoft YaHei",sans-serif; }
      .tp-head { display:flex; align-items:center; gap:8px; padding:12px 16px; border-bottom:1px solid var(--tl-border); }
      .tp-head h2 { margin:0; font-size:15px; white-space:nowrap; }
      .tp-search { flex:1; min-width:150px; max-width:420px; background:var(--tl-input-bg);
                   border:1px solid var(--tl-border-2); border-radius:8px; color:var(--tl-text);
                   padding:6px 12px; outline:none; font-size:12.5px; }
      .tp-search:focus { border-color:color-mix(in srgb, var(--tl-accent) 60%, transparent); }
      .tp-cols { flex:1; display:flex; min-height:0; }
      .tp-cats { width:200px; border-right:1px solid var(--tl-border); overflow-y:auto;
                 padding:10px; display:flex; flex-direction:column; gap:4px; }
      .tp-cat { display:flex; align-items:center; gap:7px; padding:7px 10px; border-radius:9px;
                cursor:pointer; border:1px solid transparent; transition:.12s; color:var(--tl-text-2); }
      .tp-cat.tp-cat-l0 { color:var(--tl-text); }
      .tp-cat:focus-visible { outline:2px solid color-mix(in srgb, var(--tl-accent) 70%, transparent); outline-offset:1px; }
      .tp-cat:hover { background:var(--tl-hover); }
      .tp-cat.active { background:color-mix(in srgb, currentColor 14%, transparent); border-color:currentColor; }
      .tp-cat .nm { flex:1; }
      .tp-cat .ct { font-size:11px; color:var(--tl-muted); }
      .tp-chev { cursor:pointer; opacity:.7; }
      .tp-chev:hover { opacity:1; }
      .tp-chips { flex:1; overflow-y:auto; padding:14px 16px; }
      .tp-sub { font-size:11px; color:var(--tl-muted); margin:10px 0 6px; letter-spacing:.03em; }
      .tp-grid { display:flex; flex-wrap:wrap; gap:5px; }
      .tp-tag { --c:var(--tl-accent);
        border:1px solid color-mix(in srgb, var(--c) 30%, var(--tl-border-2));
        background:color-mix(in srgb, var(--c) 8%, var(--tl-card));
        border-radius:8px; padding:3px 10px; cursor:pointer; font-size:12px;
        transition:.12s; color:var(--tl-text); }
      .tp-tag:hover { background:color-mix(in srgb, var(--c) 20%, transparent); transform:translateY(-1px); }
      .tp-tag:focus-visible { outline:2px solid color-mix(in srgb, var(--c) 70%, transparent); outline-offset:1px; }
      .tp-tag.picked { background:var(--c); color:#fff; box-shadow:0 0 8px -2px var(--c); }
      .tp-tag.picked::before { content:"✓ "; }
      .tp-tag.dim { opacity:.38; }
      .tp-tag.nsfw { --c:#e5484d; }
      .tp-tag.gender { border-style:dashed; }
      .tp-tag .tl-gsym { font-weight:700; margin-right:2px; }
      .tp-tag .tl-gsym.g-f { color:#ff6b9d; }
      .tp-tag .tl-gsym.g-m { color:var(--tl-accent); }
      .tp-foot { display:flex; align-items:center; gap:10px; padding:11px 16px; border-top:1px solid var(--tl-border); }
      .tp-count { font-size:13px; font-weight:600; color:var(--tl-accent); }
      .tp-btn { border:1px solid var(--tl-border-2); background:var(--tl-card); color:inherit;
                border-radius:8px; padding:7px 18px; cursor:pointer; font-size:13px; }
      .tp-btn:hover { background:var(--tl-hover); }
      .tp-btn:focus-visible { outline:2px solid color-mix(in srgb, var(--tl-accent) 70%, transparent); outline-offset:1px; }
      .tp-btn.primary { background:color-mix(in srgb, var(--tl-accent) 22%, transparent);
                        border-color:color-mix(in srgb, var(--tl-accent) 55%, transparent); font-weight:600; }
      .tp-btn.primary:hover { background:color-mix(in srgb, var(--tl-accent) 32%, transparent); }
      .tp-tabbtn { border:1px solid var(--tl-border-2); background:transparent; color:var(--tl-text-2);
                   border-radius:8px; padding:5px 12px; cursor:pointer; font-size:12.5px; white-space:nowrap; }
      .tp-tabbtn:hover { background:var(--tl-hover); }
      .tp-tabbtn.active { background:color-mix(in srgb, var(--tl-accent) 18%, transparent);
                          border-color:color-mix(in srgb, var(--tl-accent) 50%, transparent);
                          color:var(--tl-accent-text); }
      .tp-exc-card { display:flex; align-items:center; gap:10px; padding:9px 13px; margin-bottom:6px;
                     border:1px solid var(--tl-border); border-radius:10px; background:var(--tl-card-2); }
      .tp-exc-card.excluded { border-color:rgba(255,107,107,.55); background:rgba(255,71,87,.10); }
      .tp-exc-card .nm { flex:1; font-size:13px; }
      .tp-exc-card .why { font-size:11px; color:var(--tl-danger-soft); }
      .tp-exc-hint { font-size:12px; color:var(--tl-muted); margin-bottom:12px; line-height:1.6; }
      .tp-master { border:1px solid color-mix(in srgb, var(--tl-accent) 35%, transparent);
                   background:color-mix(in srgb, var(--tl-accent) 8%, transparent);
                   border-radius:10px; padding:10px; margin-bottom:8px; }
      .tp-range { display:inline-flex; align-items:center; gap:4px; }
      .tp-range input { width:44px; background:var(--tl-input-bg); border:1px solid var(--tl-border-2);
                        border-radius:6px; color:var(--tl-text); padding:3px 5px; font-size:11.5px; text-align:center; }
      .tp-range-hint { font-size:10.5px; color:var(--tl-dim); margin-top:5px; }
      .tp-empty { color:var(--tl-muted); }
      /* ---------- 行内编辑控件 (档案 / 互斥域 / NL 三视图共用) ---------- */
      .tp-ecell { background:var(--tl-input-bg); border:1px solid var(--tl-border-2); border-radius:6px;
                  color:var(--tl-text); font-size:11.5px; padding:3px 6px; outline:none; min-width:0; }
      .tp-ecell:focus { border-color:color-mix(in srgb, var(--tl-accent) 60%, transparent); }
      .tp-ecell.wide { flex:1 1 160px; min-width:160px; }
      .tp-ecell.num { width:44px; text-align:center; }
      .tp-echip { display:inline-flex; align-items:center; gap:5px; }
      .tp-echip-x { cursor:pointer; opacity:.5; font-style:normal; font-size:10px; }
      .tp-echip-x:hover { opacity:1; color:var(--tl-danger); }
      .tp-echip-add { background:transparent; border:1px dashed var(--tl-border-2); border-radius:7px;
                      color:var(--tl-text-2); font-size:11px; padding:3px 8px; outline:none; min-width:96px; }
      .tp-echip-add:focus { border-color:var(--tl-accent); }
      .tp-edel { background:transparent; border:1px solid var(--tl-border-2); color:var(--tl-muted);
                 border-radius:6px; cursor:pointer; font-size:11px; padding:1px 7px; }
      .tp-edel:hover { color:var(--tl-danger); border-color:var(--tl-danger); }
      .tp-eadd { background:color-mix(in srgb, var(--tl-accent) 12%, transparent); cursor:pointer;
                 border:1px solid color-mix(in srgb, var(--tl-accent) 45%, transparent);
                 color:var(--tl-accent-text); border-radius:7px; padding:3px 11px; font-size:11.5px; }
      .tp-eadd:hover { background:color-mix(in srgb, var(--tl-accent) 24%, transparent); }
      .tp-erow { display:flex; gap:8px; margin-top:8px; }
      .tp-savebox { margin:16px 0 4px; }
      .tp-save { background:var(--tl-accent); border:0; color:#fff; border-radius:8px;
                 padding:6px 20px; cursor:pointer; font-weight:600; font-size:12.5px; }
      .tp-save:hover { filter:brightness(1.12); }
      .tp-smsg { margin-left:10px; font-size:11.5px; }
      .tp-gitem2 { border:1px solid var(--tl-border); border-radius:10px; padding:8px 12px; margin-bottom:6px;
                   background:var(--tl-card-2); }
      .tp-gitem2-h { display:flex; align-items:center; gap:8px; }
      .tp-gitem2-h .tp-ecell { flex:0 0 auto; }
      .tp-gitem2-h .tp-gn { margin-left:auto; color:var(--tl-muted); font-size:11px; }
      .tp-fam-edit { display:flex; align-items:center; gap:6px; margin-bottom:3px; }
      .tp-fam-edit .tp-ecell { flex:1; }
      /* ---------- 排除抽屉 (侧栏内, 窄容器 -> 覆盖全宽视图的尺寸) ---------- */
      .tp-exc { margin-top:10px; border-top:1px solid var(--tl-border); padding-top:6px; flex:0 0 auto; }
      .tp-exc > summary { cursor:pointer; font-size:11.5px; font-weight:600; color:var(--tl-text-2); padding:3px 2px; }
      .tp-exc-body { padding:4px 0; max-height:44vh; overflow-y:auto; }
      .tp-exc-body .tp-exc-hint { font-size:10.5px; line-height:1.55; margin-bottom:6px; }
      .tp-exc-body .tp-exc-card { gap:6px; padding:4px 6px; margin-bottom:0; font-size:11.5px; border-radius:6px; }
      .tp-exc-body .tp-exc-card .nm { font-size:11.5px; }
      .tp-exc-body .tp-exc-card .why { font-size:10px; }
      .tp-exc-body .tp-exc-card .tp-chev { cursor:pointer; }
      /* 轴/槽位行首的启用开关 (关掉 = 加入排除列表, 抽取时整条跳过) */
      .tp-row-tog { width:13px; height:13px; flex:0 0 auto; cursor:pointer;
                    accent-color: var(--tl-accent); margin:0 1px 0 0; }
      /* 段位分隔标题 (Anima tag order 的六段) */
      .tp-sec-head { font-size:10px; font-weight:700; letter-spacing:.06em; color:var(--tl-accent-text);
                     opacity:.85; padding:9px 4px 3px; margin-top:2px;
                     border-top:1px solid var(--tl-border); }
      .tp-sec-head:first-of-type { border-top:0; margin-top:0; padding-top:2px; }
      /* ---- 设置页 (可折叠分区) ---- */
      .tp-set-sec { margin:0 0 10px; }
      .tp-set-sec > summary { cursor:pointer; font-size:12px; font-weight:700; color:var(--tl-accent-text);
                              letter-spacing:.05em; padding:6px 0; list-style:none; user-select:none; }
      .tp-set-sec > summary::-webkit-details-marker { display:none; }
      .tp-set-sec > summary::before { content:"▸ "; color:var(--tl-muted); font-weight:400; }
      .tp-set-sec[open] > summary::before { content:"▾ "; }
      .tp-set-sec > summary:hover { filter:brightness(1.15); }
      .tp-set-sec .sub { color:var(--tl-dim); font-weight:400; font-size:11px; }
      .tp-set-card { max-width:560px; border:1px solid var(--tl-border); border-radius:12px;
                     background:var(--tl-card-2); padding:14px 16px; margin-bottom:6px; }
      .tp-set-row { margin-bottom:13px; }
      .tp-set-row:last-child { margin-bottom:0; }
      .tp-set-lab { font-size:12px; color:var(--tl-text-2); margin-bottom:4px; }
      .tp-set-hint { font-size:11px; color:var(--tl-dim); margin-top:3px; line-height:1.5; }
      .tp-set-row select, .tp-set-row input[type="text"], .tp-set-row input[type="number"] {
        background:var(--tl-input-bg); border:1px solid var(--tl-border-2); border-radius:8px;
        color:var(--tl-text); padding:6px 9px; font-size:12.5px; outline:none;
      }
      .tp-set-row select:focus, .tp-set-row input:focus { border-color:color-mix(in srgb, var(--tl-accent) 55%, transparent); }
      .tp-set-row input[type="checkbox"] { width:15px; height:15px; accent-color:var(--tl-accent); }
      .tp-sync-note { font-size:11px; color:var(--tl-dim); margin-top:14px; line-height:1.6; max-width:560px; }
      /* ---- 防冲突关系页 ---- */
      .tp-cf-stats { font-size:12px; color:var(--tl-text-2); margin-bottom:12px; }
      .tp-cf-list { display:flex; flex-direction:column; gap:6px; margin-bottom:20px; }
      .tp-cf-rule { display:flex; align-items:center; gap:8px; flex-wrap:wrap;
        border:1px solid var(--tl-border); border-radius:10px;
        background:var(--tl-card-2); padding:8px 12px; font-size:12.5px; }
      .tp-cf-rule .cf-l { font-weight:600; color:var(--tl-accent-text); }
      .tp-cf-rule .cf-vs { color:var(--tl-muted); }
      .tp-cf-rule .cf-rt { border:1px solid var(--tl-border-2); border-radius:6px;
        padding:1px 7px; font-size:11.5px; color:var(--tl-text-2); }
      .tp-cf-rule .cf-note { color:var(--tl-dim); font-size:11px; }
      .tp-cf-rule .cf-warn { color:var(--tl-danger); font-size:11px; }
      .tp-cf-rule .cf-del { margin-left:auto; background:transparent; cursor:pointer;
        border:1px solid rgba(255,107,107,.4); color:var(--tl-danger-soft); border-radius:6px;
        padding:2px 8px; font-size:11px; }
      .tp-cf-rule .cf-del:hover { background:rgba(255,71,87,.15); }
      .tp-cf-h { font-size:12px; font-weight:700; color:var(--tl-accent-text); margin:16px 0 10px; }
      .tp-cf-form { border:1px solid var(--tl-border); border-radius:12px;
        background:var(--tl-card-2); padding:14px 16px; max-width:640px; }
      .tp-cf-frow { display:flex; align-items:center; gap:8px; margin-bottom:10px; flex-wrap:wrap; }
      .tp-cf-frow .cf-klab { font-size:11.5px; color:var(--tl-muted); width:52px; }
      .tp-cf-frow select, .tp-cf-frow input {
        background:var(--tl-input-bg); border:1px solid var(--tl-border-2); border-radius:8px;
        color:var(--tl-text); padding:5px 9px; font-size:12px; outline:none; }
      .tp-cf-frow input:focus { border-color:color-mix(in srgb, var(--tl-accent) 55%, transparent); }
      .tp-cf-add { border:1px solid color-mix(in srgb, var(--tl-accent) 50%, transparent);
        background:color-mix(in srgb, var(--tl-accent) 12%, transparent);
        color:var(--tl-accent-text); border-radius:7px; padding:4px 12px; cursor:pointer; font-size:12px; }
      .tp-cf-add:hover { background:color-mix(in srgb, var(--tl-accent) 22%, transparent); }
      .tp-cf-rights { display:flex; flex-wrap:wrap; gap:5px; margin:4px 0 10px 60px; min-height:24px; }
      .tp-cf-rights .cf-rt-chip { display:inline-flex; align-items:center; gap:5px;
        border:1px solid rgba(46,204,113,.45); background:rgba(46,204,113,.08);
        border-radius:6px; padding:1px 7px; font-size:11.5px; }
      .tp-cf-rights .cf-rt-chip .x { cursor:pointer; opacity:.6; }
      .tp-cf-rights .cf-rt-chip .x:hover { opacity:1; color:var(--tl-danger); }
      .tp-cf-save { background:var(--tl-accent); border:0; color:#fff; border-radius:8px;
        padding:6px 18px; cursor:pointer; font-weight:600; font-size:12.5px; }
      .tp-cf-save:hover { filter:brightness(1.12); }
      .tp-glist { margin-bottom:6px; }
      .tp-vm { flex:1; padding:5px 0; font-size:11.5px; border-radius:7px; cursor:pointer;
               border:1px solid var(--tl-border); background:var(--tl-card); color:var(--tl-text-2); }
      .tp-vm:hover { background:var(--tl-hover); }
      .tp-vm.active { background:color-mix(in srgb, var(--tl-accent) 18%, transparent);
                      border-color:color-mix(in srgb, var(--tl-accent) 50%, transparent); color:var(--tl-accent-text); }
      .tp-axis-head { font-size:12.5px; color:var(--tl-accent-text); font-weight:600; }
      .tp-axis-n { opacity:.55; font-weight:400; }
      .tp-axis-hint { font-size:10px; color:var(--tl-warn); font-weight:400; margin-left:8px; }
      .tp-tag.bundled { border-style:dashed; border-color:color-mix(in srgb, var(--tl-warn) 55%, transparent); }
      .tp-h1 { font-size:15px; font-weight:700; color:var(--tl-text); margin-bottom:6px; }
      .tp-h1-sub { font-size:11px; color:var(--tl-muted); font-weight:400; margin-left:8px; }
      .tp-note { font-size:11.5px; color:var(--tl-text-3); line-height:1.65; margin-bottom:12px;
                 background:var(--tl-card-2); border:1px solid var(--tl-border);
                 border-radius:8px; padding:8px 12px; }
      .tp-pcard { background:var(--tl-card); border:1px solid var(--tl-border);
                  border-radius:10px; padding:12px 14px; margin-bottom:12px; }
      .tp-pcard.err { border-color:rgba(255,107,107,.5); }
      .tp-pcard-h { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:6px; }
      .tp-pcard-h code { color:var(--tl-accent-text); font-size:11px; }
      .tp-pbadges { margin-left:auto; display:flex; gap:5px; }
      .tp-b { font-size:10px; padding:2px 7px; border-radius:99px; background:var(--tl-card); color:var(--tl-text-2); }
      .tp-b.ok { background:rgba(125,212,125,.14); color:var(--tl-ok); }
      .tp-b.warn { background:rgba(240,163,94,.16); color:var(--tl-warn); }
      .tp-prow { display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin:4px 0; }
      .tp-pl { font-size:10.5px; color:var(--tl-muted); min-width:44px; }
      .tp-chip { font-size:10.5px; padding:2px 8px; border-radius:6px;
                 background:color-mix(in srgb, var(--tl-accent) 12%, transparent); color:var(--tl-accent-text); }
      .tp-ptab { width:100%; border-collapse:collapse; margin-top:8px; font-size:11px; }
      .tp-ptab th { text-align:left; color:var(--tl-muted); font-weight:500; padding:4px 8px;
                    border-bottom:1px solid var(--tl-border); }
      .tp-ptab td { padding:4px 8px; border-bottom:1px solid var(--tl-border); color:var(--tl-text-2); }
      .tp-ptab code { color:var(--tl-accent-text); }
      .tp-ptab tr.extra td { background:color-mix(in srgb, var(--tl-warn) 5%, transparent); }
      .tp-ptab .dim { color:var(--tl-muted); font-size:10px; }
      .tp-gitem { border:1px solid var(--tl-border); border-radius:8px; margin-bottom:6px; background:var(--tl-card-2); }
      .tp-gitem summary { cursor:pointer; padding:7px 12px; font-size:11.5px; color:var(--tl-text-2); }
      .tp-gitem summary code { color:var(--tl-accent-text); }
      .tp-gn { color:var(--tl-muted); font-size:10.5px; margin-left:8px; }
      .tp-gmem { padding:6px 14px 10px; display:flex; flex-wrap:wrap; gap:5px; }
      .tp-gmem .tp-chip { background:var(--tl-card); color:var(--tl-text-2); }
      .tp-gsearch { background:var(--tl-input-bg); border:1px solid var(--tl-border-2); border-radius:8px;
                    color:var(--tl-text); padding:6px 10px; font-size:12px; outline:none; }
      .tp-fam { margin-bottom:10px; }
      .tp-fam-h { font-size:12px; color:var(--tl-accent-text); margin-bottom:3px; }
      .tp-fam-s { font-size:11.5px; color:var(--tl-text-2); padding:2px 0 2px 16px; }
      .tp-jsonbox { margin-top:14px; border:1px solid var(--tl-border); border-radius:8px; }
      .tp-jsonbox summary { padding:8px 12px; font-size:12px; color:var(--tl-text-2); cursor:pointer; }
      .tp-jsonbox textarea { width:calc(100% - 24px); margin:0 12px; background:var(--tl-code-bg);
                             color:var(--tl-text-2); border:1px solid var(--tl-border); border-radius:6px;
                             font-family:Consolas,monospace; font-size:11px; padding:8px; box-sizing:border-box; }
      .tp-jrow { padding:8px 12px 12px; display:flex; align-items:center; gap:10px; }
      .tp-jsave { background:var(--tl-accent); border:0; color:#fff; border-radius:8px;
                  padding:6px 16px; cursor:pointer; font-weight:600; font-size:12px; }
      .tp-jsave:hover { filter:brightness(1.12); }
      .tp-jmsg { font-size:11.5px; }
      .tp-zh { opacity:.55; font-size:10px; margin-left:3px; }
      .tp-chip .tp-zh { margin-left:2px; }
      .tp-langbtn { border:1px solid var(--tl-border-2); background:var(--tl-card); color:var(--tl-text-2);
                    border-radius:6px; font-size:10.5px; padding:1px 7px; cursor:pointer;
                    margin-left:8px; vertical-align:2px; }
      .tp-langbtn.en { color:var(--tl-warn); border-color:color-mix(in srgb, var(--tl-warn) 50%, transparent); }
      .tp-arrow { color:var(--tl-accent); margin:0 4px; }
    </style>
    <div class="tp-wrap">
      <div class="tp-head">
        <h2>🏷 从标签库添加</h2>
        <button class="tp-tabbtn tp-picktab active">挑标签</button>
        <button class="tp-tabbtn tp-proftab">⚔ 武器档案</button>
        <button class="tp-tabbtn tp-grptab">🧬 互斥域</button>
        <button class="tp-tabbtn tp-nltab">✍ NL 句式</button>
        <button class="tp-tabbtn tp-settab">⚙ 设置</button>
        <input class="tp-search" placeholder="🔍 搜中文 / 英文 / 别名…" />
        <span style="flex:1"></span>
      </div>
      <div class="tp-cols">
        <aside class="tp-cats"></aside>
        <section class="tp-chips"><div class="tp-empty" style="padding:40px;text-align:center;color:#8b93a5">加载中…</div></section>
        <section class="tp-profview" style="display:none;flex:1;overflow-y:auto;padding:16px 22px;"></section>
        <section class="tp-grpview" style="display:none;flex:1;overflow-y:auto;padding:16px 22px;"></section>
        <section class="tp-nlview" style="display:none;flex:1;overflow-y:auto;padding:16px 22px;"></section>
        <section class="tp-setview" style="display:none;flex:1;overflow-y:auto;padding:16px 22px;"></section>
      </div>
      <div class="tp-foot">
        <span class="tp-footinfo">已挑选 <b class="tp-count">0</b> 个</span>
        <span style="flex:1"></span>
        <button class="tp-btn tp-cancel">取消</button>
        <button class="tp-btn primary tp-ok">✔ 确定并保存</button>
        <button class="tp-btn tp-close2" style="display:none">✕ 关闭</button>
      </div>
    </div>
  `;

  const $ = (s) => rootEl.querySelector(s);
  const catsBox = $(".tp-cats");
  const chipsBox = $(".tp-chips");
  const searchEl = $(".tp-search");
  const countEl = $(".tp-count");

  function libCats() { return (LIB_CACHE && LIB_CACHE.categories) || []; }

  /* ---------- 三级侧栏树: 大类(可折叠) > 子分类 > 孙分类 + 抽取范围设置 ----------
     1.3.0: 顶栏可切 视图模式 — 分类树(浏览皮肤) / 拼装轴(引擎本体)。轴模式下
     标签按 axis 字段聚合 (一词可跨面), 武器姿势词带 ⚔ 标记。 */
  const AXES_ZH = {
    meta: "💎 画质规格", count: "👥 人数", character: "🧿 角色身份",
    artist: "🎨 画师",
    appearance: "🎨 外貌特征", clothing: "👗 服装", prop: "🧰 道具武器",
    action: "🤸 动作姿态", environment: "🏞 场景环境", lighting: "💡 光影",
    camera: "🎬 镜头构图", style: "🖌 风格媒介", material: "✨ 材质特效",
    misc: "📦 未归类",
  };
  // 段位 (与 py 侧 axes.AXIS_SECTION 一一对应) —— Anima 官方 tag order 的六段。
  // 轴列表按**段位序**展示, 让用户直接看到"输出时各轴落在哪一段"。
  const AXIS_SECTION = {
    meta: 1, style: 1, count: 2, character: 3, artist: 5,
    appearance: 6, clothing: 6, prop: 6, action: 6,
    environment: 6, lighting: 6, camera: 6, material: 6, misc: 9,
  };
  const SECTION_ZH = {
    1: "① 质量 · 元信息 · 风格", 2: "② 人数", 3: "③ 角色",
    4: "④ 作品", 5: "⑤ 画师", 6: "⑥ 通用", 9: "⑨ 未归类",
  };
  // 轴的中文名 → 轴 id (与 py 侧 axes.AXIS_NAME_ZH 对应)
  const AXIS_ZH_TO_ID = {
    "画质规格": "meta", "人数": "count", "角色身份": "character", "画师": "artist",
    "外貌特征": "appearance", "服装": "clothing", "道具武器": "prop",
    "动作姿态": "action", "场景环境": "environment", "光影氛围": "lighting",
    "构图镜头": "camera", "风格媒介": "style", "材质特效": "material",
  };
  const AXIS_ORDER = ["meta", "style", "count", "character", "artist", "appearance",
                      "clothing", "prop", "action", "environment", "lighting",
                      "camera", "material", "misc"];

  function eachTag(lib, fn) {
    for (const c of lib.categories || [])
      for (const s of c.subcategories || [])
        for (const t of s.tags || []) fn(t, c, s);
  }
  function renderCatsInner() {
    catsBox.innerHTML = "";
    if (!ui.openAxes) ui.openAxes = new Set();
    const st = getState(node);
    const master = st.fill_master ?? true;
    const tmin = st.total_min ?? 40;
    const tmax = st.total_max ?? 60;
    const excludedSet = new Set(getExcluded() || []);
    const isEx = (k) => excludedSet.has(k);
    // 开关 = 写 exclude_categories。轴/槽位/孙类三级同一套路径, 与引擎的 _migrate_excludes 对齐。
    const toggleEx = (key, on, parentKey) => {
      const cur = new Set(getExcluded() || []);
      if (on) { cur.delete(key); }
      else {
        cur.add(key);
        if (!parentKey) for (const k of [...cur]) if (k.startsWith(key + "/")) cur.delete(k);
        else cur.delete(parentKey);        // 关子级时清掉父级整条排除
      }
      setExcluded([...cur]);
      renderCats();
    };

    const allCount = libCats().reduce((n2, c) => n2 + countTags(c), 0);

    // ---- 总预算 ----
    const masterBox = document.createElement("div");
    masterBox.className = "tp-master";
    masterBox.innerHTML = `
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none">
        <input type="checkbox" class="tp-master-sw" ${master ? "checked" : ""}
          style="width:14px;height:14px;accent-color:#54a0ff"/>
        <b style="font-size:12px">自动配额</b>
      </label>
      <div class="tp-range" style="${master ? "" : "opacity:.35"}">
        <input type="number" class="tp-total-min" min="0" max="200" value="${tmin}"/>
        <span>~</span>
        <input type="number" class="tp-total-max" min="0" max="300" value="${tmax}"/>
      </div>
      <div class="tp-range-hint">全库共出 ${tmin}~${tmax} 个词 · 各槽位配额已内置<br>
        关掉此开关则改为逐槽位自定义</div>`;
    catsBox.appendChild(masterBox);
    masterBox.querySelector(".tp-master-sw").onchange = (e) => {
      setState(node, { fill_master: e.target.checked });
      renderCats();
    };
    const saveMaster = () => {
      const mn = parseInt(masterBox.querySelector(".tp-total-min").value) || 0;
      const mx = parseInt(masterBox.querySelector(".tp-total-max").value) || 0;
      const lo = Math.min(200, Math.max(0, Math.min(mn, mx)));
      const hi = Math.min(300, Math.max(0, Math.max(mn, mx)));
      setState(node, { total_min: lo, total_max: hi });
      masterBox.querySelector(".tp-range-hint").innerHTML =
        `全库共出 ${lo}~${hi} 个词 · 各槽位配额已内置<br>关掉此开关则改为逐槽位自定义`;
    };
    masterBox.querySelector(".tp-total-min").onchange = saveMaster;
    masterBox.querySelector(".tp-total-max").onchange = saveMaster;

    // ---- 全部 ----
    mkRow(catsBox, {
      id: "__all__", icon: "🎯", name: "全部", count: allCount, depth: 0,
      active: !ui.activeAxis && !ui.activeSlot,
      onclick: () => { ui.activeAxis = null; ui.activeSlot = null; renderCats(); renderChips(); },
    });

    // ---- 段位 → 轴 → 槽位 → 孙类 (单一视图) ----
    // 库里的轴顺序是编辑顺序, 未必等于输出段位序 (例如 style 是第 1 段却排在库里最后),
    // 不排序会让段位标题重复出现 (①…⑥…①…)。这里按 (段位, AXIS_ORDER) 排。
    const axCats = libCats().slice().sort((x, y) => {
      const sx = AXIS_SECTION[AXIS_ZH_TO_ID[x.name]] || 6;
      const sy = AXIS_SECTION[AXIS_ZH_TO_ID[y.name]] || 6;
      if (sx !== sy) return sx - sy;
      return AXIS_ORDER.indexOf(AXIS_ZH_TO_ID[x.name]) - AXIS_ORDER.indexOf(AXIS_ZH_TO_ID[y.name]);
    });
    let curSec = 0;
    for (const c of axCats) {
      const aId = AXIS_ZH_TO_ID[c.name] || "";
      const sec = AXIS_SECTION[aId] || 6;
      if (sec !== curSec) {
        const h = document.createElement("div");
        h.className = "tp-sec-head";
        h.textContent = SECTION_ZH[sec] || `第 ${sec} 段`;
        catsBox.appendChild(h);
        curSec = sec;
      }
      const cEx = isEx(c.name);
      const open = ui.openAxes.has(c.name);
      const axTotal = (c.subcategories || []).reduce((n2, s2) => n2 + (s2.tags || []).length, 0);
      mkRow(catsBox, {
        id: c.id, icon: c.icon || "📁",
        name: c.name + (cEx ? " · 已关" : ""), count: axTotal,
        depth: 0, color: c.color, chevron: true, open,
        active: ui.activeAxis === aId && !ui.activeSlot,
        toggle: { on: !cEx, title: cEx ? "整条轴已关闭 (抽取时跳过)" : "点击关闭整条轴",
                  onToggle: (on) => toggleEx(c.name, on, null) },
        onclick: () => { ui.activeAxis = aId; ui.activeSlot = null; renderCats(); renderChips(); },
        onchevron: () => { open ? ui.openAxes.delete(c.name) : ui.openAxes.add(c.name); renderCats(); },
      });
      if (!open) continue;
      for (const sub of c.subcategories || []) {
        const key = `${c.name}/${sub.name}`;
        const sEx = cEx || isEx(key);
        const subRange = (st.fill_sub_ranges || {})[sub.id] || { min: 1, max: 1 };
        mkRow(catsBox, {
          id: sub.id, name: sub.name + (sEx ? " · 已关" : ""), count: (sub.tags || []).length,
          depth: 1, active: ui.activeSlot === sub.name,
          toggle: { on: !sEx, title: cEx ? "所属轴已关闭" : (isEx(key) ? "该槽位已关闭" : "点击关闭该槽位"),
                    onToggle: (on) => toggleEx(key, on, c.name) },
          range: cEx ? { min: 0, max: 0, locked: true } : subRange,
          onRange: (mn, mx) => {
            const all = { ...(getState(node).fill_sub_ranges || {}) };
            all[sub.id] = { min: mn, max: mx };
            setState(node, { fill_sub_ranges: all });
          },
          onclick: () => { ui.activeAxis = aId; ui.activeSlot = sub.name; renderCats(); renderChips(); },
        });
        for (const g of sub.groups || []) {
          const gkey = `${c.name}/${sub.name}/${g.name}`;
          const gEx = sEx || isEx(gkey);
          mkRow(catsBox, {
            id: g.id, name: g.name + (gEx ? " · 已关" : ""), count: (g.tags || []).length,
            depth: 2, active: false,
            toggle: { on: !gEx, title: sEx ? "所属槽位已关闭" : "点击关闭该孙分类",
                      onToggle: (on) => toggleEx(gkey, on, null) },
            onclick: () => { ui.activeAxis = aId; ui.activeSlot = sub.name; renderCats(); renderChips(); },
          });
        }
      }
    }
  }


  function mkRow(box, { id, icon = "", name, count, depth, color, chevron, open, active, onclick, onchevron, range, onRange, toggle, leaf }) {
    const el = document.createElement("div");
    el.className = "tp-cat tp-cat-l" + depth + (active ? " active" : "");
    // 分类自带色 (用户自定义) 才内联; 未配置时交给 CSS 变量 → 深浅主题自动适配
    if (color) el.style.color = color;
    if (depth === 1) el.style.paddingLeft = "22px";
    if (depth === 2) el.style.paddingLeft = "38px";
    const rangeHtml = range ? `
      <span class="tp-range" style="${range.locked ? "opacity:.35" : ""}">
        <input type="number" min="0" max="20" value="${range.min}" data-r="min" ${range.locked ? "disabled" : ""}/>
        <span>~</span>
        <input type="number" min="0" max="20" value="${range.max}" data-r="max" ${range.locked ? "disabled" : ""}/>
      </span>` : "";
    el.innerHTML =
      (toggle ? `<input type="checkbox" class="tp-row-tog" ${toggle.on ? "checked" : ""}`
                + ` title="${toggle.title || "启用/关闭"}" style="margin-right:2px"/>` : "") +
      `${chevron ? `<span class="tp-chev">${open ? "▾" : "▸"}</span>` : (depth > 0 ? '<span class="tp-chev">·</span>' : "")}` +
      `<span>${icon}</span><span class="nm">${name}</span><span class="ct">${count}</span>` +
      rangeHtml;
    const togEl = el.querySelector(".tp-row-tog");
    if (togEl) {
      togEl.onclick = (e) => { e.stopPropagation(); };
      togEl.onchange = (e) => { e.stopPropagation(); toggle.onToggle(!toggle.on); };
    }
    el.onclick = onclick;
    if (onchevron) {
      el.querySelector(".tp-chev").onclick = (e) => { e.stopPropagation(); onchevron(); };
    }
    if (range && onRange) {
      el.querySelectorAll(".tp-range input").forEach((inp) => {
        inp.onclick = (e) => e.stopPropagation();
        inp.onchange = () => {
          const mn = parseInt(el.querySelector('[data-r="min"]').value) || 0;
          const mx = parseInt(el.querySelector('[data-r="max"]').value) || 0;
          onRange(Math.min(20, Math.max(0, mn)), Math.min(20, Math.max(0, mx)));
        };
      });
    }
    box.appendChild(el);
  }

  function findColor(id) {
    return (libCats().find((c) => c.id === id) || {}).color;
  }

  function countTags(cat) {
    let n = 0;
    for (const s of cat.subcategories || []) n += (s.tags || []).length;
    return n;
  }

  function matches(t) {
    // NSFW 关 = 挑选器直接隐藏 nsfw 标签 (与填充/输出同规则)
    if (t.nsfw && !getNsfwEffective(node)) return false;
    // 性别过滤同规则: 女性=隐藏男性专属, 男性=隐藏女性专属
    const g = getGender(node);
    if (g === "female" && t.gender === "male") return false;
    if (g === "male" && t.gender === "female") return false;
    const q = ui.filter.trim().toLowerCase();
    if (!q) return true;
    return t.en.toLowerCase().includes(q) ||
           (t.zh || "").toLowerCase().includes(q) ||
           (t.aliases || []).some((a) => a.toLowerCase().includes(q));
  }

  let WEAPON_POSES = null;   // 武器档案束成员词集 (⚔ 标记用), 懒加载一次
  async function fetchWeaponPoses() {
    if (WEAPON_POSES) return;
    try {
      const r = await fetch("/taglib/api/profiles");
      const d = await r.json();
      WEAPON_POSES = new Set((d.weapon_poses || []).map((x) => x.toLowerCase()));
    } catch { WEAPON_POSES = new Set(); }
  }

  /* 按轴分桶 —— 全库遍历一次后缓存 (库对象变了才重建)。
     旧实现每次渲染轴视图都重新遍历 4300+ 词。 */
  let _axisBuckets = null;
  let _axisBucketSrc = null;
  function axisBucketsOf(lib) {
    if (_axisBuckets && _axisBucketSrc === lib) return _axisBuckets;
    const byAxis = {};
    eachTag(lib, (t, c, s) => {
      const a = t.axis || "misc";
      (byAxis[a] = byAxis[a] || []).push({ t, c, s });
    });
    _axisBuckets = byAxis;
    _axisBucketSrc = lib;
    return byAxis;
  }

  function renderAxisChips() {
    chipsBox.innerHTML = "";
    const existing = getExisting();
    const lib = LIB_CACHE || { categories: [] };
    const byAxis = axisBucketsOf(lib);
    fetchWeaponPoses().finally(() => {
      let shown = 0;
      for (const a of AXIS_ORDER) {
        if (ui.activeAxis && ui.activeAxis !== a) continue;
        const rows = (byAxis[a] || []).filter((r) =>
          matches(r.t) && (!ui.activeSlot || (r.s && r.s.name === ui.activeSlot)));
        if (!rows.length) continue;
        shown += rows.length;
        const head = document.createElement("div");
        head.className = "tp-sub tp-axis-head";
        head.innerHTML = `${AXES_ZH[a] || a} <span class="tp-axis-n">${rows.length}</span>`
          + (a === "prop" || a === "action" ? ` <span class="tp-axis-hint">⚔=武器档案束成员, 随武器自动出生</span>` : "");
        chipsBox.appendChild(head);
        const grid = document.createElement("div");
        grid.className = "tp-grid";
        for (const { t, c, s } of rows) {
          grid.appendChild(chipEl(t, c, s, existing));
        }
        chipsBox.appendChild(grid);
      }
      if (!shown) chipsBox.innerHTML = `<div class="tp-empty" style="padding:40px;text-align:center;color:#8b93a5">没找到匹配的标签</div>`;
    });
  }

  function chipEl(t, c, s, existing) {
    const isPicked = ui.picked.some((p) => p.en.toLowerCase() === t.en.toLowerCase());
    const isExisting = existing.has(t.en.toLowerCase());
    const isBundled = WEAPON_POSES && WEAPON_POSES.has(t.en.toLowerCase());
    const el = document.createElement("span");
    el.className = "tp-tag" + (t.nsfw ? " nsfw" : "") + (t.gender ? " gender" : "")
      + (isPicked ? " picked" : "") + (isExisting ? " dim" : "")
      + (isBundled ? " bundled" : "");
    if (isExisting) { el.title = "已在节点上"; el.style.opacity = ".38"; }
    else {
      el.title = (isBundled ? "⚔ 武器档案束成员 (抽中武器自动带出, 一般无需手点)\n" : "")
        + (t.nsfw ? "🔞 NSFW 标签"
          : t.gender === "female" ? "♀ 女性专属标签"
          : t.gender === "male" ? "♂ 男性专属标签" : "")
        + `\n轴: ${AXES_ZH[t.axis || "misc"] || t.axis} · 槽位: ${s.name}`;
      el.onclick = () => {
        const i = ui.picked.findIndex((p) => p.en.toLowerCase() === t.en.toLowerCase());
        if (i >= 0) ui.picked.splice(i, 1);
        else ui.picked.push({ en: t.en, zh: t.zh, nsfw: !!t.nsfw, gender: t.gender || "" });
        countEl.textContent = ui.picked.length;
        el.classList.toggle("picked", i < 0);
      };
    }
    el.innerHTML = (isBundled ? '<span class="tl-bsym">⚔</span>' : "")
      + (t.gender === "female" ? '<span class="tl-gsym g-f">♀</span>'
        : t.gender === "male" ? '<span class="tl-gsym g-m">♂</span>' : "")
      + `${t.en}${t.zh ? `<span style="opacity:.55"> ${t.zh}</span>` : ""}`;
    return el;
  }
  function renderChips() {
    // v1.6.2: 树视图已删除 —— 只有"段位序"一种显示方式 (轴=引擎真实结构)。
    renderAxisChips();
  }


  function appendGrid(hits, clr, existing) {
    const grid = document.createElement("div");
    grid.className = "tp-grid";
    for (const t of hits) {
      grid.appendChild(chipEl(t, { name: "", icon: "" }, { name: "" }, existing));
    }
    chipsBox.appendChild(grid);
  }

  /* ---------- 排除类目视图 ---------- */
  const pickCols = [".tp-cats", ".tp-chips"].map((s) => rootEl.querySelector(s));

  function upstreamText() {
    // 收集上游 prefix 文本 (已连线的输入 widget / 上游节点预览)
    let text = "";
    try {
      for (const inp of node?.inputs || []) {
        if (inp.name !== "prefix" || !inp.link) continue;
        const link = window.app?.graph?.links?.get?.(inp.link) || window.app?.graph?.links?.[inp.link];
        const srcNode = link ? window.app.graph._nodes.find((x) => x.id === link.origin_id) : null;
        const srcW = srcNode?.widgets?.find((w) => w.name === "text" || w.name === "prompt");
        if (srcW?.value) text += " " + srcW.value;
      }
    } catch {}
    return text.toLowerCase();
  }

  function suggestExcludes() {
    const up = upstreamText();
    if (!up) return {};
    const hints = {};
    const RULE = [
      ["发型发色", ["hair", "bangs", "ponytail", "twintails", "braid", "bob cut", "short hair", "long hair"]],
      ["五官", ["eyes", "blue eyes", "green eyes", "red eyes", "pointed ears", "heterochromia"]],
      ["表情情绪", ["smile", "smirk", "crying", "blush", "open mouth", "closed mouth", "angry", "sad"]],
      ["服装", ["dress", "uniform", "hoodie", "kimono", "skirt", "bikini", "swimsuit", "jacket", "shirt"]],
      ["动作姿态", ["sitting", "standing", "lying", "kneeling", "arms", "walking", "running"]],
      ["配饰", ["glasses", "hat", "necklace", "earrings", "gloves", "ribbon"]],
      ["构图镜头", ["close-up", "from above", "from below", "portrait", "wide shot", "cowboy shot"]],
      ["光影氛围", ["backlighting", "rim light", "dappled", "sunlight", "moonlight", "neon"]],
      ["场景环境", ["bedroom", "classroom", "outdoors", "forest", "beach", "city", "street"]],
      ["风格媒介", ["anime style", "photorealistic", "oil painting", "watercolor"]],
    ];
    for (const [catName, keys] of RULE) {
      const hit = keys.filter((k) => up.includes(k));
      if (hit.length) hints[catName] = hit.slice(0, 3);
    }
    return hints;
  }

  /* v1.6.0: 排除抽屉接在侧栏末尾 —— renderCats 的两个分支都有 return, 故外层包一层 */
  function renderCats() {
    renderCatsInner();
    renderExclude();
  }

  /* ---------- 排除: 三级粒度 ----------
     exclude_categories 里可放:
       "大类名"          -> 整类排除
       "大类名/子分类名"  -> 排除某个子分类
       "大类名/子分类名/孙分类名" -> 排除某个孙分类
  */
  function excKeys() { return new Set(getExcluded ? getExcluded() : []); }

  function catFullyExcluded(cat, ex) {
    return ex.has(cat.name);
  }

  function subExcluded(cat, sub, ex) {
    if (ex.has(cat.name)) return true;
    return ex.has(`${cat.name}/${sub.name}`);
  }

  function groupExcluded(cat, sub, g, ex) {
    if (subExcluded(cat, sub, ex)) return true;
    return ex.has(`${cat.name}/${sub.name}/${g.name}`);
  }

  function tagExcluded(catName, sub, g, en_l, ex) {
    if (ex.has(catName)) return true;
    if (g && ex.has(`${catName}/${sub.name}/${g.name}`)) return true;
    if (ex.has(`${catName}/${sub.name}`)) return true;
    return false;
  }

  function renderExclude() {
    const ex = excKeys();
    const hints = suggestExcludes();
    // 目标改为侧栏底部的可折叠抽屉 (原「🚫 排除类目」页签已删)
    let host = catsBox.querySelector(".tp-exc");
    if (!host) {
      host = document.createElement("details");
      host.className = "tp-exc";
      catsBox.appendChild(host);
    }
    const excN = (getExcluded ? getExcluded().length : 0);
    host.innerHTML = `<summary>🚫 排除类目 <span class="tp-gn">${excN ? excN + " 项" : "无"}</span></summary>
      <div class="tp-exc-body"></div>`;
    const body = host.querySelector(".tp-exc-body");
    body.innerHTML = `
      <div class="tp-exc-hint">
        勾选要<b>排除</b>的层级: 可排除<b>整类</b>, 也可展开后只排除<b>子分类</b>或<b>孙分类</b>。<br/>
        排除后随机抽取与输出都会跳过对应标签。上游已有发色/眼睛等描述时 (如 <code>blue hair, blue eyes</code>),
        排除对应层级避免冲突。
        ${Object.keys(hints).length ? '<br/>💡 检测到上游提示词可能已包含以下内容 (粉色标记): ' + Object.entries(hints).map(([k, v]) => `<b>${k}</b>(${v.join(",")})`).join(" ") : ""}
      </div>
    `;
    for (const cat of libCats()) {
      if (cat.id === "nsfwcat") continue;
      const isEx = catFullyExcluded(cat, ex);
      const why = hints[cat.name] ? `上游已有: ${hints[cat.name].join(", ")}` : "";
      const card = document.createElement("div");
      card.className = "tp-exc-card" + (isEx ? " excluded" : "");
      card.innerHTML = `
        <input type="checkbox" ${isEx ? "checked" : ""} style="width:16px;height:16px;accent-color:#ff4757"/>
        <span>${cat.icon || ""}</span>
        <span class="nm">${cat.name}<span style="color:#8b93a5;font-size:11px"> · ${countTags(cat)} 条</span></span>
        <span class="why">${why}</span>
        <span class="tp-chev tp-exc-toggle">${ui.excOpen?.has(cat.id) ? "▾" : "▸"}</span>
      `;
      card.querySelector("input").onchange = (e2) => {
        const cur = excKeys();
        if (e2.target.checked) {
          cur.add(cat.name);
          // 清掉该类下更细的排除项 (整类排除已覆盖)
          for (const k of [...cur]) if (k.startsWith(cat.name + "/")) cur.delete(k);
        } else {
          cur.delete(cat.name);
        }
        setExcluded([...cur]);
        renderExclude();
      };
      card.querySelector(".tp-exc-toggle").onclick = () => {
        if (!ui.excOpen) ui.excOpen = new Set();
        ui.excOpen.has(cat.id) ? ui.excOpen.delete(cat.id) : ui.excOpen.add(cat.id);
        renderExclude();
      };
      body.appendChild(card);

      // 子分类层 (展开时)
      if (ui.excOpen?.has(cat.id) && !isEx) {
        for (const sub of cat.subcategories || []) {
          const subEx = subExcluded(cat, sub, ex);
          const subCard = document.createElement("div");
          subCard.className = "tp-exc-card" + (subEx ? " excluded" : "");
          subCard.style.cssText = "margin-left:26px;padding:6px 12px;";
          subCard.innerHTML = `
            <input type="checkbox" ${subEx ? "checked" : ""} style="width:14px;height:14px;accent-color:#ff4757"/>
            <span class="nm">${sub.name}<span style="color:#8b93a5;font-size:11px"> · ${(sub.tags || []).length}</span></span>
            ${(sub.groups || []).length ? `<span class="tp-chev tp-exc-toggle2">${ui.excOpenSub?.has(sub.id) ? "▾" : "▸"}</span>` : ""}
          `;
          subCard.querySelector("input").onchange = (e2) => {
            const cur = excKeys();
            const key = `${cat.name}/${sub.name}`;
            if (e2.target.checked) {
              cur.add(key);
              for (const k of [...cur]) if (k.startsWith(key + "/")) cur.delete(k);
              // 整类勾会被此子项替代 -> 若全部子类都被排除提示用户可直接排除整类
              cur.delete(cat.name);
            } else {
              cur.delete(key);
            }
            setExcluded([...cur]);
            renderExclude();
          };
          body.appendChild(subCard);
          const t2 = subCard.querySelector(".tp-exc-toggle2");
          if (t2) t2.onclick = () => {
            if (!ui.excOpenSub) ui.excOpenSub = new Set();
            ui.excOpenSub.has(sub.id) ? ui.excOpenSub.delete(sub.id) : ui.excOpenSub.add(sub.id);
            renderExclude();
          };
          // 孙分类层
          if (ui.excOpenSub?.has(sub.id) && !subEx) {
            for (const g of sub.groups || []) {
              const gEx = groupExcluded(cat, sub, g, ex);
              const gCard = document.createElement("div");
              gCard.className = "tp-exc-card" + (gEx ? " excluded" : "");
              gCard.style.cssText = "margin-left:52px;padding:5px 10px;";
              gCard.innerHTML = `
                <input type="checkbox" ${gEx ? "checked" : ""} style="width:13px;height:13px;accent-color:#ff4757"/>
                <span class="nm" style="font-size:12px">${g.name}<span style="color:#8b93a5"> · ${(g.tags || []).length}</span></span>
              `;
              gCard.querySelector("input").onchange = (e2) => {
                const cur = excKeys();
                const key = `${cat.name}/${sub.name}/${g.name}`;
                e2.target.checked ? cur.add(key) : cur.delete(key);
                cur.delete(`${cat.name}/${sub.name}`);
                cur.delete(cat.name);
                setExcluded([...cur]);
                renderExclude();
              };
              body.appendChild(gCard);
            }
          }
        }
      }
    }
  }

  /* ---------- 页签: 挑标签 | 排除类目 | 设置 ---------- */
  const setView = $(".tp-setview");

  function refreshLibIfTouched() {
    if (!ui.libTouched) return;
    ui.libTouched = false;
    invalidateLibraryCache();   // 两级缓存一起清: 面板索引 + 挑选器全量库
    Promise.all([fetchLibrary(), fetchPanelIndex()])
      .then(() => { renderCats(); renderChips(); });
  }

  /* ---------- 设置页: 节点参数(原⚙弹窗) + 全局偏好(与 ComfyUI 设置双向同步) ---------- */
  function renderSettingsView() {
    const st = getState(node);
    // 全局值读取 (旧版三模式值归一化为现行二态)
    const rawMode = getSetting(SET_DEFAULT_MODE, "manual");
    const gMode = rawMode === "random_mix" ? "auto" : rawMode === "random_by_category" ? "manual" : (rawMode === "auto" ? "auto" : "manual");
    const gNsfw = !!getSetting(SET_DEFAULT_NSFW, false);
    const gScale = getSetting(SET_SCALE, 100);
    const gFont = getSetting(SETTING_PREFIX + "chip_font_size", 0);
    const gRadius = getSetting(SETTING_PREFIX + "chip_radius", 7);
    const gLang = getSetting(SET_LANG, "bilingual");
    const row = (label, inner, hint) => `
      <div class="tp-set-row">
        <div class="tp-set-lab">${label}</div>
        ${inner}
        ${hint ? `<div class="tp-set-hint">${hint}</div>` : ""}
      </div>`;
    setView.innerHTML = `
      <details class="tp-set-sec" open>
      <summary>节点参数 <span class="sub">· 存入当前节点, 随工作流保存</span></summary>
      <div class="tp-set-card">
        ${row("输出分隔符", `<select class="sv-sep">
            <option value="comma" ${(st.separator ?? "comma") === "comma" ? "selected" : ""}>逗号 , (推荐)</option>
            <option value="space" ${st.separator === "space" ? "selected" : ""}>空格</option>
          </select>`)}
        ${row("权重语法 (tag:1.2)", `<input type="checkbox" class="sv-w" ${st.use_weights_syntax ? "checked" : ""}/>`,
          "开启后权重≠1 的标签输出为 (tag:权重) 形式")}
        ${row("去重", `<input type="checkbox" class="sv-dd" ${st.dedupe !== false ? "checked" : ""}/>`,
          "相同标签只输出一次")}
        ${row("组合随机过滤词", `<input type="text" class="sv-search" value="${(st.search_text || "").replace(/"/g, "&quot;")}" placeholder="留空 = 全库抽取"/>`,
          "只从匹配的标签里随机 (支持中文/英文/别名)")}
      </div>
      </details>
      <details class="tp-set-sec" open>
      <summary>1.3.0 引擎 <span class="sub">· 组互斥/资源算账/武器束/NL 尾段</span></summary>
      <div class="tp-set-card">
        ${row("自然语言尾段", `<input type="checkbox" class="sv-nltail" ${st.nl_tail !== false ? "checked" : ""}/>`,
          "输出末尾追加 2~4 句连贯英文描述 (句式随 seed 变, 关掉=纯标签)")}
        ${row("武器带姿势概率", `<input type="number" class="sv-bundleprob" min="0" max="100" step="5" value="${Math.round((st.bundle_pose_prob ?? 0.85) * 100)}"/>`,
          "% · 抽中武器时自动带出该武器一条姿势的概率")}
        ${row("同时武器上限", `<input type="number" class="sv-maxweap" min="1" max="4" step="1" value="${st.max_weapons ?? 2}"/>`,
          "超过后新武器不再配姿势 (手部资源有限, 背着一把再举一把没有意义)")}
        ${row("配件出生概率", `<input type="number" class="sv-extrprob" min="0" max="100" step="5" value="${Math.round((st.extra_prob ?? 0.35) * 100)}"/>`,
          "% · 武器档案的配件 (刀鞘/箭袋/镜) 随武器出现的概率")}
      </div>
      </details>
      <details class="tp-set-sec" open>
      <summary>全局偏好 <span class="sub">· 与 ComfyUI 设置面板「标签库」双向同步</span></summary>
      <div class="tp-set-card">
        ${row("新节点的默认模式", `<select class="sv-gmode">
            <option value="manual" ${gMode === "manual" ? "selected" : ""}>手动</option>
            <option value="auto" ${gMode === "auto" ? "selected" : ""}>自动</option>
          </select>`)}
        ${row("默认启用 NSFW 标签", `<input type="checkbox" class="sv-gnsfw" ${gNsfw ? "checked" : ""}/>`,
          "关闭时隐藏并排除 NSFW 标签; 也可在每个节点上单独开关")}
        ${row("整体比例 (%) — 按钮/字体等内部 UI 缩放", `<input type="number" class="sv-gscale" min="50" max="200" step="5" value="${gScale}"/>`,
          "100% = 默认大小; 影响面板内所有按钮/字体/chip 大小")}
        ${row("标签字号覆盖 (px, 0=跟随比例)", `<input type="number" class="sv-gfont" min="0" max="24" step="1" value="${gFont}"/>`)}
        ${row("标签圆角 (px)", `<input type="number" class="sv-grad" min="0" max="16" step="1" value="${gRadius}"/>`)}
        ${row("标签文字显示", `<select class="sv-glang">
            <option value="bilingual" ${gLang === "bilingual" ? "selected" : ""}>双语 (英文+中文)</option>
            <option value="en" ${gLang === "en" ? "selected" : ""}>仅英文</option>
            <option value="zh" ${gLang === "zh" ? "selected" : ""}>仅中文</option>
          </select>`,
          "输出永远只有英文; 这里只控制面板里标签按钮的显示文字")}
      </div>
      </details>
      <div class="tp-sync-note">💡 节点参数即改即存; 全局偏好写入 ComfyUI 设置 (设置面板搜「标签库」是同一批值, 两边改都生效)。</div>
    `;
    // 节点参数: 即改即存 + 让节点面板实时跟随
    const saveNode = (patch) => { setState(node, patch); onNodeState?.(); };
    $(".sv-sep").onchange = (e) => saveNode({ separator: e.target.value });
    $(".sv-w").onchange = (e) => saveNode({ use_weights_syntax: e.target.checked });
    $(".sv-dd").onchange = (e) => saveNode({ dedupe: e.target.checked });
    $(".sv-search").onchange = (e) => saveNode({ search_text: e.target.value.trim() });
    const clampPct = (v, d) => Math.min(100, Math.max(0, parseInt(v) ?? d)) / 100;
    $(".sv-nltail").onchange = (e) => saveNode({ nl_tail: e.target.checked });
    $(".sv-bundleprob").onchange = (e) => saveNode({ bundle_pose_prob: clampPct(e.target.value, 85) });
    $(".sv-maxweap").onchange = (e) => saveNode({ max_weapons: Math.min(4, Math.max(1, parseInt(e.target.value) || 2)) });
    $(".sv-extrprob").onchange = (e) => saveNode({ extra_prob: clampPct(e.target.value, 35) });
    // 全局偏好: 写入 ComfyUI 设置 (官方持久化) + 当前面板即时跟随; 其他节点由轮询跟进
    const saveGlobal = (id, value) => { setSetting(id, value); onGlobalChange?.(); };
    $(".sv-gmode").onchange = (e) => saveGlobal(SET_DEFAULT_MODE, e.target.value);
    $(".sv-gnsfw").onchange = (e) => saveGlobal(SET_DEFAULT_NSFW, e.target.checked);
    $(".sv-gscale").onchange = (e) => saveGlobal(SET_SCALE, Math.min(200, Math.max(50, parseInt(e.target.value) || 100)));
    $(".sv-gfont").onchange = (e) => saveGlobal(SETTING_PREFIX + "chip_font_size", Math.min(24, Math.max(0, parseInt(e.target.value) || 0)));
    $(".sv-grad").onchange = (e) => saveGlobal(SETTING_PREFIX + "chip_radius", Math.min(16, Math.max(0, parseInt(e.target.value) || 7)));
    $(".sv-glang").onchange = (e) => saveGlobal(SET_LANG, e.target.value);
  }

  /* ---------- 🧷 防冲突关系页签 ---------- */

  /* ---------- 1.3.0 新视图: 武器档案 / 互斥域 / NL 句式 ---------- */
  const profView = $(".tp-profview");
  const grpView = $(".tp-grpview");
  const nlView = $(".tp-nlview");

  function editorFoot(scope, apiUrl, getData) {
    const ta = scope.querySelector(".tp-json");
    const btn = scope.querySelector(".tp-jsave");
    const msg = scope.querySelector(".tp-jmsg");
    if (btn) btn.onclick = async () => {
      let payload;
      try { payload = JSON.parse(ta.value); }
      catch (e) { msg.textContent = "❌ JSON 解析失败: " + e.message; msg.style.color = "var(--tl-danger)"; return; }
      btn.disabled = true; msg.textContent = "保存中…"; msg.style.color = "var(--tl-muted)";
      try {
        const r = await fetch(apiUrl, { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(getData(payload)) });
        const d = await r.json();
        if (d.ok) { msg.textContent = "✅ 已保存, 引擎即时生效"; msg.style.color = "var(--tl-ok)"; WEAPON_POSES = null; }
        else { msg.textContent = "❌ " + String(d.error || JSON.stringify(d.errors || "")).slice(0, 160); msg.style.color = "var(--tl-danger)"; }
      } catch (e) { msg.textContent = "❌ " + e.message; msg.style.color = "var(--tl-danger)"; }
      btn.disabled = false;
    };
  }

  /* ---------- 行内编辑原语 (档案 / 互斥域 / NL 三个视图共用) ----------
     三个视图的共同点: 一个实体列表 + 每个实体若干字段 + 字段里可能嵌子列表。
     统一在这里提供原语, 避免每个视图各写一套只读渲染 + JSON 兜底。
     规则: 先改内存工作副本, 点保存才落盘; 结构性改动 (增删行) 立即重绘。 */

  function tagDatalistHtml() {
    const opts = [];
    for (const c of libCats()) for (const s of c.subcategories || []) for (const t of s.tags || []) opts.push(t.en);
    return `<datalist id="tp-tagdl">${opts.map((v) => `<option value="${esc(String(v))}"/>`).join("")}</datalist>`;
  }

  function subDatalistHtml() {
    const opts = [];
    for (const c of libCats()) for (const s of c.subcategories || []) opts.push(`${c.name}/${s.name}`);
    return `<datalist id="tp-subdl">${opts.map((v) => `<option value="${esc(String(v))}"/>`).join("")}</datalist>`;
  }

  /** 可编辑 chip 列表: 每个 chip 带 ✕, 末尾一个回车即加的输入框。 */
  function fillChips(container, arr, onChange, datalistId) {
    container.innerHTML = "";
    arr.forEach((v, i) => {
      const c = document.createElement("span");
      c.className = "tp-chip tp-echip";
      c.innerHTML = `${bi(v)}<i class="tp-echip-x" title="移除">✕</i>`;
      c.querySelector(".tp-echip-x").onclick = () => { arr.splice(i, 1); onChange(); };
      container.appendChild(c);
    });
    const inp = document.createElement("input");
    inp.className = "tp-echip-add";
    inp.placeholder = "＋ 回车添加";
    if (datalistId) inp.setAttribute("list", datalistId);
    inp.onkeydown = (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const v = inp.value.trim();
      if (!v) return;
      if (!arr.some((x) => String(x).toLowerCase() === v.toLowerCase())) arr.push(v);
      onChange();
    };
    container.appendChild(inp);
  }

  function saveBarHtml(label) {
    return `<div class="tp-jrow"><button class="tp-save">💾 ${label}</button><span class="tp-smsg"></span></div>`;
  }

  async function postJson(apiUrl, payload, msgEl, okText) {
    msgEl.textContent = "保存中…"; msgEl.style.color = "var(--tl-muted)";
    try {
      const r = await fetch(apiUrl, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (d.ok) {
        msgEl.textContent = okText || "✅ 已保存, 引擎即时生效";
        msgEl.style.color = "var(--tl-ok)";
        WEAPON_POSES = null;
        return true;
      }
      msgEl.textContent = "❌ " + String(d.error || JSON.stringify(d.errors || "")).slice(0, 200);
      msgEl.style.color = "var(--tl-danger)";
      return false;
    } catch (e) {
      msgEl.textContent = "❌ " + e.message; msgEl.style.color = "var(--tl-danger)";
      return false;
    }
  }

  /** 把一行 input 的值写回实体字段。data-f 指定字段名。 */
  function applyFieldInput(t, f, el) {
    let v = el.value;
    if (f === "hands" || f === "gaze" || f === "weight") {
      const n = parseFloat(v);
      t[f] = Number.isFinite(n) ? n : (f === "weight" ? 1 : 0);
      return;
    }
    v = String(v).trim();
    if (f === "tags") {
      t[f] = v ? v.split(/[,，]/).map((x) => x.trim()).filter(Boolean) : [];
      return;
    }
    if (f === "state_slot") {
      const o = {};
      for (const kv of v.split(/[,，]/)) {
        const m2 = kv.split("=");
        if (m2.length >= 2) o[m2[0].trim()] = m2.slice(1).join("=").trim();
      }
      t[f] = Object.keys(o).length ? o : undefined;
      if (!t[f]) delete t[f];
      return;
    }
    if (v) t[f] = v; else delete t[f];
  }

  /** 在容器内统一绑定: 单元格变更 / 删除按钮 / 新增按钮。
   *  getEntity(pi, k, xi) -> 要修改的对象; data-k 为空表示改档案本体。 */
  function bindEditable(scope, { getEntity, onStructural }) {
    scope.querySelectorAll("input[data-f]").forEach((el) => {
      el.onchange = () => {
        const pi = Number(el.dataset.p);
        const xi = el.dataset.x === undefined ? null : Number(el.dataset.x);
        const t = getEntity(pi, el.dataset.k || "", xi);
        if (t) applyFieldInput(t, el.dataset.f, el);
      };
    });
    scope.querySelectorAll(".tp-edel").forEach((b) => {
      b.onclick = () => { onStructural("del", Number(b.dataset.p), b.dataset.k || "", b.dataset.x); };
    });
    scope.querySelectorAll(".tp-eadd").forEach((b) => {
      b.onclick = () => { onStructural("add", Number(b.dataset.p), b.dataset.k || "", null); };
    });
  }

  const esc = (x) => String(x).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

  /* ---- 双语辅助: 词→中文 (一次性建全库 EN_ZH 表 + 档案 lang 兜底库外束词) ---- */
  const TP_LANG = { en: false };  // 新 tab 独立的 中/英 显示开关
  try { TP_LANG.en = localStorage.getItem("taglib.tpLang") === "en"; } catch {}
  let _EN_ZH = null;
  function enZhMap() {
    if (_EN_ZH) return _EN_ZH;
    const m = {};
    for (const c of libCats())
      for (const s of c.subcategories || [])
        for (const t of s.tags || []) {
          const k = String(t.en).toLowerCase();
          if (t.zh && !(k in m)) m[k] = t.zh;
        }
    _EN_ZH = m;
    return m;
  }
  let LANG_MAP = {};  // 档案接口带回: 库外束词(如 drawing bow)的中文
  function zhOf(en) {
    const k = String(en).toLowerCase();
    return LANG_MAP[k] || enZhMap()[k] || "";
  }
  function langBtnHtml() {
    return `<button class="tp-langbtn ${TP_LANG.en ? "en" : ""}" title="中/英文显示切换">文A</button>`;
  }
  function bindLang(scope, rerender) {
    const b = scope.querySelector(".tp-langbtn");
    if (b) b.onclick = () => {
      TP_LANG.en = !TP_LANG.en;
      try { localStorage.setItem("taglib.tpLang", TP_LANG.en ? "en" : "zh"); } catch {}
      b.classList.toggle("en", TP_LANG.en);
      rerender();
    };
  }
  function bi(en) {  // 双语渲染: 纯英模式或被查词无中文 → 只留英文
    const z = zhOf(en);
    return (TP_LANG.en || !z) ? esc(en) : `${esc(en)}<span class="tp-zh">${esc(z)}</span>`;
  }

  let profWork = null;      // 编辑中的档案工作副本 (点保存才落盘)
  let profDiag = [];

  async function renderProfView() {
    profView.innerHTML = `<div style="padding:30px;text-align:center;color:#8b93a5">加载中…</div>`;
    let d;
    try { d = await fetch("/taglib/api/profiles").then((r) => r.json()); }
    catch { profView.innerHTML = `<div class="tp-empty" style="padding:30px;color:#ff6b6b">档案接口加载失败</div>`; return; }
    LANG_MAP = Object.assign(LANG_MAP, d.lang || {});
    _EN_ZH = null;
    profDiag = d.diag || [];
    const src = d.data && Array.isArray(d.data.profiles) ? d.data : { version: 1, profiles: [] };
    profWork = JSON.parse(JSON.stringify(src));
    drawProf();
  }

  function drawProf() {
    const profs = (profWork.profiles = profWork.profiles || []);
    const nPose = profs.reduce((n, p) => n + (p.poses || []).length + (p.extras || []).length, 0);
    let html = `
      <div class="tp-h1">⚔ 武器 / 物品档案 ${langBtnHtml()}
        <span class="tp-h1-sub">${profs.length} 份 · ${nPose} 条束</span>
        <button class="tp-eadd tp-addprof" style="margin-left:auto">＋ 新增档案</button></div>
      <div class="tp-note">全部字段可直接改: 档案 id / 中文名 / 挂载槽位 / 身份词, 以及每条束的 id、出词、手数、视线、权重、状态槽。改完点底部「💾 保存档案」写入 <code>profiles.json</code>。
      姿势不独立存在 —— 每条束挂在档案下, 抽中/钉选身份词时按概率自动带出一条; 束成员词在随机池里永不单抽。</div>`;
    if (!profs.length) html += `<div class="tp-empty" style="padding:24px">还没有档案, 点右上「＋ 新增档案」开始。</div>`;
    profs.forEach((p, pi) => {
      const dg = (profDiag || []).find((x) => x.id === p.id) || {};
      const row = (x, xi, kind) => `
        <tr>
          <td><input class="tp-ecell" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="id" value="${esc(x.id || "")}" placeholder="束 id"/></td>
          <td><input class="tp-ecell" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="zh" value="${esc(x.zh || "")}" placeholder="中文"/></td>
          <td><input class="tp-ecell wide" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="tags" value="${esc((x.tags || []).join(", "))}" placeholder="出词, 逗号分隔"/></td>
          <td><input class="tp-ecell num" type="number" min="0" max="2" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="hands" value="${x.hands ?? 0}"/></td>
          <td><input class="tp-ecell num" type="number" min="0" max="1" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="gaze" value="${x.gaze ?? 0}"/></td>
          <td><input class="tp-ecell num" type="number" min="0" max="3" step="0.1" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="weight" value="${x.weight ?? 1}"/></td>
          <td><input class="tp-ecell" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="state_slot" value="${esc(Object.entries(x.state_slot || {}).map(([k, v]) => k + "=" + v).join(", "))}" placeholder="drawn=yes"/></td>
          <td><button class="tp-edel" data-p="${pi}" data-k="${kind}" data-x="${xi}" title="删除该条束">✕</button></td>
        </tr>`;
      html += `
      <div class="tp-pcard">
        <div class="tp-pcard-h">
          <input class="tp-ecell" data-p="${pi}" data-f="id" value="${esc(p.id || "")}" placeholder="档案 id" style="min-width:130px"/>
          <input class="tp-ecell" data-p="${pi}" data-f="zh" value="${esc(p.zh || "")}" placeholder="中文名" style="min-width:90px"/>
          <input class="tp-ecell wide" list="tp-subdl" data-p="${pi}" data-f="mount_sub" value="${esc(p.mount_sub || "")}" placeholder="挂载槽位 大类/子类" style="min-width:170px"/>
          <span class="tp-pbadges">
            <span class="tp-b">${(p.poses || []).length} 姿势</span>
            <span class="tp-b">${(p.extras || []).length} 配件</span>
            ${dg.mount_ok !== undefined ? `<span class="tp-b ${dg.mount_ok === dg.mount_total ? "ok" : "warn"}">挂载 ${dg.mount_ok}/${dg.mount_total}${dg.missing && dg.missing.length ? " 缺:" + esc(dg.missing.join(",")) : ""}</span>` : ""}
          </span>
          <button class="tp-edel tp-delprof" data-p="${pi}" title="删除该档案">✕</button>
        </div>
        <div class="tp-prow"><span class="tp-pl">身份词</span><span class="tp-echips" data-p="${pi}"></span></div>
        <table class="tp-ptab">
          <tr><th>束 id</th><th>中文</th><th>出词</th><th>手</th><th>视线</th><th>权重</th><th>状态槽</th><th></th></tr>
          ${(p.poses || []).map((x, xi) => row(x, xi, "poses")).join("")}
          ${(p.extras || []).map((x, xi) => row(x, xi, "extras")).join("")}
        </table>
        <div class="tp-erow">
          <button class="tp-eadd" data-p="${pi}" data-k="poses">＋ 姿势</button>
          <button class="tp-eadd" data-p="${pi}" data-k="extras">＋ 配件</button>
        </div>
      </div>`;
    });
    if ((profWork.profiles || []).some((p) => !(p.tags || []).length)) {
      html += `<div class="tp-note" style="color:var(--tl-danger-soft)">⚠ 有档案没有身份词 —— 引擎无法在抽取时找到它, 请至少填一个。</div>`;
    }
    html += `${tagDatalistHtml()}${subDatalistHtml()}
      <div class="tp-savebox">${saveBarHtml("保存档案")}</div>
      <details class="tp-jsonbox"><summary>✏ 高级: 直接编辑 JSON (保存前自动备份 .bak)</summary>
        <textarea class="tp-json" rows="14" spellcheck="false">${esc(JSON.stringify(profWork, null, 1))}</textarea>
        <div class="tp-jrow"><button class="tp-jsave">💾 保存档案</button><span class="tp-jmsg"></span></div>
      </details>`;
    profView.innerHTML = html;
    bindLang(profView, drawProf);

    // chip 列表 (身份词)
    profView.querySelectorAll(".tp-echips").forEach((el) => {
      const p = profWork.profiles[Number(el.dataset.p)];
      p.tags = p.tags || [];
      fillChips(el, p.tags, drawProf, "tp-tagdl");
    });
    bindEditable(profView, {
      getEntity: (pi, k, xi) => (k ? (profWork.profiles[pi][k] || [])[xi] : profWork.profiles[pi]),
      onStructural: (act, pi, k, xi) => {
        if (act === "del") {
          if (k) profWork.profiles[pi][k].splice(Number(xi), 1);
          else profWork.profiles.splice(pi, 1);
        } else if (act === "add" && k) {
          (profWork.profiles[pi][k] = profWork.profiles[pi][k] || []).push(
            k === "poses" ? { id: "new_pose", tags: [], hands: 1, gaze: 0, weight: 1 }
                          : { id: "new_extra", tags: [], weight: 1 });
        }
        drawProf();
      },
    });
    const addP = profView.querySelector(".tp-addprof");
    addP.onclick = () => {
      profWork.profiles.push({ id: "", zh: "", mount_sub: "", tags: [], poses: [], extras: [] });
      drawProf();
    };
    const save = async () => {
      const msg = profView.querySelector(".tp-smsg");
      const ok = await postJson("/taglib/api/profiles", { data: profWork }, msg);
      if (ok) renderProfView();
      // 高级 JSON 保存沿用原逻辑
    };
    profView.querySelector(".tp-save").onclick = save;
    editorFoot(profView, "/taglib/api/profiles", (payload) => ({ data: payload }));
  }


  let grpWork = null;

  async function renderGrpView() {
    grpView.innerHTML = `<div style="padding:30px;text-align:center;color:#8b93a5">加载中…</div>`;
    let d;
    try { d = await fetch("/taglib/api/grouprules").then((r) => r.json()); }
    catch { grpView.innerHTML = `<div style="padding:30px;color:#ff6b6b">互斥域接口加载失败</div>`; return; }
    grpWork = { groups: JSON.parse(JSON.stringify(d.groups || [])) };
    drawGrp();
  }

  function drawGrp() {
    const groups = grpWork.groups;
    let html = `
      <div class="tp-h1">🧬 互斥关系 ${langBtnHtml()}
        <span class="tp-h1-sub">${groups.length} 个互斥域 + 跨池规则</span></div>
      <div class="tp-note">两件事在这里统一: <b>互斥域</b>(同域内任意两词天然不可能同现, 抽取时查组名交集) 与 <b>跨池规则</b>(下方 A ⟂ {B,C} 的批量事实, 如 nude ⟂ 整个服装池)。
      武器姿势的排斥不在这里 —— 在档案的 <code>conflicts_with</code> 字段。域 id 与成员都可直接改。</div>
      <input class="tp-gsearch" placeholder="🔍 过滤组名 / 成员…" style="width:100%;box-sizing:border-box;margin-bottom:10px" />
      <div class="tp-glist">`;
    groups.forEach((g, gi) => {
      html += `
        <div class="tp-gitem2" data-key="${esc(String(g.id || "") + " " + (g.members || []).join(" "))}">
          <div class="tp-gitem2-h">
            <input class="tp-ecell" data-g="${gi}" data-f="id" value="${esc(g.id || "")}" placeholder="域 id"/>
            <span class="tp-gn">${(g.members || []).length} 词</span>
            <button class="tp-edel" data-g="${gi}" title="删除该域">✕</button>
          </div>
          <div class="tp-gmem tp-gchips" data-g="${gi}"></div>
        </div>`;
    });
    html += `</div>
      <div class="tp-erow"><button class="tp-eadd tp-addgrp">＋ 新增互斥域</button></div>
      <div class="tp-cf-host"></div>
      <div class="tp-savebox">${saveBarHtml("保存互斥域")}</div>
      ${tagDatalistHtml()}
      <details class="tp-jsonbox"><summary>✏ 高级: 直接编辑 JSON</summary>
        <textarea class="tp-json" rows="14" spellcheck="false">${esc(JSON.stringify(grpWork, null, 1))}</textarea>
        <div class="tp-jrow"><button class="tp-jsave">💾 保存互斥域</button><span class="tp-jmsg"></span></div>
      </details>`;
    grpView.innerHTML = html;
    bindLang(grpView, drawGrp);
    grpView.querySelectorAll(".tp-gchips").forEach((el) => {
      const g = grpWork.groups[Number(el.dataset.g)];
      g.members = g.members || [];
      fillChips(el, g.members, drawGrp, "tp-tagdl");
    });
    grpView.querySelectorAll("input[data-g][data-f]").forEach((el) => {
      el.onchange = () => {
        const g = grpWork.groups[Number(el.dataset.g)];
        const v = el.value.trim();
        if (v) g.id = v; else delete g.id;
      };
    });
    grpView.querySelectorAll(".tp-edel[data-g]").forEach((b) => {
      b.onclick = () => { grpWork.groups.splice(Number(b.dataset.g), 1); drawGrp(); };
    });
    grpView.querySelector(".tp-addgrp").onclick = () => {
      grpWork.groups.push({ id: "new_group", members: [] });
      drawGrp();
    };
    const gs = grpView.querySelector(".tp-gsearch");
    gs.oninput = () => {
      const q = gs.value.trim().toLowerCase();
      grpView.querySelectorAll(".tp-gitem2").forEach((el) => {
        el.style.display = !q || el.dataset.key.toLowerCase().includes(q) ? "" : "none";
      });
    };
    grpView.querySelector(".tp-save").onclick = async () => {
      const ok = await postJson("/taglib/api/grouprules", { groups: grpWork.groups },
                               grpView.querySelector(".tp-smsg"));
      if (ok) renderGrpView();
    };
    editorFoot(grpView, "/taglib/api/grouprules", (payload) => ({ groups: payload.groups }));
    renderCfView();   // 跨池互斥规则同属"互斥"语义, 与域规则并到一个页面
  }


  let nlWork = null;
  let nlUncovered = [];

  async function renderNlView() {
    nlView.innerHTML = `<div style="padding:30px;text-align:center;color:#8b93a5">加载中…</div>`;
    let d;
    try { d = await fetch("/taglib/api/nl").then((r) => r.json()); }
    catch { nlView.innerHTML = `<div style="padding:30px;color:#ff6b6b">NL 接口加载失败</div>`; return; }
    nlUncovered = d.uncovered || [];
    nlWork = JSON.parse(JSON.stringify(d.data || {}));
    nlWork.families = nlWork.families || {};
    nlWork.pose_map = nlWork.pose_map || {};
    drawNl();
  }

  function _nlFams() {
    return Object.entries(nlWork.families).map(([k, v]) => [k, v || []]);
  }

  function drawNl() {
    const fams = _nlFams();
    const total = fams.reduce((n, [, v]) => n + v.length, 0);
    const pm = Object.entries(nlWork.pose_map).filter(([k]) => k !== "null");
    let html = `
      <div class="tp-h1">✍ NL 句式素材
        <span class="tp-h1-sub">${fams.length} 族 · ${total} 句 · ${pm.length} 条动作映射</span>
        <button class="tp-eadd tp-addfam" style="margin-left:auto">＋ 新增句式族</button></div>
      <div class="tp-note">末尾自然语言段的素材库。占位符 <code>{S}</code> 主语 (随人数词自动 She/He/They) · <code>{POS}</code> 所有格 · <code>{O}</code> 宾语 (从档案 obj_kind→words 解析)。
      ${nlUncovered.length ? `<br><b style="color:var(--tl-warn,#e0a35e)">⚠ 档案姿势词未进下方映射 (${nlUncovered.length}): ${esc(nlUncovered.join(", "))}</b>` : `<br><b style="color:var(--tl-ok)">✓ 全部武器姿势词已有句式覆盖</b>`}</div>`;
    fams.forEach(([fam, vs], fi) => {
      html += `
        <div class="tp-fam">
          <div class="tp-fam-h">
            <input class="tp-ecell" data-fi="${fi}" data-nf="famname" value="${esc(fam)}"/>
            <span class="tp-gn">${vs.length} 变体</span>
            <button class="tp-edel tp-delfam" data-fi="${fi}" title="删除该族">✕</button>
          </div>
          ${vs.map((v, vi) => `
            <div class="tp-fam-s tp-fam-edit">
              <input class="tp-ecell wide" data-fi="${fi}" data-vi="${vi}" data-nf="variant" value="${esc(v)}"/>
              <button class="tp-edel tp-delvar" data-fi="${fi}" data-vi="${vi}" title="删除">✕</button>
            </div>`).join("")}
          <button class="tp-eadd tp-addvar" data-fi="${fi}">＋ 变体</button>
        </div>`;
    });
    html += `
      <div class="tp-fam">
        <div class="tp-fam-h">动作词 → 句式族 <span class="tp-gn">${pm.length} 项</span>
          <button class="tp-eadd tp-addpm" style="margin-left:auto">＋ 映射</button></div>
        ${pm.map(([k, v], mi) => `
          <div class="tp-fam-s tp-fam-edit">
            <input class="tp-ecell" data-mi="${mi}" data-nf="pmkey" value="${esc(k)}" list="tp-tagdl" placeholder="动作词"/>
            <span class="tp-arrow">→</span>
            <select class="tp-ecell" data-mi="${mi}" data-nf="pmval">
              ${fams.map(([f2]) => `<option value="${esc(f2)}"${f2 === v ? " selected" : ""}>${esc(f2)}</option>`).join("")}
            </select>
            <button class="tp-edel tp-delpm" data-mi="${mi}" title="删除">✕</button>
          </div>`).join("")}
      </div>
      <div class="tp-savebox">${saveBarHtml("保存句式")}</div>
      ${tagDatalistHtml()}
      <details class="tp-jsonbox"><summary>✏ 高级: 直接编辑 JSON (含 words / intro / env / light / obj_kind 等)</summary>
        <textarea class="tp-json" rows="18" spellcheck="false">${esc(JSON.stringify(nlWork, null, 1))}</textarea>
        <div class="tp-jrow"><button class="tp-jsave">💾 保存句式</button><span class="tp-jmsg"></span></div>
      </details>`;
    nlView.innerHTML = html;
    bindLang(nlView, drawNl);

    // 族改名 (保序重建 + 同步 pose_map 指向)
    nlView.querySelectorAll('input[data-nf="famname"]').forEach((el) => {
      el.onchange = () => {
        const arr = _nlFams();
        const fi = Number(el.dataset.fi);
        const oldName = arr[fi][0];
        const nv = el.value.trim();
        if (!nv || nv === oldName || nlWork.families[nv]) { drawNl(); return; }
        const rebuilt = {};
        for (const [k, v] of arr) rebuilt[k === oldName ? nv : k] = v;
        nlWork.families = rebuilt;
        for (const [k, v] of Object.entries(nlWork.pose_map)) {
          if (v === oldName) nlWork.pose_map[k] = nv;
        }
        drawNl();
      };
    });
    nlView.querySelectorAll('input[data-nf="variant"]').forEach((el) => {
      el.onchange = () => {
        const fam = _nlFams()[Number(el.dataset.fi)][0];
        nlWork.families[fam][Number(el.dataset.vi)] = el.value;
      };
    });
    nlView.querySelectorAll(".tp-delvar").forEach((b) => {
      b.onclick = () => {
        const fam = _nlFams()[Number(b.dataset.fi)][0];
        nlWork.families[fam].splice(Number(b.dataset.vi), 1);
        drawNl();
      };
    });
    nlView.querySelectorAll(".tp-addvar").forEach((b) => {
      b.onclick = () => { _nlFams()[Number(b.dataset.fi)][1].push(""); drawNl(); };
    });
    nlView.querySelectorAll(".tp-delfam").forEach((b) => {
      b.onclick = () => { delete nlWork.families[_nlFams()[Number(b.dataset.fi)][0]]; drawNl(); };
    });
    nlView.querySelector(".tp-addfam").onclick = () => {
      let name = "new_family", i = 2;
      while (nlWork.families[name]) name = "new_family" + i++;
      nlWork.families[name] = [""];
      drawNl();
    };
    nlView.querySelectorAll('input[data-nf="pmkey"]').forEach((el) => {
      el.onchange = () => {
        const keys = Object.keys(nlWork.pose_map).filter((k) => k !== "null");
        const old = keys[Number(el.dataset.mi)];
        const nv = el.value.trim();
        if (!nv || nv === old) { drawNl(); return; }
        const rebuilt = {};
        for (const k of Object.keys(nlWork.pose_map)) rebuilt[k === old ? nv : k] = nlWork.pose_map[k];
        nlWork.pose_map = rebuilt;
        drawNl();
      };
    });
    nlView.querySelectorAll('select[data-nf="pmval"]').forEach((el) => {
      el.onchange = () => {
        const keys = Object.keys(nlWork.pose_map).filter((k) => k !== "null");
        nlWork.pose_map[keys[Number(el.dataset.mi)]] = el.value;
      };
    });
    nlView.querySelectorAll(".tp-delpm").forEach((b) => {
      b.onclick = () => {
        const keys = Object.keys(nlWork.pose_map).filter((k) => k !== "null");
        delete nlWork.pose_map[keys[Number(b.dataset.mi)]];
        drawNl();
      };
    });
    nlView.querySelector(".tp-addpm").onclick = () => {
      const f = _nlFams()[0];
      nlWork.pose_map["new action"] = f ? f[0] : "new_family";
      drawNl();
    };
    nlView.querySelector(".tp-save").onclick = async () => {
      const ok = await postJson("/taglib/api/nl", { data: nlWork }, nlView.querySelector(".tp-smsg"));
      if (ok) renderNlView();
    };
    editorFoot(nlView, "/taglib/api/nl", (payload) => ({ data: payload }));
  }

  let cfRights = [];   // 新增规则的右侧引用 [{kind, value}]

  function cfKindName(kind) {
    return kind === "tag" ? "标签" : kind === "sub" ? "二级分类" : "一级分类";
  }

  function cfDatalist(kind) {
    const opts = [];
    if (kind === "tag") {
      for (const c of libCats()) for (const s of c.subcategories || [])
        for (const t of s.tags || []) opts.push(t.en);
    } else if (kind === "sub") {
      for (const c of libCats()) for (const s of c.subcategories || [])
        opts.push(`${c.name}/${s.name}`);
    } else {
      for (const c of libCats()) opts.push(c.name);
    }
    return `<datalist id="tp-cf-dl-${kind}">${opts.map((v) => `<option value="${escapeHtml(String(v))}"/>`).join("")}</datalist>`;
  }

  async function renderCfView() {
    // v1.6.0: 原「🧷 防冲突关系」独立页签已删, 规则列表并入「🧬 互斥域」页
    // (两者都是"两两互斥", 用户不该判断该去哪个页签加互斥)。
    const cfView = grpView.querySelector(".tp-cf-host");
    if (!cfView) return;
    cfView.innerHTML = `<div style="padding:20px;text-align:center;color:#8b93a5">加载中…</div>`;
    let st;
    try {
      st = await fetch("/taglib/api/conflicts").then((r) => r.json());
    } catch {
      cfView.innerHTML = `<div class="tp-empty" style="padding:30px;color:#8b93a5">反冲突规则加载失败</div>`;
      return;
    }
    const rules = st.rules || [];
    cfRights = [];
    const invalidVals = new Set((st.invalid || []).map((x) => String(x.value)));
    cfView.innerHTML = `
      <div class="tp-cf-stats">
        共 <b style="color:#54a0ff">${rules.length}</b> 条双向互斥规则
        ${(st.invalid || []).length ? `，<span style="color:#ff6b6b">⚠ ${invalidVals.size} 个失效引用</span>` : ""}
        —— 填充/自动模式抽到一侧，另一侧自动让位（手动点选不受影响）
      </div>
      <div class="tp-cf-list"></div>
      <div class="tp-cf-h">新增规则</div>
      <div class="tp-cf-form">
        <div class="tp-cf-frow">
          <span class="cf-klab">左侧</span>
          <select class="cf-lkind">
            <option value="tag">标签</option>
            <option value="sub">二级分类</option>
            <option value="cat">一级分类</option>
          </select>
          <input class="cf-linput" list="tp-cf-dl-tag" placeholder="标签英文…" style="flex:1;min-width:180px"/>
        </div>
        <div class="tp-cf-frow">
          <span class="cf-klab">右侧</span>
          <select class="cf-rkind">
            <option value="tag">标签</option>
            <option value="sub">二级分类</option>
            <option value="cat">一级分类</option>
          </select>
          <input class="cf-rinput" list="tp-cf-dl-tag" placeholder="可连续添加多个…" style="flex:1;min-width:180px"/>
          <button class="tp-cf-add">＋ 添加到右侧</button>
        </div>
        <div class="tp-cf-rights"></div>
        <button class="tp-cf-save">💾 保存规则</button>
        <span class="tp-cf-note" style="font-size:11px;color:#6b7385;margin-left:10px">保存后立即写入 data/taglib/conflicts.json</span>
      </div>
      ${cfDatalist("tag")}${cfDatalist("sub")}${cfDatalist("cat")}`;

    const listBox = cfView.querySelector(".tp-cf-list");
    if (!rules.length) {
      listBox.innerHTML = `<div style="color:#8b93a5;font-size:12px">暂无规则</div>`;
    }
    for (const r of rules) {
      const card = document.createElement("div");
      card.className = "tp-cf-rule";
      const warns = [];
      if (invalidVals.has(String(r.left?.value))) warns.push(escapeHtml(String(r.left?.value)));
      const rts = (r.right || []).map((ref) => {
        const bad = invalidVals.has(String(ref.value));
        if (bad) warns.push(escapeHtml(String(ref.value)));
        return `<span class="cf-rt">${escapeHtml(String(ref.value))}</span>`;
      }).join(" ");
      card.innerHTML = `
        <span class="cf-l">${escapeHtml(String(r.left?.value ?? "?"))}</span>
        <span class="cf-vs">⟂</span>${rts}
        ${r.note ? `<span class="cf-note">${escapeHtml(String(r.note))}</span>` : ""}
        ${warns.length ? `<span class="cf-warn">⚠ 失效: ${warns.join("、")}</span>` : ""}
        <button class="cf-del" title="删除规则">✕</button>`;
      card.querySelector(".cf-del").onclick = async () => {
        const rest = rules.filter((x) => x !== r);
        try {
          const res = await fetch("/taglib/api/conflicts", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ rules: rest }),
          });
          const out = await res.json();
          if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
          toast("规则已删除");
          renderCfView();
        } catch (err) {
          toast(`删除失败: ${err.message}`, true);
        }
      };
      listBox.appendChild(card);
    }

    // 新增表单
    const lkind = cfView.querySelector(".cf-lkind");
    const linput = cfView.querySelector(".cf-linput");
    const rkind = cfView.querySelector(".cf-rkind");
    const rinput = cfView.querySelector(".cf-rinput");
    const rightsBox = cfView.querySelector(".tp-cf-rights");
    const renderRights = () => {
      rightsBox.innerHTML = cfRights.length
        ? cfRights.map((ref, i) =>
            `<span class="cf-rt-chip">${escapeHtml(String(ref.value))}<span class="x" data-i="${i}">✕</span></span>`).join("")
        : `<span style="color:#6b7385;font-size:11px">尚未添加右侧对象</span>`;
      rightsBox.querySelectorAll(".x").forEach((x) => {
        x.onclick = () => { cfRights.splice(Number(x.dataset.i), 1); renderRights(); };
      });
    };
    renderRights();
    lkind.onchange = () => {
      const dl = cfView.querySelector(`#tp-cf-dl-${lkind.value}`);
      linput.setAttribute("list", `tp-cf-dl-${lkind.value}`);
      if (dl) { dl.remove(); cfView.appendChild(dl); }
      linput.value = "";
    };
    rkind.onchange = () => {
      const dl = cfView.querySelector(`#tp-cf-dl-${rkind.value}`);
      rinput.setAttribute("list", `tp-cf-dl-${rkind.value}`);
      if (dl) { dl.remove(); cfView.appendChild(dl); }
      rinput.value = "";
    };
    cfView.querySelector(".tp-cf-add").onclick = () => {
      const v = rinput.value.trim();
      if (!v) return toast("先填右侧对象", true);
      const ref = { kind: rkind.value, value: v };
      if (cfRights.some((x) => x.kind === ref.kind && String(x.value).toLowerCase() === String(v).toLowerCase()))
        return toast("已添加过", true);
      cfRights.push(ref);
      rinput.value = "";
      renderRights();
    };
    cfView.querySelector(".tp-cf-save").onclick = async () => {
      const lv = linput.value.trim();
      if (!lv) return toast("先填左侧对象", true);
      if (!cfRights.length) return toast("至少添加一个右侧对象", true);
      const rule = { id: `cf.${Date.now().toString(36)}.${Math.floor(Math.random() * 999)}`,
                     left: { kind: lkind.value, value: lv },
                     right: cfRights.slice() };
      try {
        const res = await fetch("/taglib/api/conflicts", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rules: [...rules, rule] }),
        });
        const out = await res.json();
        if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
        toast(`✅ 规则已保存 (共 ${out.count} 条)`);
        renderCfView();
      } catch (err) {
        toast(`保存失败: ${err.message}`, true);
      }
    };
  }

  function switchTab(tab) {
    ui.tab = tab;
    rootEl.querySelector(".tp-picktab").classList.toggle("active", tab === "pick");
    rootEl.querySelector(".tp-settab").classList.toggle("active", tab === "settings");
    rootEl.querySelector(".tp-proftab")?.classList.toggle("active", tab === "prof");
    rootEl.querySelector(".tp-grptab")?.classList.toggle("active", tab === "grp");
    rootEl.querySelector(".tp-nltab")?.classList.toggle("active", tab === "nl");
    for (const el of pickCols) el.style.display = tab === "pick" ? "" : "none";
    setView.style.display = tab === "settings" ? "block" : "none";
    profView.style.display = tab === "prof" ? "block" : "none";
    grpView.style.display = tab === "grp" ? "block" : "none";
    nlView.style.display = tab === "nl" ? "block" : "none";
    searchEl.style.visibility = tab === "pick" ? "visible" : "hidden";
    const info = $(".tp-footinfo");
    if (tab === "pick") {
      info.innerHTML = `已挑选 <b class="tp-count">${ui.picked.length}</b> 个`;
    } else if (tab === "prof") {
      info.innerHTML = `⚔ 姿势只能随武器出生 · 改档案保存即生效`;
    } else if (tab === "grp") {
      info.innerHTML = `🧬 同域任意两词永不共存 (引擎抽取期拦截)`;
    } else if (tab === "nl") {
      info.innerHTML = `✍ 句式素材 · 与标签同 seed 确定性输出`;
    } else {
      info.innerHTML = `节点参数即改即存 · 全局偏好双向同步`;
    }
    // 底部按钮: 挑选/排除 -> 取消+确定; 管理/防冲突/设置 -> 仅关闭
    const pickLike = tab === "pick";
    $(".tp-cancel").style.display = pickLike ? "" : "none";
    $(".tp-ok").style.display = pickLike ? "" : "none";
    $(".tp-close2").style.display = pickLike ? "none" : "";
    if (tab === "settings") renderSettingsView();
    if (tab === "prof") renderProfView();
    if (tab === "grp") renderGrpView();
    if (tab === "nl") renderNlView();
  }
  rootEl.querySelector(".tp-picktab").onclick = () => switchTab("pick");
  rootEl.querySelector(".tp-settab").onclick = () => switchTab("settings");
  rootEl.querySelector(".tp-proftab")?.addEventListener("click", () => switchTab("prof"));
  rootEl.querySelector(".tp-grptab")?.addEventListener("click", () => switchTab("grp"));
  rootEl.querySelector(".tp-nltab")?.addEventListener("click", () => switchTab("nl"));
  $(".tp-close2").onclick = onCancel;

  searchEl.oninput = () => { ui.filter = searchEl.value; renderChips(); };
  $(".tp-cancel").onclick = onCancel;
  $(".tp-ok").onclick = () => onConfirm(ui.picked);

  renderCats();
  renderChips();
  return {
    destroy() {},
    libTouched: () => ui.libTouched,
  };
}

/* ------------------------------------------------- manager dialog */

function openManagerDialog() {
  let dlg = document.getElementById("taglib-manager-dialog");
  if (dlg) { dlg.close(); dlg.remove(); }
  dlg = document.createElement("dialog");
  dlg.id = "taglib-manager-dialog";
  dlg.style.cssText =
    "width:min(96vw,1400px);height:min(94vh,980px);border:none;border-radius:14px;" +
    "padding:0;background:var(--tl-bg-solid);color:var(--tl-text);max-width:none;max-height:none;";
  dlg.classList.add("p-inputtext", "notranslate", "tl-scope");
  dlg.setAttribute("translate", "no");
  // 不设 ✕ 按钮 —— 会与管理页顶栏「恢复默认库」重叠; 关闭 = 点遮罩 / Esc
  dlg.innerHTML =
    `<iframe src="${managerUrl()}" style="width:100%;height:100%;border:0;border-radius:14px;display:block"></iframe>`;
  document.body.appendChild(dlg);
  dlg.showModal();
  dlg.addEventListener("click", (e) => {
    // 点击遮罩区域也可关闭 (dialog 自身 = 遮罩)
    if (e.target === dlg) dlg.close();
  });
  dlg.addEventListener("close", () => {
    invalidateLibraryCache();
    window.dispatchEvent(new CustomEvent("taglib-updated"));
  });
}

/* --------------------------------------------------------- register */

app.registerExtension({
  name: "zhixin.tagLibrary",

  // 命令 + Extensions 菜单入口 (正规姿势: registerExtension 字段; 旧 registerCommand API 不存在)
  commands: [
    { id: "zhixin.openTagLibraryManager", label: "🏷 打开标签库管理页", function: () => openManagerDialog() },
  ],
  menuCommands: [
    { path: ["Extensions"], commands: ["zhixin.openTagLibraryManager"] },
  ],

  /* ComfyUI 设置面板里的专属设置 */
  settings: [
    {
      id: SET_DEFAULT_MODE,
      name: "标签库: 新节点的默认模式",
      type: "combo",
      options: ["manual", "auto"],
      defaultValue: "manual",
      tooltip: "手动=点选+填充 / 自动=每次 Queue 按排除类目随机组合",
    },
    {
      id: SET_DEFAULT_NSFW,
      name: "标签库: 默认启用 NSFW 标签",
      type: "boolean",
      defaultValue: false,
      tooltip: "关闭时隐藏并排除 NSFW 标签；也可在每个节点上单独开关",
    },
    {
      id: SET_SCALE,
      name: "标签库: 整体比例 (%) — 按钮/字体等内部 UI 缩放",
      type: "number",
      attrs: { min: 50, max: 200, step: 5 },
      defaultValue: 100,
      tooltip: "100% = 默认大小; 影响面板内所有按钮/字体/chip 大小; 面板高度自动跟随节点",
    },
    {
      id: SETTING_PREFIX + "chip_font_size",
      name: "标签库: 标签字号覆盖 (px, 0=跟随比例)",
      type: "number",
      attrs: { min: 0, max: 24, step: 1 },
      defaultValue: 0,
      tooltip: "单独指定标签文字大小; 0 = 使用上面的整体比例",
    },
    {
      id: SETTING_PREFIX + "chip_radius",
      name: "标签库: 标签圆角 (px)",
      type: "number",
      attrs: { min: 0, max: 16, step: 1 },
      defaultValue: 7,
      tooltip: "标签芯片的圆角半径",
    },
    {
      id: SET_LANG,
      name: "标签库: 标签文字显示",
      type: "combo",
      options: [
        { text: "双语 (英文+中文)", value: "bilingual" },
        { text: "仅英文", value: "en" },
        { text: "仅中文", value: "zh" },
      ],
      defaultValue: "bilingual",
      tooltip: "输出永远只有英文; 这里只控制面板里标签按钮的显示文字",
    },
  ],

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated?.apply(this, arguments);
      const node = this;

      // 面板随节点宽度自适应: 监听节点 resize, 同步最小宽度 + 重算高度
      const PANEL_MIN_W = 280;
      const PANEL_MIN_H = 300;  // 面板最少需要的高度 (参数区 + 面板 + 预览)
      function syncPanelToNode() {
        // 宽度不再强制节点变宽 —— 面板 CSS (flex/min-width:0) 跟随节点实际宽度收缩,
        // 避免"面板凸出节点"的错位。仅提醒画布重绘。
        node.setDirtyCanvas?.(true, true);
      }
      const origOnResize = nodeType.prototype.onResize;
      nodeType.prototype.onResize = function (size) {
        syncPanelToNode();
        return origOnResize?.call(this, size);
      };

      // 新节点应用默认模式设置
      setTimeout(() => {
        // ---- 插槽中文化 (2进2出是什么) ----
        const IN_LABELS = {
          prefix: "⬅️ 前置文本",
          suffix: "⬅️ 后置文本",
        };
        const IN_TOOLTIPS = {
          prefix: "上游提示词会拼在标签前面 (如质量词/LoRA触发词)",
          suffix: "上游文本会拼在标签后面",
        };
        const OUT_LABELS = {
          positive: "➡️ 正面提示词",
          tags_preview: "➡️ 标签预览",
        };
        const OUT_TOOLTIPS = {
          positive: "连接 CLIPTextEncode 的 text 输入",
          tags_preview: "接 Preview Text 节点可查看实际输出内容",
        };
        for (let i = 0; i < (node.inputs || []).length; i++) {
          const inp = node.inputs[i];
          if (IN_LABELS[inp.name]) {
            inp.label = IN_LABELS[inp.name];
            if (IN_TOOLTIPS[inp.name]) inp.tooltip = IN_TOOLTIPS[inp.name];
          }
        }
        for (let i = 0; i < (node.outputs || []).length; i++) {
          const out = node.outputs[i];
          if (OUT_LABELS[out.name]) {
            out.label = OUT_LABELS[out.name];
            out.localized_name = OUT_LABELS[out.name];
            if (OUT_TOOLTIPS[out.name]) out.tooltip = OUT_TOOLTIPS[out.name];
          }
        }
        node.onConnectionsChange = (() => {
          const orig = node.onConnectionsChange;
          return function () {
            // 连线后 ComfyUI 可能重算 slot label -> 保持中文
            for (let i = 0; i < (node.inputs || []).length; i++) {
              const inp = node.inputs[i];
              if (IN_LABELS[inp.name] && !inp.label) inp.label = IN_LABELS[inp.name];
            }
            return orig?.apply(this, arguments);
          };
        })();

        // ---- 中文化 widget 标签 (v3: selection_state/mode/seed/ctl) ----
        const LABELS = {
          mode: "模式",
          seed: "随机种子",
          control_after_generate: "生成后种子动作",
          selection_state: "标签库状态 (自动维护)",
        };
        // combo 选项显示值映射 (显示中文, 内部值仍英文以兼容工作流)
        const OPT_LABELS = {
          mode: { manual: "手动", auto: "自动", random_mix: "自动", random_by_category: "手动" },
          control_after_generate: { fixed: "固定", increment: "递增", decrement: "递减", randomize: "随机" },
        };
        for (const w of node.widgets || []) {
          if (LABELS[w.name]) {
            try { w.label = LABELS[w.name]; } catch {}
          }
          const optMap = OPT_LABELS[w.name];
          if (optMap) {
            try {
              if (w.element?.tagName === "SELECT") {
                for (const opt of w.element.options) {
                  if (optMap[opt.value]) opt.textContent = optMap[opt.value];
                }
              }
            } catch {}
          }
        }
        // 显示层兜底: 每次绘制前把 widget 显示文本换中文 (LiteGraph 画布绘 label+value)
        try {
          const origDraw = node.onDrawBackground;
          node.onDrawBackground = function (ctx) {
            for (const w of node.widgets || []) {
              const m = OPT_LABELS[w.name];
              if (m && m[w.value] && w.element?.tagName !== "SELECT") {
                w.displayValue = m[w.value];
              }
            }
            // 工作流加载/粘贴/撤销后 widget 值可能晚于面板构建到达: 每帧检测,
            // 值有变化才真正重同步 (内部有守卫, 开销为一次字符串比较)
            node._taglibPanelApi?.syncMode?.();
            return origDraw?.apply(this, arguments);
          };
        } catch {}
        // ComfyUI 渲染用 w.label ?? w.name, label 设置即生效;
        // 老版本没有 label 字段时 hack 到 onLabel 需要额外兼容, 现代版都支持.
        const modeW2 = node.widgets?.find((w) => w.name === "mode");
        if (modeW2) {
          // combo 选项中文化 (显示层): ComfyUI 用 options.values 传值, label 映射显示
          const disp = { manual: "手动选签", random_by_category: "按分类随机", random_mix: "组合随机" };
          if (!modeW2.__zhPatched) {
            modeW2.__zhPatched = true;
            const origToString = {};
            // 简单方案: tooltip 说明含义即可, 值保持英文 (兼容工作流)
          }
        }

        // ---- 参数自愈 (onConfigure): 按名字校验, 非法值重置默认。
        // v4 签名只有 [selection_state, mode, seed, ctl, taglib_panel],
        // 旧工作流多出来的槽位值 (含 v3 的 nsfw_mode / v2 的 8 个) 会错位 —— 统一纠正,
        // 旧 nsfw_mode=on 的用户设置迁移到 selection_state.nsfw。
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
          const r = onConfigure?.apply(this, arguments);
          try {
            let repaired = [];
            const wOf = (name) => this.widgets?.find((x) => x.name === name);
            const modeW3 = wOf("mode");
            if (modeW3 && modeW3.value === "random_mix") {
              // 旧"组合随机" → 自动
              modeW3.value = "auto";
              repaired.push(`组合随机→自动`);
            } else if (modeW3 && modeW3.value === "random_by_category") {
              // 旧"按类随机" → 手动
              modeW3.value = "manual";
              repaired.push(`按类随机→手动`);
            } else if (modeW3 && !["manual", "auto"].includes(modeW3.value)) {
              modeW3.value = "manual";
              repaired.push(`mode→manual`);
            }
            // v3 工作流的 nsfw_mode=on 迁移到 selection_state.nsfw
            if (Array.isArray(this.widgets_values) && this.widgets_values.length >= 5) {
              const legacyNsfw = this.widgets_values[4];
              if (legacyNsfw === "on" || legacyNsfw === "only") {
                const swPre = wOf("selection_state");
                if (swPre) {
                  try {
                    const st0 = JSON.parse(swPre.value || "{}");
                    if (!st0.nsfw) { st0.nsfw = true; swPre.value = JSON.stringify(st0); repaired.push("nsfw→开(迁移)"); }
                  } catch {}
                }
              }
            }
            const seedW = wOf("seed");
            if (seedW && (typeof seedW.value !== "number" || isNaN(seedW.value) || seedW.value < 0)) {
              seedW.value = 0;
              repaired.push(`seed→0`);
            }
            // selection_state 必须是 JSON 对象; 旧 v2 工作流错位可能把数字/字符串塞进来
            const sw = wOf("selection_state");
            if (sw) {
              let parsed = null;
              if (typeof sw.value === "string" && sw.value.trim()) {
                try { parsed = JSON.parse(sw.value); } catch { parsed = null; }
              } else if (typeof sw.value === "object" && sw.value !== null) {
                parsed = sw.value;
              }
              if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
                sw.value = "{}";
                repaired.push("selection_state→{}");
              }
              // 旧 v2 工作流: 错位把 8 个旧参数值留在 widgets_values 里, 而新签名
              // 只消费 5 个 (state/mode/seed/ctl/nsfw) → 多余的 8 个不会污染任何 widget,
              // 但需要把用户当时的设置抢救进 selection_state:
              // v2 顺序: [state, mode, seed, ctl, nsfw, min, max, cw, st, sep, uw, dd, pr]
              if (Array.isArray(this.widgets_values) && this.widgets_values.length > 5) {
                const [, , , , , minV, maxV, cwV, stV, sepV, uwV, ddV] = this.widgets_values;
                try {
                  const st2 = JSON.parse(sw.value || "{}");
                  let migrated = [];
                  if (Number.isFinite(minV)) { st2.min_tags = minV; migrated.push("min"); }
                  if (Number.isFinite(maxV)) { st2.max_tags = maxV; migrated.push("max"); }
                  if (typeof cwV === "string") { st2.category_weights = cwV; }
                  if (typeof stV === "string") { st2.search_text = stV; }
                  if (sepV === "comma" || sepV === "space") { st2.separator = sepV; migrated.push("sep"); }
                  if (typeof uwV === "boolean") { st2.use_weights_syntax = uwV; }
                  if (typeof ddV === "boolean") { st2.dedupe = ddV; }
                  sw.value = JSON.stringify(st2);
                  if (migrated.length) repaired.push(`旧参数迁移(${migrated.join(",")})`);
                } catch {}
              }
            }
            if (repaired.length) {
              console.warn("[TagLibrary] 检测到旧工作流参数, 已自动修复/迁移:", repaired.join(", "));
            }
          } catch {}
          return r;
        };

        const modeW = node.widgets?.find((w) => w.name === "mode");
        const defMode = getSetting(SET_DEFAULT_MODE, "manual");
        // 只对"新建节点"应用默认模式: widgets_values 还没被工作流填充时值为原型默认。
        // 加载旧工作流时此 setTimeout 同样会跑, 但 mode 已是工作流保存值, 不能覆盖!
        if (modeW && node.widgets_values === null && Object.values(modeW.options || {}).includes(defMode)) {
          modeW.value = defMode;
        }
        const defNsfw = getSetting(SET_DEFAULT_NSFW, false);
        if (defNsfw && node.widgets_values === null) {
          const sw = node.widgets?.find((w) => w.name === "selection_state");
          if (sw) {
            try {
              const st = JSON.parse(sw.value || "{}");
              st.nsfw = true;
              sw.value = JSON.stringify(st);
            } catch {}
          }
        }
        // 隐藏内部 widget (selection_state 是面板状态, 不需要显示)
        for (const name of ["selection_state"]) {
          const w = node.widgets?.find((x) => x.name === name);
          if (w) {
            w.computeSize = () => [0, -4];
            if (w.inputEl) w.inputEl.style.display = "none";
            try { w.hidden = true; } catch {}
          }
        }
        // 工作流加载完成后面板与 widget 对齐一次: 模式按钮跟随 mode 值,
        // 已选 chips 从加载回来的 selection_state 重渲染 (修复重启后面板显示手动、后端仍是自动)
        node._taglibPanelApi?.syncMode?.();
        node._taglibPanelApi?.refresh?.();
      }, 0);

      const holder = document.createElement("div");
      holder.className = "taglib-widget-holder";
      const panelApi = buildPanelWidget(node, holder);
      // ---- 主题适配: ComfyUI 会在 html 上切 dark-theme 类; 内置主题共 6 套 ----
      // arc/dark/github/solarized/nord = 深色, light = 浅色。
      // 监听设置变化, 把当前主题 id 写到面板 data-theme 上, CSS 按此切换配色。
      const applyTheme = () => {
        try {
          // 官方主题切换机制: html.dark-theme 类 (light 主题移除, 其余添加)。
          // 具体配色 id 走 data-theme, 明暗走 .tl-light —— 与 tagpanel-css.js 的
          // .tl-scope 变量表对应; 面板/挑选器/管理弹窗三处同步同一份值。
          const { pid, isLight } = currentTheme();
          // holder 自身就是 .taglib-panel (buildPanelWidget 在 container 上加类)
          const panel = holder.classList.contains("taglib-panel") ? holder : holder.querySelector(".taglib-panel");
          if (panel) {
            panel.dataset.theme = pid;
            panel.classList.toggle("tl-light", isLight);
          }
          for (const dlg of document.querySelectorAll("#taglib-picker-dialog, #taglib-manager-dialog")) {
            dlg.dataset.theme = pid;
            dlg.classList.toggle("tl-light", isLight);
            pushThemeToFrames(dlg);   // 内嵌管理页是独立文档, 只能 postMessage
          }
        } catch {}
      };
      applyTheme();
      try {
        app.extensionManager?.settings?.addEventListener?.("change", (e) => {
          if (e?.detail?.id === "Comfy.ColorPalette") { applyTheme(); }
        });
      } catch {}
      // 设置页可能还没就绪, 延迟再刷一次; 并监听 html 主题类变化 (官方切主题就靠它)
      setTimeout(applyTheme, 1500);
      setTimeout(applyTheme, 4000);
      try {
        new MutationObserver(applyTheme).observe(document.documentElement, {
          attributes: true, attributeFilter: ["class"],
        });
      } catch {}
      // ---- 官方高度机制 (前端 1.48+): DOM widget 通过 CSS 变量声明高度 ----
      //   --comfy-widget-min-height : 节点最小高度下限 (面板永远完整可见)
      //   --comfy-widget-height     : 期望高度, 支持 "60%" 百分比 = 按节点高度折算
      // 前端 _arrangeWidgets 自动把节点剩余空间分给面板 (min~max 弹性),
      // 不需要任何手动 onDraw/rAF 同步 —— 面板原生嵌入节点, 随节点缩放。
      holder.style.setProperty("--comfy-widget-min-height", "160px");
      holder.style.setProperty("--comfy-widget-height", "60%");
      // serialize:false —— 面板本身不进 widgets_values (它的状态已存在 selection_state 里),
      // 否则会在 seed 的 control_after_generate 之后插入一个多余槽位, 让按位置保存/加载错位。
      const domW = node.addDOMWidget("taglib_panel", "panel", holder, {
        hideOnZoom: false,
        serialize: false,
      });
      // 新版前端序列化循环读的是【widget 实例属性】serialize (不是 options.serialize),
      // 必须直接赋在实例上才能真正跳过。另外 serializeValue 返回 undefined 兜底。
      domW.serialize = false;
      try { domW.serializeValue = () => undefined; } catch {}
      node._taglibPanelApi = panelApi;
      node._taglibGetLibPath = () => LIB_PATH; // executed 回显用 (模块内 LIB_PATH)

      // 内容变化(分类展开/chips 渲染)时让画布重排一次
      panelApi.onChange = () => {
        app.canvas?.setDirty?.(true, true);
      };

      syncPanelToNode();
      // ---- 出生尺寸 = 最小限制 (computeSize 的地板值) ----
      // 高度: computeSize 会 clamp 到 constructor.min_height (DOM widget 不参与高度累计)
      // 宽度: computeSize 宽度由 slots/title/widgets 推算 (比我们想要的 420 宽, 无妨 ——
      //       它就是"最小限制", 出生=它, 用户点缩放/拖拽都不会再跳变)
      // 前端 node.size 是 Float32Array backing 的 getter; prototype.onResize 就地改
      // sizeRef 可以做硬下限钳制。
      node.constructor.min_height = Math.max(PANEL_MIN_H, 560);
      const minW = Math.max(PANEL_MIN_W, 420);
      node.constructor.prototype.onResize = function (size) {
        // sizeRef 是 node.boundingRect.size 的 subarray (引用语义, 就地改生效)。
        // 下限 = computeSize() 即时值 → 与"点缩放按钮"完全一致, 拖拽不可能低于它。
        try {
          const cs = this.computeSize();
          if (size[0] < cs[0]) size[0] = cs[0];
          if (size[1] < cs[1]) size[1] = cs[1];
        } catch {}
        if (size[0] < minW) size[0] = minW;
        if (size[1] < node.constructor.min_height) size[1] = node.constructor.min_height;
      };
      // 出生即达到 computeSize() (含 min_height clamp) —— 与"点缩放按钮"的结果一致。
      // 注意: onNodeCreated 时 widgets 可能还没 arrange, computeSize 会偏小;
      // 所以再延迟补一次 (arrange 后 computeSize 变大, 出生尺寸跟着到位)。
      const fitNow = node.computeSize();
      node.setSize([
        Math.max(fitNow[0], minW),
        Math.max(fitNow[1], node.constructor.min_height),
      ]);
      setTimeout(() => {
        try {
          if (node.graph?._nodes?.includes(node)) {
            const fit = node.computeSize();
            node.setSize([
              Math.max(fit[0], minW),
              Math.max(fit[1], node.constructor.min_height),
            ]);
          }
        } catch {}
      }, 400);

      window.addEventListener("taglib-updated", () => panelApi.refresh({ reloadLib: true }));
      return r;
    };
  },

  async setup() {
    // 顶栏直达按钮: fixed 定位贴在右上角 (控制面板按钮左侧), 不依赖插件变动大的 DOM 结构
    const injectTopbarBtn = () => {
      try {
        if (document.getElementById("taglib-topbar-btn")) return true;
        const btn = document.createElement("button");
        btn.id = "taglib-topbar-btn";
        btn.textContent = "🏷";
        btn.title = "标签库管理页";
        // tl-scope: 复用面板主题变量 → 顶栏按钮在深浅主题下都不违和
        btn.className = "tl-scope";
        btn.style.cssText =
          "position:fixed;z-index:99999;top:10px;right:64px;padding:4px 10px;" +
          "border-radius:8px;border:1px solid var(--tl-border-2);" +
          "background:var(--tl-bg-solid);color:var(--tl-text);cursor:pointer;font-size:13px;";
        const syncTheme = () => {
          const { pid, isLight } = currentTheme();
          btn.dataset.theme = pid;
          btn.classList.toggle("tl-light", isLight);
        };
        syncTheme();
        try {
          new MutationObserver(syncTheme).observe(document.documentElement, {
            attributes: true, attributeFilter: ["class"],
          });
        } catch {}
        btn.onclick = openManagerDialog;
        document.body.appendChild(btn);
        return true;
      } catch { return false; }
    };
    setTimeout(injectTopbarBtn, 2500);
    setTimeout(injectTopbarBtn, 6000);
    // ---- 自动模式队列回显: 监听 executed 事件, 把 auto 节点实际抽到的标签写回面板 ----
    try {
      app.api?.addEventListener?.("executed", (event) => {
        try {
          const detail = event?.detail || {};
          const nodeId = String(detail.node ?? "");
          const output = detail.output || {};
          if (!output.taglib_echo) return;
          const node = app.graph?.getNodeById?.(Number(nodeId))
            || app.graph?._nodes_by_id?.[nodeId];
          if (!node || node.type !== "TagLibraryNode") return;
          // 服务器可能把 str 值拆成字符数组 → join 还原
          const echoRaw = Array.isArray(output.taglib_echo)
            ? output.taglib_echo.join("") : output.taglib_echo;
          const parsed = JSON.parse(echoRaw);
          if (!Array.isArray(parsed)) return;
          const w = node.widgets?.find((x) => x.name === "selection_state");
          if (!w) return;
          const st = (() => { try { return JSON.parse(w.value || "{}"); } catch { return {}; } })();
          // 替换填充部分: 排除类目保留标签 + 📌钉选标签保留 (钉选语义不丢);
          // 手动挑选的标签 (无 _auto 标记) 也保留 —— 回显只替换引擎抽的那部分,
          // 否则 auto 模式下用户从挑选器加的词会在下一次生成时被静默清空。
          const excluded = new Set(st.exclude_categories || []);
          const libPath = node._taglibGetLibPath?.() || new Map();
          const kept = (st.tags || []).filter((t) => {
            if (t.pinned) return true;  // 钉选必含常开: 生成回显不清掉 📌 标签
            if (!t._auto) return true;
            const p = libPath.get(String(t.en).toLowerCase());
            return p && excluded.has(p[0]);
          });
          const have = new Set(kept.map((t) => t.en.toLowerCase()));
          // NSFW / 性别反查: 直接用面板索引带来的标记表 (无需全量库)
          const nsfwSet = PANEL_NSFW;
          const genderSet = LIB_GENDER;
          const fresh = [];
          for (const t of parsed) {
            if (!t.en || have.has(t.en.toLowerCase())) continue;
            // cat 优先用后端带回的; 没有时前端按 libPath 反查 (en 可能是格式化后的)
            let cat = t.cat || "";
            const p = libPath.get(t.en.toLowerCase());
            if (!cat && p) cat = p[0];
            have.add(t.en.toLowerCase());
            const gSym = t.gender || genderSet.get(String(t.en).toLowerCase()) || "";
            fresh.push({
              en: t.en, zh: t.zh || "",
              nsfw: !!t.nsfw || nsfwSet.has(String(t.en).toLowerCase()),
              gender: gSym,
              enabled: true, _cat: cat, _auto: true,  // _auto=引擎抽取, 下轮回显可被替换
            });
          }
          // 分组标题数据: cat → fillGroups (钉选保留词也计入分组)
          const keptWithCat = kept.map((t) => {
            if (!t._cat) {
              const p = libPath.get(String(t.en).toLowerCase());
              t._cat = t._cat || (p && p[0]) || "";
            }
            return t;
          });
          const groups = new Map();
          for (const t of [...keptWithCat.filter((x) => x.pinned), ...fresh]) {
            const k = t._cat || "其他";
            if (!groups.has(k)) groups.set(k, []);
            groups.get(k).push(t);
          }
          node._taglibPendingGroups = groups;
          // mutex 让位标签 (灰显+删除线, 仅 auto 模式渲染时生效)
          let dropped = output.taglib_echo_dropped;
          if (typeof dropped === "string") {
            try { dropped = JSON.parse(Array.isArray(dropped) ? dropped.join("") : dropped); }
            catch { dropped = []; }
          }
          node._mutexDropped = new Set((Array.isArray(dropped) ? dropped : [])
            .map((x) => String(x).toLowerCase()));
          // 按库类目顺序合并 (钉选不顶置, 随类目走)
          const catIdx = (t) => {
            const c = t._cat || "";
            const i = PANEL_CATS.findIndex((x) => x.name === c);
            return c ? (i === -1 ? 999 : i) : -1;
          };
          const merged = [...keptWithCat, ...fresh].map((t, i) => [t, i])
            .sort((a, b) => catIdx(a[0]) - catIdx(b[0]) || a[1] - b[1])
            .map((x) => x[0]);
          w.value = JSON.stringify({ ...st, tags: merged });
          node._taglibPanelApi?.refresh?.();
          node.setDirtyCanvas?.(true, true);
        } catch {}
      });
    } catch {}
  },
});
