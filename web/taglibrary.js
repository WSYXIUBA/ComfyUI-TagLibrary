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
import {
  escapeHtml, toast, SETTING_PREFIX, SET_DEFAULT_MODE, SET_DEFAULT_NSFW,
  SET_SCALE, SET_LANG, LIB_CACHE, PANEL_CATS, PANEL_NSFW, LIB_PATH, LIB_GENDER,
  tagGender, fetchPanelIndex, fetchLibrary, invalidateLibraryCache,
  getSetting, setSetting, currentTheme, managerUrl, pushThemeToFrames,
  registerPanelSync, getState, setState, getNsfwEffective, getGender,
  GENDER_SEQ, GENDER_LABEL, GENDER_TITLE,
} from "./taglib-common.js";
import { mountTagPicker } from "./taglib-picker.js";

const NODE_NAME = "TagLibraryNode";

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
      // 🎲 填充 = 面板临时随机一次: seed 每次全新 (与 widget 种子无关, 那是 queue 用的)
      drawRes = await fetch("/taglib/api/draw", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: { ...st, nsfw: nsfwOn },
                               seed: Math.floor(Math.random() * 0xffffffff) }),
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
    // 库内文本统一转义 —— 词来自可导入的 .md/JSON, 不能直接进 innerHTML
    const en = escapeHtml(t.en);
    const zh = t.zh ? escapeHtml(t.zh) : "";
    if (lang === "en") return bsym + gsym + en;
    if (lang === "zh") return bsym + gsym + (t.zh ? zh : en);
    return bsym + gsym + `${en}${t.zh ? `<span style="opacity:.8;font-size:10px">${zh}</span>` : ""}`;
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
              } else if (parsed.nsfw !== true && parsed.nsfw !== false) {
                // 旧工作流 state.nsfw 缺失/null: 载入时就地物化成显式布尔,
                // 否则面板按全局默认显示、后端却按 false 过滤 (预览≠生成)。
                parsed.nsfw = !!getSetting(SET_DEFAULT_NSFW, false);
                sw.value = JSON.stringify(parsed);
                repaired.push("nsfw→显式布尔");
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
        // 只对"新建节点"应用默认模式: widgets_values 尚未被工作流填充时才生效。
        // ⚠ 新前端里新节点的 widgets_values 是 **undefined** 而非 null (旧 litegraph
        //   才是 null) —— 只判 === null 会让设置永远不生效; 工作流加载后它是数组。
        //   且 configure 晚于本 setTimeout, 已保存的 mode 值最后总会覆盖回正确值。
        // combo widget 的 options 在新前端是 {values:[...]} 对象 (旧 litegraph 才是数组),
        // 不能用 Object.values(options).includes() 判断 —— 那会拿到 [[...]] 永远不命中。
        const modeOpts = Array.isArray(modeW?.options) ? modeW.options
          : (modeW?.options?.values || []);
        const wvFresh = node.widgets_values === null || node.widgets_values === undefined;
        if (modeW && wvFresh && modeOpts.includes(defMode)) {
          modeW.value = defMode;
        }
        const defNsfw = getSetting(SET_DEFAULT_NSFW, false);
        if (node.widgets_values === null || node.widgets_values === undefined) {
          const sw = node.widgets?.find((w) => w.name === "selection_state");
          if (sw) {
            try {
              const st = JSON.parse(sw.value || "{}");
              // 新节点直接物化成显式布尔 (关也写 false): state 自带语义, 不留 null
              st.nsfw = !!defNsfw;
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
