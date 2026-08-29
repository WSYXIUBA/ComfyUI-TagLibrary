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
const MANAGER_URL = "/taglib?embed=1";
const SETTING_PREFIX = "TagLibrary.";

/* settings keys */
const SET_DEFAULT_MODE = SETTING_PREFIX + "default_mode";
const SET_DEFAULT_NSFW = SETTING_PREFIX + "default_nsfw";
const SET_SCALE = SETTING_PREFIX + "chip_scale";
const SET_LANG = SETTING_PREFIX + "display_lang";

let LIB_CACHE = null;
let LIB_FETCHING = null;
let LIB_PATH = new Map();  // en_l -> [大类名, 子分类名, 孙分类名|null]

function buildLibPath(lib) {
  const m = new Map();
  for (const c of lib.categories || []) {
    for (const s of c.subcategories || []) {
      if (s.groups && s.groups.length) {
        for (const g of s.groups) {
          for (const t of g.tags || []) m.set(t.en.toLowerCase(), [c.name, s.name, g.name]);
        }
      }
      for (const t of s.tags || []) {
        if (!m.has(t.en.toLowerCase())) m.set(t.en.toLowerCase(), [c.name, s.name, null]);
      }
    }
  }
  return m;
}

async function fetchLibrary() {
  if (LIB_CACHE) return LIB_CACHE;
  if (!LIB_FETCHING) {
    LIB_FETCHING = fetch("/taglib/api/library")
      .then((r) => r.json())
      .then((data) => {
        LIB_CACHE = data.library || { categories: [] };
        LIB_PATH = buildLibPath(LIB_CACHE);
        return LIB_CACHE;
      })
      .finally(() => { LIB_FETCHING = null; });
  }
  return LIB_FETCHING;
}

function invalidateLibraryCache() {
  LIB_CACHE = null;
  LIB_PATH = new Map();
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

/* ---------------------------------------------------- state */

function defaultState() {
  return {
    // 面板只显示这里 —— "已添加到本节点" 的标签, 每条:
    // { en, zh?, nsfw?, enabled:bool, pinned?:true }
    tags: [],
    // 排除的类目 (分类名数组): 唯一的范围控制 —
    // 随机抽不到、🎲填充不填也不清空该分类的已填标签
    exclude_categories: [],
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

function setState(node, patch) {
  const w = node.widgets?.find((x) => x.name === "selection_state");
  if (!w) return;
  w.value = JSON.stringify({ ...getState(node), ...patch });
  node.setDirtyCanvas?.(true, true);
}

/* ---------------------------------------------------- panel build */

export function buildPanelWidget(node, container) {
  injectPanelStyle();
  container.classList.add("taglib-panel");

  const ui = { activeCat: null, filter: "", mode: "manual", chipsBoxHeight: null,
               previewMode: getState(node).preview_mode || "simple" };
  // activeCat=null -> 显示全部分类的 chips; 点胶囊切换到该分类; 再点取消回全部


  container.innerHTML = `
    <div class="tl-head">
      <span class="tl-logo">🏷</span>
      <span class="tl-title">标签库</span>
      <span class="tl-head-spacer"></span>
      <button class="tl-btn tl-nsfw-btn" data-act="nsfw" title="NSFW: 关=剔除并不显示 NSFW 标签; 开=显示且可输出">NSFW</button>
      <button class="tl-btn icon tl-lang-btn" data-act="lang" title="标签显示语言 (双语/英文/中文)">文A</button>
      <button class="tl-btn icon tl-conflict-btn" data-act="conflict" title="防冲突开关 (随机时同组互斥)">🚫</button>
      <button class="tl-btn primary" data-act="addtags" title="从标签库挑选标签添加">➕ 添加标签</button>
    </div>
    <div class="tl-toolbar">
      <input class="tl-search" placeholder="🔍 过滤已添加的标签…" />
      <div class="tl-seg tl-mode-seg" title="工作模式">
        <button data-mode="manual">手动</button>
        <button data-mode="auto">自动</button>
      </div>
      <div class="tl-seg tl-eng-seg" title="自动模式引擎: Fast=极速 / Smart=依赖+权重+多样性" style="display:none">
        <button data-eng="default_fast">Fast</button>
        <button data-eng="default_smart">Smart</button>
      </div>
    </div>
    <div class="tl-chipzone"></div>
    <div class="tl-preview-row">
      <div class="tl-preview"></div>
      <button class="tl-btn icon tl-lock-btn" data-act="lock" title="锁定当前结果为手动选择">🔒</button>
      <button class="tl-btn icon tl-pv-btn" data-act="pv" title="预览模式: 简洁 → 带权重 → 调试">👁</button>
      <button class="tl-roll-btn" data-act="roll" title="随机抽取标签填入框内 (按当前模式和设置)">🎲 填充</button>
    </div>
  `;

  const $ = (cls) => container.querySelector(cls);
  const chipzoneEl = $(".tl-chipzone");
  const searchEl = $(".tl-search");
  const previewEl = $(".tl-preview");
  const modeSeg = $(".tl-mode-seg");
  const nsfwBtn = $(".tl-nsfw-btn");

  /* ---------- mode (二态: 手动 / 自动) — 两模式界面相同, 自动=queue 时引擎填充 ---------- */
  function syncModeWidgets() {
    const modeW = node.widgets?.find((x) => x.name === "mode");
    if (modeW) {
      ui.mode = modeW.value === "random_mix" ? "auto"
        : modeW.value === "random_by_category" ? "manual" : modeW.value;
    }
    modeSeg.querySelectorAll("button").forEach((b) =>
      b.classList.toggle("active", b.dataset.mode === ui.mode));
    if (typeof syncEngSeg === "function") syncEngSeg();
  }

  function setMode(m) {
    ui.mode = m;
    const modeW = node.widgets?.find((x) => x.name === "mode");
    if (modeW) { modeW.value = m; modeW.callback?.(m); }
    syncModeWidgets();
    renderAll();
    node.setDirtyCanvas?.(true);
  }

  /* ---------- 引擎切换 (Fast/Smart, 写入 selection_state.random_config_ref) ---------- */
  const engSeg = $(".tl-eng-seg");
  function syncEngSeg() {
    if (!engSeg) return;
    engSeg.style.display = ui.mode === "auto" ? "" : "none";
    const ref = getState(node).random_config_ref || "default_fast";
    engSeg.querySelectorAll("button").forEach((b) =>
      b.classList.toggle("active", b.dataset.eng === ref));
  }
  engSeg?.querySelectorAll("button").forEach((b) => {
    b.onclick = () => {
      setState(node, { random_config_ref: b.dataset.eng });
      syncEngSeg();
      if (ui.mode === "auto") renderTags();
    };
  });

  /* ---------- 锁定当前结果为手动 ---------- */
  $(".tl-lock-btn").onclick = () => {
    const st = getState(node);
    if (!(st.tags || []).length) return toast("当前没有标签可锁定");
    setMode("manual");
    toast("已锁定当前结果为手动选择 (不再随生成变化)");
  };

  /* ---------- 预览模式: 简洁 / 带权重 / 调试 ---------- */
  const PV_MODES = ["simple", "weighted", "debug"];
  $(".tl-pv-btn").onclick = () => {
    const cur = getState(node).preview_mode || "simple";
    const next = PV_MODES[(PV_MODES.indexOf(cur) + 1) % PV_MODES.length];
    setState(node, { preview_mode: next });
    ui.previewMode = next;
    previewEl.textContent = outputPreview(getState(node).tags, next);
    toast(`预览模式: ${{ simple: "简洁", weighted: "带权重", debug: "调试" }[next]}`);
  };

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
    // 填充分组标题行: 最近一次 🎲填充 的标签按大类分组显示
    const fillCats = ui.fillGroups instanceof Map ? ui.fillGroups : null;
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
          head.textContent = `── ${grp} ──`;
          chipzoneEl.appendChild(head);
        }
      } else {
        lastGroup = null;
      }
      const el = document.createElement("span");
      const dropped = ui.mode === "auto" && node._mutexDropped?.has(String(t.en).toLowerCase());
      el.className = "tl-ttag" + (t.enabled === false ? "" : " on") + (t.nsfw ? " nsfw" : "")
        + (dropped ? " tl-dropped" : "");
      el.draggable = true;
      el.title = t.enabled === false
        ? "已停用 — 点击启用"
        : "已启用 · 拖动排序 / 📌随机必含 / ✕移除";
      el.innerHTML =
        `<span class="tl-pin${t.pinned ? " pinned" : ""}" title="随机时必含">📌</span>` +
        `<b>${chipLabel(t)}</b>` +
        (t.zh && getLang() === "en" ? `<i class="t-zh">${t.zh}</i>` : "") +
        `<span class="tl-x" title="移除">✕</span>`;
      el.querySelector(".tl-pin").onclick = (e) => { e.stopPropagation(); togglePinIdx(idx); };
      el.querySelector(".tl-x").onclick = (e) => { e.stopPropagation(); removeTagIdx(idx); };
      el.onclick = () => toggleEnabledIdx(idx);
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

  function outputPreview(tags, mode) {
    mode = mode || getState(node).preview_mode || "simple";
    if (mode === "debug") {
      const enabledN = tags.filter((t) => t.enabled !== false).length;
      return `(调试) 共 ${tags.length} · 启用 ${enabledN} · 模式 ${ui.mode} · 引擎 `
        + (getState(node).random_config_ref || "default_fast");
    }
    const weighted = mode === "weighted";
    const withW = tags.filter((t) => t.enabled !== false && t.weight && t.weight !== 1).length;
    if (weighted && withW) {
      const parts = tags.filter((t) => t.enabled !== false)
        .map((t) => t.weight && t.weight !== 1 ? `${t.en} (×${t.weight})` : t.en);
      return parts.length ? "→ " + parts.join(", ") : "(无启用标签)";
    }
    return outputPreviewSimple(tags);
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
      .filter((t) => t.enabled !== false)
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

  /* ---------- 🎲 填充: 子分类粒度抽取, 排除类目=0~0 ---------- */
  function getFillRange(st, subId) {
    if (st.fill_master ?? true) {
      const lo = st.fill_master_min ?? 1, hi = st.fill_master_max ?? 1;
      return [Math.min(lo, hi), Math.max(lo, hi)];
    }
    const r = (st.fill_sub_ranges || {})[subId] || { min: 1, max: 1 };
    return [Math.min(r.min, r.max), Math.max(r.min, r.max)];
  }

  async function fetchConflicts() {
    try {
      const r = await fetch("/taglib/api/conflicts");
      const d = await r.json();
      // 引用解析: sub/cat → LIB_CACHE 里的标签集合
      const idxSrc = {};
      for (const cat of (typeof LIB_CACHE?.categories === "object" ? LIB_CACHE.categories : []) || []) {
        const subs = idxSrc[cat.name] = {};
        for (const sub of cat.subcategories || []) {
          subs[sub.name] = (sub.tags || []).map((t) => String(t.en).toLowerCase());
        }
      }
      const resolve = (ref) => {
        if (!ref) return [];
        if (ref.kind === "tag") return [String(ref.value).toLowerCase()];
        if (ref.kind === "tags") return (ref.value || []).map((v) => String(v).toLowerCase());
        if (ref.kind === "cat") {
          const out = [];
          Object.values(idxSrc[String(ref.value)] || {}).forEach((arr) => out.push(...arr));
          return out;
        }
        if (ref.kind === "sub") {
          const [c, s] = String(ref.value).split("/");
          return [...((idxSrc[c] || {})[s] || [])];
        }
        return [];
      };
      const map = new Map();
      const link = (a, b) => {
        if (!a || !b || a === b) return;
        if (!map.has(a)) map.set(a, new Set());
        map.get(a).add(b);
      };
      for (const rule of d.rules || []) {
        const Ls = resolve(rule.left);
        const Rs = (rule.right || []).flatMap(resolve);
        for (const a of Ls) for (const b of Rs) { link(a, b); link(b, a); }
      }
      return map;
    } catch { return new Map(); }
  }

  function pickFrom(list, n, usedEn, conflictMap) {
    const bag = [...list];
    const out = [];
    const banned = new Set();
    const grow = () => {
      if (!conflictMap) return;
      for (const e of usedEn) {
        for (const b of conflictMap.get(e) || []) banned.add(b);
      }
    };
    grow();
    for (let i = 0; i < n && bag.length; i++) {
      const idx = Math.floor(Math.random() * bag.length);
      const tag = bag.splice(idx, 1)[0];
      const plo = tag.en.toLowerCase();
      if (usedEn.has(plo)) { i--; continue; }
      // 反冲突: 与已抽中的任一标签互斥 → 让位
      if (conflictMap && banned.has(plo)) { i--; continue; }
      usedEn.add(plo);
      grow();
      out.push(tag);
    }
    return out;
  }

  function buildSubPools(nsfwOn) {
    // [{catName, subId, subName, tags:[...]}]  排除类目跳过 (一级"大类" 或 二级"大类/子分类")
    const excluded = new Set(getState(node).exclude_categories || []);
    const cats = (typeof LIB_CACHE?.categories === "object" ? LIB_CACHE.categories : []) || [];
    const subs = [];
    for (const cat of cats) {
      if (excluded.has(cat.name)) continue;
      for (const sub of cat.subcategories || []) {
        if (excluded.has(`${cat.name}/${sub.name}`)) continue; // 二级排除同样不填充
        const tags = (sub.tags || []).filter((t) =>
          t.enabled !== false && (nsfwOn || !t.nsfw));
        if (tags.length) subs.push({ catName: cat.name, subId: sub.id, subName: sub.name, tags });
      }
    }
    return subs;
  }

  async function rollFill() {
    const st = getState(node);
    const nsfwOn = getNsfwEffective(node);
    const excluded = new Set(st.exclude_categories || []);
    // ① 清空: 非"排除类目"的已有标签全部清掉 (排除类目的标签保留不动)
    const keptTags = st.tags.filter((t) => {
      const p = LIB_PATH.get(String(t.en).toLowerCase());
      return p && excluded.has(p[0]);
    });
    // ② 按子分类抽取: 每个子分类读范围, 反冲突避让 (抽到一边另一边让位)
    const subPools = buildSubPools(nsfwOn);
    const usedEn = new Set(keptTags.map((t) => t.en.toLowerCase()));
    const conflictMap = st.avoid_conflicts !== false ? await fetchConflicts() : null;
    const picked = [];
    for (const sp of subPools) {
      const [mn, mx] = getFillRange(st, sp.subId);
      if (mx <= 0) continue;
      const n = mn + Math.floor(Math.random() * (mx - mn + 1));
      picked.push(...pickFrom(sp.tags, n, usedEn, conflictMap).map((t) => ({ ...t, _cat: sp.catName })));
    }
    if (!picked.length) return;
    // ③ 写回: 排除类目的保留标签 + 新填充
    setState(node, { tags: [...keptTags, ...picked.map(({ _cat, ...rest }) => ({ ...rest, enabled: true }))] });
    ui.fillGroups = groupByCat(picked);
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
    container.querySelector(".tl-lang-btn").textContent =
      next === "bilingual" ? "文A" : next === "en" ? "EN" : "中";
    // 全量重渲染: 已选标签 chip、填充分组、预览全部跟随语言
    renderAll();
  }

  function chipLabel(t) {
    const lang = getLang();
    if (lang === "en") return t.en;
    if (lang === "zh") return (t.zh || t.en);
    return `${t.en}${t.zh ? `<span style="opacity:.55;font-size:10px">${t.zh}</span>` : ""}`;
  }

  function renderConflictBtn() {
    const on = getState(node).avoid_conflicts !== false;
    const b = container.querySelector(".tl-conflict-btn");
    b.textContent = on ? "🚫" : "⚔";
    b.title = on ? "防冲突已开启 (随机时同组互斥) — 点击关闭"
                 : "防冲突已关闭 — 点击开启";
    b.style.opacity = on ? "1" : ".45";
  }

  function renderAll() {
    renderTags(); renderNsfw(); renderConflictBtn(); syncEngSeg();
  }

  // 全局偏好变更 -> 本节点面板实时跟随。
  // 本版本前端 extensionManager 没有 settings change 事件面 (setting/setting.settings
  // 均非 EventTarget, Pinia $subscribe 也不触发), 所以: 设置页写入路径走 onGlobalChange
  // 即时刷新; 其余来源 (ComfyUI 设置面板等) 用 2s 轻量轮询兜底。
  const SYNC_KEYS = [
    SET_DEFAULT_MODE, SET_DEFAULT_NSFW, SET_SCALE, SET_LANG,
    SETTING_PREFIX + "chip_font_size", SETTING_PREFIX + "chip_radius",
  ];
  const lastVals = new Map(SYNC_KEYS.map((k) => [k, getSetting(k, null)]));
  function pollSettingsSync() {
    let changed = false;
    for (const k of SYNC_KEYS) {
      const v = getSetting(k, null);
      if (v !== lastVals.get(k)) { lastVals.set(k, v); changed = true; }
    }
    if (changed) { applyScale(); renderAll(); }
  }
  setInterval(pollSettingsSync, 2000);

  /* ---------- ➕ 添加标签窗口 (全库挑选器) ---------- */
  function openTagPicker() {
    let dlg = document.getElementById("taglib-picker-dialog");
    if (dlg) { dlg.close(); dlg.remove(); }
    dlg = document.createElement("dialog");
    dlg.id = "taglib-picker-dialog";
    dlg.style.cssText =
      "width:min(92vw,1200px);height:min(90vh,860px);border:none;border-radius:14px;" +
      "padding:0;background:#15171d;color:#e3e7ee;max-width:none;max-height:none;";
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
        fetchLibrary().then(renderAll);
        window.dispatchEvent(new CustomEvent("taglib-updated"));
      }
    });
  }

  /* ---------- 随机设置 (原 ⚙ 弹窗) 已并入「添加标签 → ⚙ 设置」页签 ---------- */

  /* ---------- events ---------- */
  container.querySelector('[data-act="addtags"]').onclick = openTagPicker;
  container.querySelector('[data-act="roll"]').onclick = rollFill;
  container.querySelector('[data-act="lang"]').onclick = cycleLang;
  container.querySelector('[data-act="conflict"]').onclick = () => {
    const cur = getState(node).avoid_conflicts !== false;
    setState(node, { avoid_conflicts: !cur });
    renderConflictBtn();
  };
  searchEl.oninput = () => { ui.filter = searchEl.value; renderTags(); };
  modeSeg.querySelectorAll("button").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));

  /* ---------- init ---------- */
  applyScale();
  syncModeWidgets();
  fetchLibrary()
    .then(renderAll)
    .catch((err) => { container.innerHTML = `<div class="tl-empty">标签库加载失败: ${err}</div>`; });

  return {
    refresh: async (opts = {}) => {
      // reloadLib 仅在库真的变了时用 (管理页保存/热同步导入);
      // 每轮队列的自动回显刷新不重拉, 避免无谓的 200KB 请求
      if (opts.reloadLib) {
        invalidateLibraryCache();
        await fetchLibrary();
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
  const ui = { activeCat: null, filter: "", picked: [], tab: "pick", libTouched: false };  // pick | exclude | manager | settings

  rootEl.innerHTML = `
    <style>
      .tp-wrap { display:flex; flex-direction:column; height:100%; font:12.5px/1.5 "Segoe UI","Microsoft YaHei",sans-serif; }
      .tp-head { display:flex; align-items:center; gap:10px; padding:12px 16px; border-bottom:1px solid rgba(255,255,255,.09); }
      .tp-head h2 { margin:0; font-size:15px; }
      .tp-search { flex:1; max-width:420px; background:rgba(0,0,0,.35); border:1px solid rgba(255,255,255,.12);
                   border-radius:8px; color:#e3e7ee; padding:6px 12px; outline:none; font-size:12.5px; }
      .tp-cols { flex:1; display:flex; min-height:0; }
      .tp-cats { width:200px; border-right:1px solid rgba(255,255,255,.08); overflow-y:auto; padding:10px; display:flex; flex-direction:column; gap:4px; }
      .tp-cat {
        display:flex; align-items:center; gap:7px; padding:7px 10px; border-radius:9px;
        cursor:pointer; border:1px solid transparent; transition:.12s;
      }
      .tp-cat:hover { background:rgba(255,255,255,.05); }
      .tp-cat.active { background:color-mix(in srgb, currentColor 14%, transparent); border-color:currentColor; }
      .tp-cat .nm { flex:1; }
      .tp-cat .ct { font-size:11px; color:#8b93a5; }
      .tp-chips { flex:1; overflow-y:auto; padding:14px 16px; }
      .tp-sub { font-size:11px; color:#8b93a5; margin:10px 0 6px; letter-spacing:.03em; }
      .tp-grid { display:flex; flex-wrap:wrap; gap:5px; }
      .tp-tag {
        --c:#54a0ff;
        border:1px solid color-mix(in srgb, var(--c) 30%, rgba(255,255,255,.13));
        background:color-mix(in srgb, var(--c) 8%, rgba(255,255,255,.04));
        border-radius:8px; padding:3px 10px; cursor:pointer; font-size:12px; transition:.12s;
      }
      .tp-tag:hover { background:color-mix(in srgb, var(--c) 20%, transparent); transform:translateY(-1px); }
      .tp-tag.picked { background:var(--c); color:#fff; box-shadow:0 0 8px -2px var(--c); }
      .tp-tag.picked::before { content:"✓ "; }
      .tp-tag.nsfw { --c:#e5484d; }   /* NSFW = 红色 (与管理页一致) */
      .tp-foot { display:flex; align-items:center; gap:10px; padding:11px 16px; border-top:1px solid rgba(255,255,255,.09); }
      .tp-count { font-size:13px; font-weight:600; color:#54a0ff; }
      .tp-btn { border:1px solid rgba(255,255,255,.15); background:rgba(255,255,255,.06); color:inherit;
                border-radius:8px; padding:7px 18px; cursor:pointer; font-size:13px; }
      .tp-btn.primary { background:linear-gradient(135deg,rgba(84,160,255,.35),rgba(84,160,255,.2));
                        border-color:rgba(84,160,255,.55); font-weight:600; }
      .tp-btn:hover { filter:brightness(1.25); }
      .tp-tabbtn {
        border:1px solid rgba(255,255,255,.14); background:transparent; color:#aab3c5;
        border-radius:8px; padding:5px 12px; cursor:pointer; font-size:12.5px;
      }
      .tp-tabbtn.active { background:rgba(84,160,255,.18); border-color:rgba(84,160,255,.5); color:#cfe4ff; }
      .tp-exc-card {
        display:flex; align-items:center; gap:10px; padding:9px 13px; margin-bottom:6px;
        border:1px solid rgba(255,255,255,.10); border-radius:10px; background:rgba(255,255,255,.03);
      }
      .tp-exc-card.excluded { border-color: rgba(255,107,107,.55); background: rgba(255,71,87,.10); }
      .tp-exc-card .nm { flex:1; font-size:13px; }
      .tp-exc-card .why { font-size:11px; color:#f7a4b1; }
      .tp-exc-hint { font-size:12px; color:#8b93a5; margin-bottom:12px; line-height:1.6; }
      .tp-master { border:1px solid rgba(84,160,255,.35); background:rgba(84,160,255,.08);
                   border-radius:10px; padding:10px; margin-bottom:8px; }
      .tp-range { display:inline-flex; align-items:center; gap:4px; }
      .tp-range input { width:44px; background:rgba(0,0,0,.35); border:1px solid rgba(255,255,255,.14);
                        border-radius:6px; color:#e3e7ee; padding:3px 5px; font-size:11.5px; text-align:center; }
      .tp-range-hint { font-size:10.5px; color:#6b7385; margin-top:5px; }
      .tp-set-h { font-size:12px; font-weight:700; color:#8fb8ff; letter-spacing:.05em; margin:20px 0 10px; }
      .tp-set-h:first-child { margin-top:0; }
      .tp-set-h .sub { color:#6b7385; font-weight:400; font-size:11px; }
      .tp-set-card { max-width:560px; border:1px solid rgba(255,255,255,.09); border-radius:12px;
                     background:rgba(255,255,255,.03); padding:14px 16px; margin-bottom:6px; }
      .tp-set-row { margin-bottom:13px; }
      .tp-set-row:last-child { margin-bottom:0; }
      .tp-set-lab { font-size:12px; color:#aab3c5; margin-bottom:4px; }
      .tp-set-hint { font-size:11px; color:#6b7385; margin-top:3px; line-height:1.5; }
      .tp-set-row select, .tp-set-row input[type="text"], .tp-set-row input[type="number"] {
        background:rgba(0,0,0,.35); border:1px solid rgba(255,255,255,.14); border-radius:8px;
        color:#e3e7ee; padding:6px 9px; font-size:12.5px; outline:none;
      }
      .tp-set-row select:focus, .tp-set-row input:focus { border-color:rgba(84,160,255,.55); }
      .tp-set-row input[type="checkbox"] { width:15px; height:15px; accent-color:#54a0ff; }
      .tp-sync-note { font-size:11px; color:#6b7385; margin-top:14px; line-height:1.6; max-width:560px; }
      .tp-cf-stats { font-size:12px; color:#aab3c5; margin-bottom:12px; }
      .tp-cf-list { display:flex; flex-direction:column; gap:6px; margin-bottom:20px; }
      .tp-cf-rule { display:flex; align-items:center; gap:8px; flex-wrap:wrap;
        border:1px solid rgba(255,255,255,.09); border-radius:10px;
        background:rgba(255,255,255,.03); padding:8px 12px; font-size:12.5px; }
      .tp-cf-rule .cf-l { font-weight:600; color:#cfe4ff; }
      .tp-cf-rule .cf-vs { color:#8b93a5; }
      .tp-cf-rule .cf-rt { border:1px solid rgba(255,255,255,.16); border-radius:6px;
        padding:1px 7px; font-size:11.5px; color:#cfd6e4; }
      .tp-cf-rule .cf-note { color:#6b7385; font-size:11px; }
      .tp-cf-rule .cf-warn { color:#ff6b6b; font-size:11px; }
      .tp-cf-rule .cf-del { margin-left:auto; background:transparent; cursor:pointer;
        border:1px solid rgba(255,107,107,.4); color:#ff9d9d; border-radius:6px;
        padding:2px 8px; font-size:11px; }
      .tp-cf-rule .cf-del:hover { background:rgba(255,71,87,.15); }
      .tp-cf-h { font-size:12px; font-weight:700; color:#8fb8ff; margin:16px 0 10px; }
      .tp-cf-form { border:1px solid rgba(255,255,255,.09); border-radius:12px;
        background:rgba(255,255,255,.03); padding:14px 16px; max-width:640px; }
      .tp-cf-frow { display:flex; align-items:center; gap:8px; margin-bottom:10px; flex-wrap:wrap; }
      .tp-cf-frow .cf-klab { font-size:11.5px; color:#8b93a5; width:52px; }
      .tp-cf-frow select, .tp-cf-frow input {
        background:rgba(0,0,0,.35); border:1px solid rgba(255,255,255,.14); border-radius:8px;
        color:#e3e7ee; padding:5px 9px; font-size:12px; outline:none; }
      .tp-cf-frow input:focus { border-color:rgba(84,160,255,.55); }
      .tp-cf-add { border:1px solid rgba(84,160,255,.5); background:rgba(84,160,255,.12);
        color:#9ecbff; border-radius:7px; padding:4px 12px; cursor:pointer; font-size:12px; }
      .tp-cf-add:hover { background:rgba(84,160,255,.22); }
      .tp-cf-rights { display:flex; flex-wrap:wrap; gap:5px; margin:4px 0 10px 60px; min-height:24px; }
      .tp-cf-rights .cf-rt-chip { display:inline-flex; align-items:center; gap:5px;
        border:1px solid rgba(46,204,113,.45); background:rgba(46,204,113,.08);
        border-radius:6px; padding:1px 7px; font-size:11.5px; }
      .tp-cf-rights .cf-rt-chip .x { cursor:pointer; opacity:.6; }
      .tp-cf-rights .cf-rt-chip .x:hover { opacity:1; color:#ff6b6b; }
      .tp-cf-save { background:linear-gradient(135deg,#0071e3,#54a0ff); border:0; color:#fff;
        border-radius:8px; padding:6px 18px; cursor:pointer; font-weight:600; font-size:12.5px; }
    </style>
    <div class="tp-wrap">
      <div class="tp-head">
        <h2>🏷 从标签库添加</h2>
        <button class="tp-tabbtn tp-picktab active">挑标签</button>
        <button class="tp-tabbtn tp-excludetab">🚫 排除类目</button>
        <button class="tp-tabbtn tp-mgrtab">🏷 标签库管理</button>
        <button class="tp-tabbtn tp-cftab">🧷 防冲突关系</button>
        <button class="tp-tabbtn tp-settab">⚙ 设置</button>
        <input class="tp-search" placeholder="🔍 搜中文 / 英文 / 别名…" />
        <span style="flex:1"></span>
      </div>
      <div class="tp-cols">
        <aside class="tp-cats"></aside>
        <section class="tp-chips"><div class="tp-empty" style="padding:40px;text-align:center;color:#8b93a5">加载中…</div></section>
        <section class="tp-excview" style="display:none;flex:1;overflow-y:auto;padding:16px 20px;"></section>
        <section class="tp-mgrview" style="display:none;flex:1;min-width:0;"></section>
        <section class="tp-cfview" style="display:none;flex:1;overflow-y:auto;padding:16px 22px;"></section>
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

  /* ---------- 三级侧栏树: 大类(可折叠) > 子分类 > 孙分类 + 抽取范围设置 ---------- */
  function renderCats() {
    catsBox.innerHTML = "";
    if (!ui.openCats) ui.openCats = new Set();
    const allCount = libCats().reduce((n, c) => n + countTags(c), 0);
    // ---- 总控制开关 + 范围 (放在"全部"上面) ----
    const st = getState(node);
    const master = st.fill_master ?? true;
    const mlo = st.fill_master_min ?? 1;
    const mhi = st.fill_master_max ?? 1;
    const masterBox = document.createElement("div");
    masterBox.className = "tp-master";
    masterBox.innerHTML = `
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none">
        <input type="checkbox" class="tp-master-sw" ${master ? "checked" : ""}
          style="width:14px;height:14px;accent-color:#54a0ff"/>
        <b style="font-size:12px">总控制</b>
      </label>
      <div class="tp-range" style="${master ? "" : "opacity:.35"}">
        <input type="number" class="tp-master-min" min="0" max="20" value="${mlo}"/>
        <span>~</span>
        <input type="number" class="tp-master-max" min="0" max="20" value="${mhi}"/>
      </div>
      <div class="tp-range-hint">每个子分类抽取 ${mlo}~${mhi} 个</div>`;
    catsBox.appendChild(masterBox);
    masterBox.querySelector(".tp-master-sw").onchange = (e) => {
      setState(node, { fill_master: e.target.checked });
      renderCats();
    };
    const saveMaster = () => {
      const mn = parseInt(masterBox.querySelector(".tp-master-min").value) || 0;
      const mx = parseInt(masterBox.querySelector(".tp-master-max").value) || 0;
      setState(node, { fill_master_min: Math.min(20, Math.max(0, mn)),
                       fill_master_max: Math.min(20, Math.max(0, mx)) });
      masterBox.querySelector(".tp-range-hint").textContent =
        `每个子分类抽取 ${Math.min(mn,mx)}~${Math.max(mn,mx)} 个`;
    };
    masterBox.querySelector(".tp-master-min").onchange = saveMaster;
    masterBox.querySelector(".tp-master-max").onchange = saveMaster;
    // 排除的类目标注 0~0 (不填充)
    const excludedSet = new Set(getExcluded() || []);
    mkRow(catsBox, {
      id: "__all__", icon: "🗂", name: "全部", count: allCount,
      depth: 0, active: ui.activeCat === "__all__",
      onclick: () => { ui.activeCat = "__all__"; ui.activeSub = null; renderCats(); renderChips(); },
    });
    for (const c of libCats()) {
      const open = ui.openCats.has(c.id);
      const isExcluded = excludedSet.has(c.name);
      mkRow(catsBox, {
        id: c.id, icon: c.icon || "📁", name: c.name + (isExcluded ? " (0~0)" : ""), count: countTags(c),
        depth: 0, color: c.color, chevron: true, open,
        active: ui.activeCat === c.id && !ui.activeSub,
        onclick: () => { ui.activeCat = c.id; ui.activeSub = null; renderCats(); renderChips(); },
        onchevron: () => {
          open ? ui.openCats.delete(c.id) : ui.openCats.add(c.id);
          renderCats();
        },
      });
      if (!open) continue;
      for (const sub of c.subcategories || []) {
        // 子分类独立范围框 (总控制关时生效)
        const subRange = (st.fill_sub_ranges || {})[sub.id] || { min: 1, max: 1 };
        mkRow(catsBox, {
          id: sub.id, name: sub.name, count: (sub.tags || []).length,
          depth: 1, active: ui.activeSub === sub.id,
          range: isExcluded ? { min: 0, max: 0, locked: true } : subRange,
          onRange: (mn, mx) => {
            const all = { ...(getState(node).fill_sub_ranges || {}) };
            all[sub.id] = { min: mn, max: mx };
            setState(node, { fill_sub_ranges: all });
          },
          onclick: () => { ui.activeCat = c.id; ui.activeSub = sub.id; renderCats(); renderChips(); },
        });
        // 孙分类 (groups)
        for (const g of sub.groups || []) {
          mkRow(catsBox, {
            id: g.id, name: g.name, count: (g.tags || []).length,
            depth: 2, active: ui.activeSub === g.id, leaf: true,
            onclick: () => { ui.activeCat = c.id; ui.activeSub = g.id; renderCats(); renderChips(); },
          });
        }
      }
    }
  }

  function mkRow(box, { id, icon = "", name, count, depth, color, chevron, open, active, onclick, onchevron, range, onRange }) {
    const el = document.createElement("div");
    el.className = "tp-cat tp-cat-l" + depth + (active ? " active" : "");
    el.style.color = color || (depth === 0 ? "#cfd6e4" : "#aab3c5");
    if (depth === 1) el.style.paddingLeft = "22px";
    if (depth === 2) el.style.paddingLeft = "38px";
    const rangeHtml = range ? `
      <span class="tp-range" style="${range.locked ? "opacity:.35" : ""}">
        <input type="number" min="0" max="20" value="${range.min}" data-r="min" ${range.locked ? "disabled" : ""}/>
        <span>~</span>
        <input type="number" min="0" max="20" value="${range.max}" data-r="max" ${range.locked ? "disabled" : ""}/>
      </span>` : "";
    el.innerHTML =
      `${chevron ? `<span class="tp-chev">${open ? "▾" : "▸"}</span>` : (depth > 0 ? '<span class="tp-chev">·</span>' : "")}` +
      `<span>${icon}</span><span class="nm">${name}</span><span class="ct">${count}</span>` +
      rangeHtml;
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
    const q = ui.filter.trim().toLowerCase();
    if (!q) return true;
    return t.en.toLowerCase().includes(q) ||
           (t.zh || "").toLowerCase().includes(q) ||
           (t.aliases || []).some((a) => a.toLowerCase().includes(q));
  }

  function renderChips() {
    chipsBox.innerHTML = "";
    const existing = getExisting();
    // activeSub 可以是子分类 id 或孙分类 id
    const subFilter = ui.activeSub || null;
    const cats = libCats().filter((c) => !ui.activeCat || ui.activeCat === "__all__" || c.id === ui.activeCat);
    let shown = 0;
    for (const cat of cats) {
      const clr = cat.color || "#54a0ff";
      for (const sub of cat.subcategories || []) {
        if (subFilter && sub.id !== subFilter && !(sub.groups || []).some((g) => g.id === subFilter)) continue;
        const groups = sub.groups && sub.groups.length ? sub.groups : null;
        if (groups) {
          // 三级: 按 孙分类 分小节
          for (const g of groups) {
            if (subFilter && subFilter !== sub.id && g.id !== subFilter) continue;
            const hits = (g.tags || []).filter(matches);
            if (!hits.length) continue;
            shown += hits.length;
            const head = document.createElement("div");
            head.className = "tp-sub";
            head.textContent = `${cat.icon || ""} ${cat.name} / ${sub.name} / ${g.name}`;
            chipsBox.appendChild(head);
            appendGrid(hits, clr, existing);
          }
        } else {
          const hits = (sub.tags || []).filter(matches);
          if (!hits.length) continue;
          shown += hits.length;
          const head = document.createElement("div");
          head.className = "tp-sub";
          head.textContent = `${cat.icon || ""} ${cat.name} / ${sub.name}`;
          chipsBox.appendChild(head);
          appendGrid(hits, clr, existing);
        }
      }
    }
    if (!shown) chipsBox.innerHTML = `<div class="tp-empty" style="padding:40px;text-align:center;color:#8b93a5">没找到匹配的标签</div>`;
  }

  function appendGrid(hits, clr, existing) {
    const grid = document.createElement("div");
    grid.className = "tp-grid";
    for (const t of hits) {
      const isPicked = ui.picked.some((p) => p.en.toLowerCase() === t.en.toLowerCase());
      const isExisting = existing.has(t.en.toLowerCase());
      const el = document.createElement("span");
          el.className = "tp-tag" + (t.nsfw ? " nsfw" : "") + (isPicked ? " picked" : "") + (isExisting ? " dim" : "");
          if (isExisting) { el.title = "已在节点上"; el.style.opacity = ".38"; }
          else {
            el.title = t.nsfw ? "🔞 NSFW 标签" : "";
            el.onclick = () => {
              const i = ui.picked.findIndex((p) => p.en.toLowerCase() === t.en.toLowerCase());
              if (i >= 0) ui.picked.splice(i, 1);
              else ui.picked.push({ en: t.en, zh: t.zh, nsfw: !!t.nsfw });
              countEl.textContent = ui.picked.length;
              el.classList.toggle("picked", i < 0);
            };
          }
          el.innerHTML = `${t.en}${t.zh ? `<span style="opacity:.55"> ${t.zh}</span>` : ""}`;
          grid.appendChild(el);
        }
        chipsBox.appendChild(grid);
  }

  /* ---------- 排除类目视图 ---------- */
  const excView = $(".tp-excview");
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
      ["服装系统", ["dress", "uniform", "hoodie", "kimono", "skirt", "bikini", "swimsuit", "jacket", "shirt"]],
      ["姿势动作", ["sitting", "standing", "lying", "kneeling", "arms", "walking", "running"]],
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
    excView.innerHTML = `
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
      excView.appendChild(card);

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
          excView.appendChild(subCard);
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
              excView.appendChild(gCard);
            }
          }
        }
      }
    }
  }

  /* ---------- 页签: 挑标签 | 排除类目 | 标签库管理 | 设置 ---------- */
  const mgrView = $(".tp-mgrview");
  const setView = $(".tp-setview");

  // 内嵌管理页 (iframe 懒加载, 首次进入才创建; 离开/关闭时按需刷新库缓存)
  function ensureMgrFrame() {
    ui.libTouched = true;
    if (!mgrView.querySelector("iframe")) {
      mgrView.innerHTML =
        `<iframe src="${MANAGER_URL}" style="width:100%;height:100%;border:0;display:block;background:#17191f"></iframe>`;
    }
  }

  function refreshLibIfTouched() {
    if (!ui.libTouched) return;
    ui.libTouched = false;
    invalidateLibraryCache();
    fetchLibrary().then(() => { renderCats(); renderChips(); });
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
      <div class="tp-set-h">节点参数 <span class="sub">· 存入当前节点, 随工作流保存</span></div>
      <div class="tp-set-card">
        ${row("📌 钉选标签必含", `<input type="checkbox" class="sv-pinned" ${st.pinned_required !== false ? "checked" : ""}/>`,
          "开启后带 📌 的标签随机时一定出现")}
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
      <div class="tp-set-h">全局偏好 <span class="sub">· 与 ComfyUI 设置面板「标签库」双向同步</span></div>
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
      <div class="tp-sync-note">💡 节点参数即改即存; 全局偏好写入 ComfyUI 设置 (设置面板搜「标签库」是同一批值, 两边改都生效)。</div>
    `;
    // 节点参数: 即改即存 + 让节点面板实时跟随
    const saveNode = (patch) => { setState(node, patch); onNodeState?.(); };
    $(".sv-pinned").onchange = (e) => saveNode({ pinned_required: e.target.checked });
    $(".sv-sep").onchange = (e) => saveNode({ separator: e.target.value });
    $(".sv-w").onchange = (e) => saveNode({ use_weights_syntax: e.target.checked });
    $(".sv-dd").onchange = (e) => saveNode({ dedupe: e.target.checked });
    $(".sv-search").onchange = (e) => saveNode({ search_text: e.target.value.trim() });
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
  const cfView = $(".tp-cfview");
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
    cfView.innerHTML = `<div style="padding:30px;text-align:center;color:#8b93a5">加载中…</div>`;
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
    if (ui.tab === "manager" && tab !== "manager") refreshLibIfTouched();
    ui.tab = tab;
    rootEl.querySelector(".tp-picktab").classList.toggle("active", tab === "pick");
    rootEl.querySelector(".tp-excludetab").classList.toggle("active", tab === "exclude");
    rootEl.querySelector(".tp-mgrtab").classList.toggle("active", tab === "manager");
    rootEl.querySelector(".tp-cftab").classList.toggle("active", tab === "cf");
    rootEl.querySelector(".tp-settab").classList.toggle("active", tab === "settings");
    for (const el of pickCols) el.style.display = tab === "pick" ? "" : "none";
    excView.style.display = tab === "exclude" ? "block" : "none";
    mgrView.style.display = tab === "manager" ? "flex" : "none";
    cfView.style.display = tab === "cf" ? "block" : "none";
    setView.style.display = tab === "settings" ? "block" : "none";
    searchEl.style.visibility = tab === "pick" ? "visible" : "hidden";
    const info = $(".tp-footinfo");
    if (tab === "pick") {
      info.innerHTML = `已挑选 <b class="tp-count">${ui.picked.length}</b> 个`;
    } else if (tab === "exclude") {
      const n = (getExcluded ? getExcluded().length : 0);
      info.innerHTML = `已排除 <b style="color:#ff6b6b">${n}</b> 个分类`;
    } else if (tab === "manager") {
      info.innerHTML = `管理页改动保存后全局生效`;
    } else if (tab === "cf") {
      info.innerHTML = `反冲突规则双向互斥 · 填充/自动模式生效`;
    } else {
      info.innerHTML = `节点参数即改即存 · 全局偏好双向同步`;
    }
    // 底部按钮: 挑选/排除 -> 取消+确定; 管理/防冲突/设置 -> 仅关闭
    const pickLike = tab === "pick" || tab === "exclude";
    $(".tp-cancel").style.display = pickLike ? "" : "none";
    $(".tp-ok").style.display = pickLike ? "" : "none";
    $(".tp-close2").style.display = pickLike ? "none" : "";
    if (tab === "exclude") renderExclude();
    if (tab === "settings") renderSettingsView();
    if (tab === "cf") renderCfView();
  }
  rootEl.querySelector(".tp-picktab").onclick = () => switchTab("pick");
  rootEl.querySelector(".tp-excludetab").onclick = () => switchTab("exclude");
  rootEl.querySelector(".tp-mgrtab").onclick = () => { ensureMgrFrame(); switchTab("manager"); };
  rootEl.querySelector(".tp-cftab").onclick = () => switchTab("cf");
  rootEl.querySelector(".tp-settab").onclick = () => switchTab("settings");
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
    "padding:0;background:#17191f;color:#dfe3ea;max-width:none;max-height:none;";
  // 不设 ✕ 按钮 —— 会与管理页顶栏「恢复默认库」重叠; 关闭 = 点遮罩 / Esc
  dlg.innerHTML =
    `<iframe src="${MANAGER_URL}" style="width:100%;height:100%;border:0;border-radius:14px;display:block"></iframe>`;
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
                const [, , , , , minV, maxV, cwV, stV, sepV, uwV, ddV, prV] = this.widgets_values;
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
                  if (typeof prV === "boolean") { st2.pinned_required = prV; }
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
          // getSetting 只能拿到 id, 但部分主题 (github/nord/solarized) 都是深色,
          // 用类存在性区分明暗最可靠; 具体配色差异再用 data-theme 细分。
          let pid = getSetting("Comfy.ColorPalette", "dark");
          if (typeof pid !== "string") pid = pid?.id || "dark";
          const isLightTheme = !document.documentElement.classList.contains("dark-theme");
          // holder 自身就是 .taglib-panel (buildPanelWidget 在 container 上加类)
          const panel = holder.classList.contains("taglib-panel") ? holder : holder.querySelector(".taglib-panel");
          if (panel) {
            panel.dataset.theme = pid;
            panel.classList.toggle("tl-light", isLightTheme);
            // 同步面板内弹窗 (挑选器/设置) 的主题
            for (const dlg of document.querySelectorAll("dialog.taglib-dialog, #taglib-picker-dialog")) {
              dlg.dataset.theme = pid;
              dlg.classList.toggle("tl-light", isLightTheme);
            }
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
        btn.style.cssText =
          "position:fixed;z-index:99999;top:10px;right:64px;padding:4px 10px;" +
          "border-radius:8px;border:1px solid rgba(128,140,160,.4);" +
          "background:rgba(28,30,38,.92);color:#e3e7ee;cursor:pointer;font-size:13px;";
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
          // 只替换填充部分: 排除类目的保留标签 + 引擎抽到的标签
          const excluded = new Set(st.exclude_categories || []);
          const libPath = node._taglibGetLibPath?.() || new Map();
          const kept = (st.tags || []).filter((t) => {
            const p = libPath.get(String(t.en).toLowerCase());
            return p && excluded.has(p[0]);
          });
          const have = new Set(kept.map((t) => t.en.toLowerCase()));
          // NSFW 反查集: 回显数据没带 nsfw 时从库补 (旧后端兼容)
          const nsfwSet = new Set();
          for (const c of (typeof LIB_CACHE?.categories === "object" ? LIB_CACHE.categories : []) || []) {
            for (const s of c.subcategories || []) {
              for (const t of s.tags || []) if (t.nsfw) nsfwSet.add(String(t.en).toLowerCase());
            }
          }
          const fresh = [];
          for (const t of parsed) {
            if (!t.en || have.has(t.en.toLowerCase())) continue;
            // cat 优先用后端带回的; 没有时前端按 libPath 反查 (en 可能是格式化后的)
            let cat = t.cat || "";
            const p = libPath.get(t.en.toLowerCase());
            if (!cat && p) cat = p[0];
            have.add(t.en.toLowerCase());
            fresh.push({
              en: t.en, zh: t.zh || "",
              nsfw: !!t.nsfw || nsfwSet.has(String(t.en).toLowerCase()),
              enabled: true, _cat: cat,
            });
          }
          // 分组标题数据: cat → fillGroups
          const groups = new Map();
          for (const t of fresh) {
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
          w.value = JSON.stringify({ ...st, tags: [...kept, ...fresh] });
          node._taglibPanelApi?.refresh?.();
          node.setDirtyCanvas?.(true, true);
        } catch {}
      });
    } catch {}
  },
});
