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
  escapeHtml, toast, undoToast, SETTING_PREFIX, SET_DEFAULT_MODE, SET_DEFAULT_NSFW,
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
      <div class="tl-seg tl-mode-seg" title="工作模式: 手动=自己挑标签 / 自动=按排除类目随机组合">
        <button data-mode="manual">手动</button>
        <button data-mode="auto">自动</button>
      </div>
      <span class="tl-head-spacer"></span>
      <button class="tl-btn primary" data-act="addtags" title="从标签库挑选标签添加">＋ 添加</button>
      <button class="tl-btn icon tl-more-btn" data-act="more" title="更多: 场景 / 预设 / 内容过滤 / 显示 / 清空">⋯<i class="tl-more-dot"></i></button>
    </div>
    <div class="tl-toolbar">
      <input class="tl-search" placeholder="🔍 过滤已添加的标签…" />
    </div>
    <div class="tl-controls">
      <div class="tl-ctl"><span class="tl-ctl-k">NSFW</span>
        <button class="tl-sw tl-nsfw-btn" data-act="nsfw" role="switch" aria-checked="false"
                title="NSFW: 关=剔除并不显示 NSFW 标签; 开=显示且可输出"><i></i></button>
      </div>
      <div class="tl-ctl tl-ninten-wrap" hidden><span class="tl-ctl-k">涩度</span>
        <div class="tl-seg tl-ninten-seg" role="radiogroup" aria-label="涩词强度">
          <button data-ninten="0">标准</button><button data-ninten="1">强调</button><button data-ninten="2">纯欲</button>
        </div>
      </div>
      <div class="tl-ctl"><span class="tl-ctl-k">性别</span>
        <div class="tl-seg tl-gender-seg" role="radiogroup" aria-label="性别过滤">
          <button data-gender="off">双性</button><button data-gender="female">仅女</button><button data-gender="male">仅男</button>
        </div>
      </div>
      <div class="tl-ctl"><span class="tl-ctl-k">单人</span>
        <button class="tl-sw" data-scene="solo" role="switch" aria-checked="false"
                title="单人锁: 人数轴只出单词 (1girl/1boy/solo…), 禁多人词与互动槽"><i></i></button>
      </div>
      <div class="tl-ctl"><span class="tl-ctl-k">简背景</span>
        <button class="tl-sw" data-scene="bg" role="switch" aria-checked="false"
                title="简洁背景: 禁具象场景/天气/粒子槽, 背景处理只出简洁族 (纯色/渐变/虚化/棚拍)"><i></i></button>
      </div>
      <div class="tl-ctl"><span class="tl-ctl-k">特写</span>
        <button class="tl-sw" data-scene="focus" role="switch" aria-checked="false"
                title="人物特写: 禁杂物道具槽 (日用/食物/乐器/动物/束缚), 取景只出特写族"><i></i></button>
      </div>
      <div class="tl-ctl"><span class="tl-ctl-k">防冲突</span>
        <button class="tl-sw tl-conflict-btn" data-act="conflict" role="switch" aria-checked="true"
                title="防冲突: 随机时同组互斥 (关闭后可能抽出互相冲突的词)"><i></i></button>
      </div>
      <div class="tl-ctl"><span class="tl-ctl-k">排除类目</span>
        <button class="tl-excbtn" data-act="exclude" type="button" aria-label="排除类目设置">无</button>
      </div>
    </div>
    <div class="tl-mode-hint"></div>
    <!-- 预设 (1.11.0): 从 ⋯ 菜单搬到主区 —— 用户原话「只可用, 不可选, 也不可显」。
         选一行 = 召唤: 该预设记下的词全部进面板并**打钉**, 自动模式不再覆盖它们。 -->
    <div class="tl-preset-bar">
      <span class="tl-preset-k">📦 预设</span>
      <select class="tl-preset-sel" title="召唤预设: 出厂「场景预设」= 载入钉选词+排除域+配置 (约束不锁死, 🎲 继续在预设框内随机); 我的预设 = 把存下的词标签全部打钉, 自动模式不再覆盖它们">
        <option value="">选择一个预设…</option>
      </select>
      <button class="tl-btn icon" data-act="preset-save" title="把当前面板的词标签 + 排除域 + 配置存为预设 (召唤时会全部打钉)">💾</button>
      <button class="tl-btn icon" data-act="preset-del" title="删除选中的「我的」预设">🗑</button>
    </div>
    <div class="tl-chipzone"></div>
    <div class="tl-preview-row">
      <div class="tl-preview"></div>
      <button class="tl-roll-btn" data-act="roll" title="随机抽取标签填入框内 (按当前模式和设置)">🎲 填充</button>
    </div>
    <div class="tl-menu" hidden>
      <div class="tl-menu-sec">预设 / 导入</div>
      <div class="tl-preset-row">
        <button class="tl-btn icon" data-act="absorb" title="吸收器: 粘贴外部 prompt → 库内词直接进面板, 新词归位入库">📥</button>
        <span class="tl-preset-tip">预设选择框已移到面板主区 (图标 📦 那一行)</span>
      </div>
      <div class="tl-menu-sec">显示</div>
      <div class="tl-mi-row"><span class="tl-mi-k">显示语言</span>
        <select class="tl-sel tl-lang-sel" title="标签显示语言">
          <option value="bilingual">双语</option><option value="zh">中文</option><option value="en">英文</option>
        </select>
      </div>
      <div class="tl-mi-row"><span class="tl-mi-k">预览模式</span>
        <select class="tl-sel tl-pv-sel" title="节点面板底部的预览文本怎么显示">
          <option value="simple">简洁</option><option value="weighted">带权重</option><option value="debug">调试</option>
        </select>
      </div>
      <div class="tl-menu-sec">其他</div>
      <button class="tl-menu-item" data-act="manager"><span class="tl-mi-k">🏷 标签库管理</span><span class="tl-mi-v">分类/导入/备份/同步</span></button>
      <button class="tl-menu-item" data-act="preset-mgr"><span class="tl-mi-k">📦 预设管理</span><span class="tl-mi-v">详情/编辑</span></button>
      <button class="tl-menu-item" data-act="explorer"><span class="tl-mi-k">🎲 批量探索</span><span class="tl-mi-v">一次看 N 条</span></button>
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

  /* ---------- NSFW —— **开关** ----------
     ⚠ 用户明确要求: NSFW 是开关, 不是"可以 ✕ 掉的标签"。所以它就是开关的样子,
     拨一下就切换; 不挂 ✕、不做"点一下循环"。 */
  function renderNsfw() {
    const on = getNsfwEffective(node);
    nsfwBtn.classList.toggle("on", on);
    nsfwBtn.setAttribute("aria-checked", on ? "true" : "false");
    container.dataset.nsfw = on ? "1" : "0";
  }

  function toggleNsfw() {
    setState(node, { nsfw: !getNsfwEffective(node) });
    renderNsfw();
    renderAll();
  }
  nsfwBtn.addEventListener("click", toggleNsfw);

  /* ---------- 性别三态 —— **三分段** ----------
     原来做成"点一下循环"的胶囊: 用户看不出能不能点、也不知道点完会变成什么。
     现在是标准分段: 三个选项平铺, 当前项高亮, 点哪个就是哪个。 */
  function renderGender() {
    const g = getGender(node);
    container.querySelectorAll(".tl-gender-seg button").forEach((b) =>
      b.classList.toggle("active", b.dataset.gender === g));
    container.dataset.gender = g;
  }
  container.querySelector(".tl-gender-seg").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-gender]");
    if (!b) return;
    setState(node, { gender: b.dataset.gender });
    renderGender();
    renderAll();
    toast(GENDER_TITLE[b.dataset.gender]);
  });

  /* 防冲突开关 —— ⚠ 必须单独绑!
     它原来在 ⋯ 里是 .tl-menu-item[data-act="conflict"], 靠下面的 forEach 统一绑定;
     搬成面板上的开关后 .tl-menu-item 的 forEach 不再覆盖它 → 变成没人绑的死按钮
     (实测: 拨一下 true->true 毫无反应)。**凡是把控件移出 forEach 覆盖范围的, 都要补绑。** */
  container.querySelector(".tl-conflict-btn").addEventListener("click", () => toggleConflict());

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

  /* ---------- 档案束: 复合 chip (1.9.0 方案 C) ----------
     挑选器里点一个姿势 = 整束入面板 (如 holding sword + one handed gun hold)。
     旧界面把它们拆成各自独立的 chip —— 用户看不出"这几个词是一把刀的姿势",
     换姿势只能删了重挑。现在整束 = 一个对象: 一起进出 / 点一下换姿势 / ✕ 整束移除。 */
  let _profCache = null;
  let _bundleMenuEl = null;
  const bundleLabelOf = (t) => String((t && t._bundle) || "");

  async function loadProfiles() {
    if (_profCache) return _profCache;
    const d = await apiJson("/taglib/api/profiles");
    _profCache = (d && d.data && d.data.profiles) || [];
    return _profCache;
  }

  function bundleGroups(tags) {
    const m = new Map();
    (tags || []).forEach((t, i) => {
      const k = bundleLabelOf(t);
      if (!k) return;
      if (!m.has(k)) m.set(k, { label: k, idxs: [], items: [] });
      const b = m.get(k);
      b.idxs.push(i);
      b.items.push(t);
    });
    return m;
  }

  const archOfBundle = (label) => {
    const head = String(label).split(" · ")[0];
    return (_profCache || []).find((p) => String(p.zh || "") === head || String(p.id) === head) || null;
  };

  function setBundleTags(label, replacer) {
    const tags = getState(node).tags.slice();
    setState(node, { tags: replacer(tags) });
    renderTags();
  }

  const removeBundle = (b) => setBundleTags(b.label,
    (tags) => tags.filter((t) => bundleLabelOf(t) !== b.label));

  function moveBundle(label, before) {
    const tags = getState(node).tags.slice();
    const moving = tags.filter((t) => bundleLabelOf(t) === label);
    if (!moving.length) return;
    const anchor = tags[before];
    const rest = tags.filter((t) => bundleLabelOf(t) !== label);
    let at = anchor ? rest.indexOf(anchor) : rest.length;
    if (at < 0) at = rest.length;
    rest.splice(at, 0, ...moving);
    setState(node, { tags: rest });
    renderTags();
  }

  /* 换姿势: 整束成员原地替换成新姿势的出词, 已调过的权重/中文名跟着走 */
  function applyBundlePose(b, arch, pose) {
    const label = `${arch.zh || arch.id} · ${pose.zh || pose.id}`;
    setBundleTags(b.label, (tags) => {
      const at = tags.findIndex((t) => bundleLabelOf(t) === b.label);
      if (at < 0) return tags;
      const fresh = (pose.tags || []).map((en) => {
        const old = b.items.find((x) => String(x.en).toLowerCase() === String(en).toLowerCase());
        const nt = { en, zh: (old && old.zh) || "", enabled: old ? old.enabled !== false : true, _bundle: label };
        if (old && old.weight) nt.weight = old.weight;
        if (old && old.nsfw) nt.nsfw = true;
        return nt;
      });
      tags.splice(at, b.idxs.length, ...fresh);
      return tags;
    });
  }

  function closeBundleMenu() { if (_bundleMenuEl) _bundleMenuEl.style.display = "none"; }

  function showBundleMenu(anchor, b, items) {
    if (!_bundleMenuEl) {
      _bundleMenuEl = document.createElement("div");
      _bundleMenuEl.className = "tl-bundle-menu tl-scope";
      _bundleMenuEl.style.display = "none";
      document.body.appendChild(_bundleMenuEl);
    }
    const el = _bundleMenuEl;
    const { pid, isLight } = currentTheme();
    el.dataset.theme = pid;
    el.classList.toggle("tl-light", isLight);
    el.innerHTML = `<div class="bm-h">⚔ ${escapeHtml(b.label)} · ${b.items.length} 个词</div>`;
    for (const it of items) {
      if (it.sep) {
        const d = document.createElement("div");
        d.className = "bm-sep";
        el.appendChild(d);
        continue;
      }
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = (it.checked ? "checked " : "") + (it.danger ? "danger" : "");
      btn.textContent = (it.checked ? "✓ " : "") + it.label;
      if (it.disabled) { btn.disabled = true; btn.style.opacity = ".5"; }
      else btn.onclick = (ev) => { ev.stopPropagation(); closeBundleMenu(); it.onClick(); };
      el.appendChild(btn);
    }
    el.style.display = "flex";
    const r = el.getBoundingClientRect();
    const a = anchor.getBoundingClientRect();
    el.style.left = Math.min(a.left, innerWidth - r.width - 8) + "px";
    el.style.top = Math.min(a.bottom + 4, innerHeight - r.height - 8) + "px";
    const off = (ev) => { if (!el.contains(ev.target)) closeBundleMenu(); };
    setTimeout(() => document.addEventListener("click", off, { once: true }), 0);
  }

  async function openBundleMenu(anchor, b) {
    await loadProfiles();
    const arch = archOfBundle(b.label);
    const cur = String(b.label).split(" · ").slice(1).join(" · ");
    const items = [];
    if (arch) {
      for (const [kind, arr] of [["pose", arch.poses || []], ["extra", arch.extras || []]]) {
        for (const p of arr) {
          const nm = String(p.zh || p.id);
          items.push({ label: nm + (kind === "extra" ? " · 配件" : ""), checked: nm === cur,
                       onClick: () => applyBundlePose(b, arch, p) });
        }
      }
    } else {
      items.push({ label: "找不到对应档案 (可能已被删改)", disabled: true });
    }
    items.push({ sep: true });
    const on = b.items.every((x) => x.enabled !== false);
    items.push({ label: on ? "⏸ 整束停用" : "▶ 整束启用",
                 onClick: () => setBundleTags(b.label, (tags) => tags.map((t) =>
                   bundleLabelOf(t) === b.label ? { ...t, enabled: !on } : t)) });
    items.push({ label: "✕ 移除整束", danger: true, onClick: () => removeBundle(b) });
    showBundleMenu(anchor, b, items);
  }

  function bundleChip(b, idx) {
    const on = b.items.every((x) => x.enabled !== false);
    const el = document.createElement("span");
    el.className = "tl-ttag tl-bundle" + (on ? " on" : "");
    el.dataset.bundle = b.label;
    el.draggable = true;
    el.title = `⚔ ${b.label}\n出词: ${b.items.map((x) => x.en).join(", ")}\n`
      + `点击 = 换姿势 · 右键 = 更多 · ✕ = 整束移除`;
    el.innerHTML = `<b>⚔ ${escapeHtml(b.label)}</b><span class="tl-bw">${b.items.length}</span>`
      + `<span class="tl-x" title="移除整束">✕</span>`;
    el.onclick = () => openBundleMenu(el, b);
    el.oncontextmenu = (e) => { e.preventDefault(); e.stopPropagation(); openBundleMenu(el, b); };
    el.querySelector(".tl-x").onclick = (e) => { e.stopPropagation(); removeBundle(b); };
    el.ondragstart = (e) => { e.dataTransfer.setData("text/plain", "b:" + b.label); el.classList.add("dragging"); };
    el.ondragend = () => {
      el.classList.remove("dragging");
      chipzoneEl.querySelectorAll(".drop-target").forEach((x) => x.classList.remove("drop-target"));
    };
    el.ondragover = (e) => { e.preventDefault(); el.classList.add("drop-target"); };
    el.ondragleave = () => el.classList.remove("drop-target");
    el.ondrop = (e) => { e.preventDefault(); dropOnChip(e.dataTransfer.getData("text/plain"), idx); };
    return el;
  }

  function dropOnChip(raw, idx) {
    if (String(raw).startsWith("b:")) { moveBundle(String(raw).slice(2), idx); return; }
    const from = parseInt(raw);
    if (Number.isNaN(from) || from === idx) return;
    const cur = getState(node).tags.slice();
    const [moved] = cur.splice(from, 1);
    cur.splice(idx, 0, moved);
    setState(node, { tags: cur });
    renderTags();
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

    const bundles = bundleGroups(st.tags);   // 档案束: 整束画成一个复合 chip
    const bundleDrawn = new Set();

    let shown = 0;
    let lastGroup = null;
    st.tags.forEach((t, idx) => {
      if (q && !(
        t.en.toLowerCase().includes(q) ||
        (t.zh || "").toLowerCase().includes(q))) return;
      shown++;
      // 束成员只画一次 (画在第一个可见成员的位置) —— 复合 chip 代表整束
      const bk = bundleLabelOf(t);
      if (bk) {
        if (bundleDrawn.has(bk)) return;
        bundleDrawn.add(bk);
        chipzoneEl.appendChild(bundleChip(bundles.get(bk), idx));
        return;
      }
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
          // 1.8.0 分轴重摇: 只换这一轴的词, 其余轴全部保留
          const rr = document.createElement("span");
          rr.className = "tl-axreroll";
          rr.textContent = " 🎲";
          rr.style.cssText = "cursor:pointer;opacity:.7;font-size:10px;";
          rr.title = `只重摇「${grp}」轴 (其余词全部保留)`;
          rr.onclick = (e) => { e.stopPropagation(); rerollAxis(grp); };
          head.appendChild(rr);
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
      // NSFW 开关为「关」时 nsfw chip 会在出口被剔除 —— 必须显式标出。
      // 这是手动路径上仅剩的"静默丢失": 用户看不出为什么少了一个词。
      const ndrop = !!t.nsfw && !getNsfwEffective(node);
      el.className = "tl-ttag" + (t.enabled === false ? "" : " on") + (t.nsfw ? " nsfw" : "")
        + (tg ? " gender" : "") + (dropped ? " tl-dropped" : "") + (gdrop ? " tl-gdrop" : "")
        + (ndrop ? " tl-ndrop" : "");
      el.draggable = true;
      el.title = (t.enabled === false
        ? "已停用 — 点击启用"
        : (t.pinned ? "📌 已钉选 (随机/填充不覆盖) · 拖动排序 / ✕移除"
                    : "已启用 · 拖动排序 / 右键📌钉选 / ✕移除"))
        + (gdrop ? `\n⚧ 性别过滤中: 此${tg === "male" ? "男性" : "女性"}专属标签不会参与输出/随机/填充` : "")
        + (ndrop ? "\n🔞 NSFW 开关为「关」: 此标签不会输出 (打开 NSFW 后才出)" : "");
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
      el.ondrop = (e) => { e.preventDefault(); dropOnChip(e.dataTransfer.getData("text/plain"), idx); };
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

  /* opts.quiet = true 时抑制"成功"提示 (用于场景开关切换后的自动重抽,
     避免每拨一下都弹一条); 失败提示与撤销按钮不受它影响。 */
  async function rollFill(opts) {
    const quiet = !!(opts && opts.quiet);
    const st = getState(node);
    const nsfwOn = getNsfwEffective(node);
    const excluded = new Set(st.exclude_categories || []);
    const keepPins = true;  // 钉选必含常开 (设置开关已移除): 📌 标签填充时必保留且占子类目名额
    // 撤销快照: 填充会清掉非钉选/非排除类目的词 (不可逆), 必须留退路
    const prevTags = st.tags.map((t) => ({ ...t }));
    const prevFillGroups = ui.fillGroups;
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
    } catch (e) {
      console.warn("[taglib] draw 失败", e);
      toast("抽取失败: 请求没送到, 请重试", true);
      return;
    }
    if (!drawRes?.ok) {
      console.warn("[taglib] draw 返回异常", drawRes);
      toast(`抽取失败: ${(drawRes && drawRes.error) || "服务端返回异常"}`, true);
      return;
    }
    // 服务端本来就告诉我们有多少候选被互斥/资源账本挡下了 —— 以前这里全扔了,
    // 于是"点了没反应"和"被规则过滤了"在用户眼里长得一模一样。
    const dropped = Array.isArray(drawRes.dropped) ? drawRes.dropped : [];
    const droppedMutex = (drawRes.stats && drawRes.stats.dropped_mutex) || 0;
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
    const pinnedKeptCount = keptTags.filter((t) => t.pinned).length;
    if (!picked.length && !pinnedKeptCount) {
      // 以前这里是裸 return —— "点了没反应"与"被规则挡住了"在用户眼里完全一样
      const why = droppedMutex
        ? `候选与已选互斥 (挡下 ${droppedMutex} 个)`
        : (excluded.size ? `已排除 ${excluded.size} 个类目` : "当前设置下没有可抽的词");
      toast(`本次没抽到词 —— ${why}`, true);
      return;
    }
    // ③ 写回: 全部按库类目顺序排列 (钉选不顶置, 随类目走); 分组标题含钉选保留词
    const pinnedKept = keepPins ? keptTags.filter((t) => t.pinned && t._cat) : [];
    ui.fillGroups = groupByCat([...pinnedKept, ...picked]);
    setState(node, {
      tags: sortByCat([...keptTags, ...picked])
        .map((t) => ({ ...t, _auto: true, enabled: t.enabled !== false })),
    });
    renderTags();
    previewEl.textContent = outputPreview(getState(node).tags, ui.previewMode);
    // ④ 反馈 + 撤销。说清"填了几个 / 换掉几个 / 跳过几个"。
    //    只有真的替换掉过词才弹撤销 —— 否则没什么可撤, 弹出来只是噪声。
    const replaced = prevTags.length - keptTags.length;
    const bits = [`已填入 ${picked.length} 个词`];
    if (replaced > 0) bits.push(`替换掉 ${replaced} 个`);
    if (pinnedKeptCount) bits.push(`保留 ${pinnedKeptCount} 个📌`);
    if (dropped.length || droppedMutex) bits.push(`跳过 ${dropped.length || droppedMutex} 个互斥词`);
    const msg = bits.join(" · ");
    if (replaced > 0) {
      undoToast(msg, () => {
        setState(node, { tags: prevTags });
        ui.fillGroups = prevFillGroups;
        renderTags();
        previewEl.textContent = outputPreview(getState(node).tags, ui.previewMode);
        toast("已撤销, 标签回到填充前的状态");
      });
    } else if (!quiet) {
      toast(msg);
    }
  }

  /* ---------- 1.8.0 场景预设 / 分轴重摇 / 吸收器 ---------- */

  async function apiJson(url, opts) {
    try { return await fetch(url, opts).then((r) => r.json()); }
    catch (e) { console.warn("[taglib] api 失败:", url, e); return null; }
  }

  let _presetsCache = { factory: [], user: [] };
  async function loadPresets() {
    const d = await apiJson("/taglib/api/presets");
    if (!d?.ok) return;
    _presetsCache = { factory: d.factory || [], user: d.user || [] };
    const sel = container.querySelector(".tl-preset-sel");
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="">选择一个预设…</option>';
    const opt = (p, val) => {
      const o = document.createElement("option");
      o.value = val;
      const n = (p.tags || []).length;
      o.textContent = `${p.name}${p.kind ? ` · ${p.kind}` : ""}${n ? ` · ${n} 词` : ""}`;
      o.title = p.note || "";
      sel.appendChild(o);
    };
    if (_presetsCache.factory.length) {
      const g = document.createElement("optgroup");
      g.label = "出厂";
      _presetsCache.factory.forEach((p) => opt(p, "f." + p.id));
      sel.appendChild(g);
    }
    if (_presetsCache.user.length) {
      const g = document.createElement("optgroup");
      g.label = "我的";
      _presetsCache.user.forEach((p) => opt(p, "u." + p.id));
      sel.appendChild(g);
    }
    sel.value = cur || "";
    if (sel.value !== cur) sel.value = "";
  }

  function findPreset(val) {
    if (!val) return null;
    const [src, ...rest] = val.split(".");
    const id = rest.join(".");
    const pool = src === "f" ? _presetsCache.factory : _presetsCache.user;
    return pool.find((p) => String(p.id) === id) || null;
  }

  async function applyPreset(p) {
    const st = getState(node);
    // 出厂「场景预设」只有 pinned → 约束不锁死 (只钉必要词, 🎲 仍在框内随机)。
    // 我的预设带 tags (当前面板的词标签快照) → 召唤时**全部打钉**, 自动模式不再覆盖它们。
    const snap = (p.tags || []).map((x) => (typeof x === "string" ? { en: x } : x));
    const wantPins = new Set([...(p.pinned || []), ...snap.map((x) => x.en)]
      .map((x) => String(x).toLowerCase()));
    const tags = st.tags.map((t) =>
      wantPins.has(String(t.en).toLowerCase()) ? { ...t, pinned: true } : t);
    const have = new Set(tags.map((t) => String(t.en).toLowerCase()));
    for (const w of snap) {                     // 快照里的词不在面板就补进来
      const lo = String(w.en || "").toLowerCase();
      if (!lo || have.has(lo)) continue;
      tags.push({ en: w.en, zh: w.zh || "", pinned: true, enabled: true,
                  ...(w.cat ? { _cat: w.cat } : {}) });
      have.add(lo);
    }
    for (const en of p.pinned || []) {           // 出厂预设的钉选词同理
      const lo = String(en).toLowerCase();
      if (have.has(lo)) continue;
      const t = { en, zh: "", pinned: true, enabled: true };
      const path = LIB_PATH.get(lo);
      if (path) t._cat = path[0];
      tags.push(t);
      have.add(lo);
    }
    const upd = {
      tags: sortByCat(tags).map((t) => ({ ...t, enabled: t.enabled !== false })),
      exclude_categories: (p.exclude || []).slice(),
    };
    const cfg = p.config || {};
    for (const k of ["total_min", "total_max", "bundle_pose_prob", "extra_prob", "max_weapons", "nsfw_intensity", "solo_lock", "bg_mode", "focus_mode", "max_props_total"]) {
      upd[k] = cfg[k] !== undefined ? cfg[k] : null;   // null = 还原引擎默认
    }
    setState(node, upd);
    ui.fillGroups = null;
    renderAll();
    previewEl.textContent = outputPreview(getState(node).tags, ui.previewMode);
  }

  function savePresetDialog(onDone) {
    const old = document.getElementById("taglib-preset-save-dialog");
    if (old) old.remove();
    const dlg = document.createElement("dialog");
    dlg.id = "taglib-preset-save-dialog";
    dlg.classList.add("p-inputtext");
    dlg.setAttribute("translate", "no");
    dlg.style.cssText = "background:#15171d;color:#e3e7ee;border:1px solid #333845;"
      + "border-radius:12px;padding:14px;width:min(380px,92vw);";
    dlg.innerHTML = `
      <div style="font-weight:600;margin-bottom:8px;">💾 把当前面板存为预设</div>
      <div style="display:grid;gap:8px;font-size:12px;">
        <label>名称 <input id="tl-ps-name" style="width:100%;box-sizing:border-box;background:#1c1f26;color:inherit;border:1px solid #333845;border-radius:6px;padding:5px 8px;" placeholder="例如 浴室·纯欲" /></label>
        <label>类型 <select id="tl-ps-kind" style="width:100%;background:#1c1f26;color:inherit;border:1px solid #333845;border-radius:6px;padding:5px 8px;">
          <option>场景</option><option>角色</option><option>局面</option><option>背景</option></select></label>
        <label>备注 (可选) <input id="tl-ps-note" style="width:100%;box-sizing:border-box;background:#1c1f26;color:inherit;border:1px solid #333845;border-radius:6px;padding:5px 8px;" /></label>
        <div id="tl-ps-err" style="color:#e77;font-size:11px;"></div>
      </div>
      <div style="display:flex;gap:8px;margin-top:10px;">
        <button id="tl-ps-ok" class="tl-btn primary" style="padding:4px 14px;">保存</button>
        <span style="flex:1"></span>
        <button id="tl-ps-cancel" class="tl-btn" style="padding:4px 10px;">取消</button>
      </div>`;
    document.body.appendChild(dlg);
    dlg.querySelector("#tl-ps-cancel").onclick = () => dlg.close();
    dlg.querySelector("#tl-ps-ok").onclick = () => {
      const name = dlg.querySelector("#tl-ps-name").value.trim();
      if (!name) { dlg.querySelector("#tl-ps-err").textContent = "请填名称"; return; }
      dlg.close();
      onDone(name, dlg.querySelector("#tl-ps-kind").value, dlg.querySelector("#tl-ps-note").value.trim());
    };
    dlg.showModal();
    dlg.querySelector("#tl-ps-name").focus();
  }

  async function savePreset() {
    savePresetDialog(async (name, kind, note) => {
      const st = getState(node);
      // ★ 1.11.0: 预设 = 当前面板**全部词标签**的快照 (原来只存"已钉选"那几个 ——
      //   用户报"记不住当前节点词标签")。召唤时这些词全部打钉, 自动模式不再覆盖。
      const snap = st.tags.map((t) => {
        const path = LIB_PATH.get(String(t.en).toLowerCase()) || [];
        return { en: t.en, ...(t.zh ? { zh: t.zh } : {}), ...(path[0] ? { cat: path[0] } : {}) };
      });
      const preset = {
        id: "u" + Date.now().toString(36),
        name, kind: kind || "场景",
        tags: snap,
        pinned: st.tags.filter((t) => t.pinned).map((t) => t.en),
        exclude: (st.exclude_categories || []).slice(),
        config: {},
        note: note || "",
      };
      for (const k of ["total_min", "total_max", "bundle_pose_prob", "extra_prob", "max_weapons", "nsfw_intensity", "solo_lock", "bg_mode", "focus_mode", "max_props_total"]) {
        if (st[k] !== undefined && st[k] !== null) preset.config[k] = st[k];
      }
      if (!preset.tags.length && !preset.exclude.length && !Object.keys(preset.config).length) {
        alert("面板还是空的 (没有词标签 / 排除域 / 自定义配置), 没什么可存的");
        return;
      }
      const r = await apiJson("/taglib/api/settings");
      const list = (r?.settings?.presets || []).slice();
      list.push(preset);
      await apiJson("/taglib/api/settings", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: { presets: list } }),
      });
      await loadPresets();
      const sel = container.querySelector(".tl-preset-sel");
      if (sel) sel.value = "u." + preset.id;
    });
  }

  async function deletePreset() {
    const sel = container.querySelector(".tl-preset-sel");
    const val = sel?.value || "";
    if (!val.startsWith("u.")) { alert("请先在下拉里选中一个「我的」预设"); return; }
    const id = val.slice(2);
    const r = await apiJson("/taglib/api/settings");
    const list = (r?.settings?.presets || []).filter((p) => String(p.id) !== id);
    await apiJson("/taglib/api/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings: { presets: list } }),
    });
    await loadPresets();
  }

  // ---- 分轴重摇: 保留词转钉选 + 其余轴排除 → 只有该轴重新出生 ----
  async function rerollAxis(grp) {
    const st = getState(node);
    const nsfwOn = getNsfwEffective(node);
    const keepTags = st.tags.filter((t) => tagCatOf(t) !== grp);
    const keepWords = keepTags.map((t) => t.en);
    const res = await apiJson("/taglib/api/draw_reroll", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        state: { ...st, nsfw: nsfwOn },
        seed: Math.floor(Math.random() * 0xffffffff),
        axes: [grp], keep_words: keepWords,
      }),
    });
    if (!res?.ok) { console.warn("[taglib] reroll 失败", res); return; }
    const have = new Set(keepTags.map((t) => String(t.en).toLowerCase()));
    const picked = [];
    for (const pk of res.picks) {
      const lo = String(pk.en).toLowerCase();
      if (have.has(lo)) continue;
      have.add(lo);
      const item = { en: pk.en, zh: pk.zh || "", _cat: pk.cat || "", _auto: true, enabled: true };
      picked.push(item);
    }
    ui.fillGroups = groupByCat([...keepTags, ...picked]);
    setState(node, { tags: sortByCat([...keepTags, ...picked]) });
    renderTags();
    previewEl.textContent = outputPreview(getState(node).tags, ui.previewMode);
  }

  // ---- 吸收器: 粘贴 prompt → 库内词进面板, 库外词归位入库 ----
  let _absorbSlots = null;   // [{cat, sub}] 骨架槽位表 (打开时懒加载)
  async function openAbsorb() {
    if (!_absorbSlots) {
      const sk = await apiJson("/taglib/api/library?mode=skeleton");
      if (sk?.categories) {
        _absorbSlots = [];
        for (const c of sk.categories)
          for (const s of c.subcategories || [])
            _absorbSlots.push({ cat: c.name, sub: s.name });
      }
    }
    const old = document.getElementById("taglib-absorb-dialog");
    if (old) old.remove();
    const dlg = document.createElement("dialog");
    dlg.id = "taglib-absorb-dialog";
    dlg.classList.add("p-inputtext");
    dlg.setAttribute("translate", "no");
    dlg.style.cssText = "background:#15171d;color:#e3e7ee;border:1px solid #333845;"
      + "border-radius:12px;padding:14px;width:min(560px,92vw);max-height:80vh;overflow:auto;";
    dlg.innerHTML = `
      <div style="font-weight:600;margin-bottom:8px;">📥 吸收外部 Prompt</div>
      <textarea id="tl-absorb-text" rows="4" placeholder="粘贴任意来源的提示词 (逗号/换行分隔, 支持 (tag:1.2) 权重与下划线命名)…"
        style="width:100%;box-sizing:border-box;background:#1c1f26;color:inherit;border:1px solid #333845;border-radius:8px;padding:8px;font-size:12px;"></textarea>
      <div style="display:flex;gap:8px;margin:8px 0;align-items:center;">
        <button id="tl-absorb-parse" class="tl-btn primary" style="padding:4px 12px;">解析</button>
        <label style="font-size:11px;display:flex;gap:4px;align-items:center;">
          <input type="checkbox" id="tl-absorb-nsfw" /> 新词标为 NSFW</label>
        <span style="flex:1"></span>
        <button id="tl-absorb-close" class="tl-btn" style="padding:4px 10px;">关闭</button>
      </div>
      <div id="tl-absorb-result" style="font-size:12px;"></div>
    `;
    document.body.appendChild(dlg);
    const resBox = dlg.querySelector("#tl-absorb-result");
    let lastMatched = [], lastUnmatched = [];

    dlg.querySelector("#tl-absorb-close").onclick = () => dlg.close();
    dlg.querySelector("#tl-absorb-parse").onclick = async () => {
      const d = await apiJson("/taglib/api/absorb", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: dlg.querySelector("#tl-absorb-text").value }),
      });
      if (!d?.ok) { resBox.textContent = "解析失败"; return; }
      lastMatched = d.matched || [];
      lastUnmatched = d.unmatched || [];
      renderAbsorbResult(dlg, resBox, lastMatched, lastUnmatched, _absorbSlots || []);
      // 绑定"添加选中到面板"
      dlg.querySelector("#tl-absorb-addsel").onclick = () => {
        const st = getState(node);
        const have = new Set(st.tags.map((t) => String(t.en).toLowerCase()));
        const add = [];
        resBox.querySelectorAll('[data-mi]:checked').forEach((cb) => {
          const m = lastMatched[parseInt(cb.dataset.mi)];
          if (m && !have.has(String(m.en).toLowerCase())) {
            const t = { en: m.en, zh: m.zh || "", enabled: true };
            const path = LIB_PATH.get(String(m.en).toLowerCase());
            if (path) t._cat = path[0];
            add.push(t);
          }
        });
        if (add.length) {
          setState(node, { tags: sortByCat([...st.tags, ...add]) });
          renderTags();
          previewEl.textContent = outputPreview(getState(node).tags, ui.previewMode);
        }
        dlg.querySelector("#tl-absorb-addsel").disabled = true;
      };
      // 绑定"新词入库"
      dlg.querySelector("#tl-absorb-addlib").onclick = async () => {
        const nsfw = dlg.querySelector("#tl-absorb-nsfw").checked;
        const tags = [];
        resBox.querySelectorAll('[data-ui]:checked').forEach((cb) => {
          const u = lastUnmatched[parseInt(cb.dataset.ui)];
          if (!u) return;
          const sel = resBox.querySelector(`select[data-slot="${cb.dataset.ui}"]`);
          if (!sel?.value) return;
          const [cat, sub] = sel.value.split("||");
          tags.push({ en: u.raw.replace(/_/g, " ").trim(), zh: "", cat, sub, nsfw });
        });
        if (!tags.length) return;
        const d2 = await apiJson("/taglib/api/absorb_add", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tags }),
        });
        if (d2?.ok) {
          resBox.querySelectorAll('[data-ui]').forEach((cb) => { cb.disabled = true; });
          resBox.querySelector("#tl-absorb-addlib").disabled = true;
          const note = document.createElement("div");
          note.style.cssText = "color:#7fd18a;margin-top:6px;";
          note.textContent = `已入库 ${d2.added.length} 词` +
            (d2.skipped.length ? `, 跳过 ${d2.skipped.length} (已存在/槽位无效)` : "");
          resBox.appendChild(note);
        }
      };
    };
    dlg.showModal();
  }

  function renderAbsorbResult(dlg, resBox, matched, unmatched, slots) {
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const slotOpts = (slots || [])
      .map((s) => `<option value="${esc(s.cat)}||${esc(s.sub)}">${esc(s.cat)} / ${esc(s.sub)}</option>`)
      .join("");
    let html = "";
    if (matched.length) {
      html += `<div style="margin:6px 0 4px;opacity:.8;">库内命中 ${matched.length} 词:</div>`;
      matched.forEach((m, i) => {
        html += `<label style="display:flex;gap:6px;align-items:center;padding:2px 0;">
          <input type="checkbox" data-mi="${i}" checked />
          <span>${esc(m.en)}</span><span style="opacity:.6;font-size:11px;">${esc(m.zh || "")}</span>
          <span style="opacity:.5;font-size:11px;margin-left:auto;">${esc(m.cat)}</span></label>`;
      });
      html += `<button id="tl-absorb-addsel" class="tl-btn primary" style="padding:3px 10px;margin-top:6px;">添加选中到面板</button>`;
    }
    if (unmatched.length) {
      html += `<div style="margin:8px 0 4px;opacity:.8;">库外新词 ${unmatched.length} 个 (勾选并选槽位归位):</div>`;
      unmatched.forEach((u, i) => {
        html += `<div style="display:flex;gap:6px;align-items:center;padding:2px 0;">
          <input type="checkbox" data-ui="${i}" checked />
          <span style="min-width:90px;">${esc(u.raw)}</span>
          <select data-slot="${i}" style="flex:1;background:#1c1f26;color:inherit;border:1px solid #333845;border-radius:6px;font-size:11px;">
            <option value="">选择槽位…</option>${slotOpts}</select></div>`;
      });
      html += `<button id="tl-absorb-addlib" class="tl-btn primary" style="padding:3px 10px;margin-top:6px;">新词入库</button>`;
    }
    if (!matched.length && !unmatched.length) html = `<div style="opacity:.6;">没有解析出任何词条</div>`;
    resBox.innerHTML = html;
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
    const bsym = t._bundle ? `<span class="tl-bsym" title="档案姿势/配件成员${t._bundle ? " (" + String(t._bundle).replace(/"/g, "") + ")" : ""}">⚔</span>` : "";
    // 手调过权重就标出来 —— 否则"设了权重没看到变化"又是一次静默
    const w = Number(t.weight);
    const wsym = (w && Math.abs(w - 1) > 1e-6)
      ? `<span class="tl-wsym" title="权重 ${w} (输出成 (词:${w})，需开启权重语法)">×${w}</span>` : "";
    // 库内文本统一转义 —— 词来自可导入的 .md/JSON, 不能直接进 innerHTML
    const en = escapeHtml(t.en);
    const zh = t.zh ? escapeHtml(t.zh) : "";
    if (lang === "en") return bsym + gsym + en + wsym;
    if (lang === "zh") return bsym + gsym + (t.zh ? zh : en) + wsym;
    return bsym + gsym + `${en}${t.zh ? `<span style="opacity:.8;font-size:10px">${zh}</span>` : ""}` + wsym;
  }

  function renderConflictBtn() {
    const on = getState(node).avoid_conflicts !== false;
    const sw = container.querySelector(".tl-conflict-btn");
    if (sw) {
      sw.classList.toggle("on", on);
      sw.setAttribute("aria-checked", on ? "true" : "false");
    }
  }

  /* NSFW 强度三档 (1.8.0): 标准=原池占比 / 强调=×2.5 / 纯欲=×6.0 (涩词抽样权重乘数) */
  const NINTEN_SEQ = [0, 1, 2];
  const NINTEN_LABEL = { 0: "标准", 1: "强调", 2: "纯欲" };
  function cycleNsfwIntensity() {
    const st = getState(node);
    const cur = Number(st.nsfw_intensity || 0);
    const next = NINTEN_SEQ[(NINTEN_SEQ.indexOf(cur) + 1) % NINTEN_SEQ.length];
    setState(node, { nsfw_intensity: next === 0 ? null : next });
    renderNsfwIntensity();
    rollFill();   // 立刻按新强度重抽, 按钮点了就见效
  }
  /* ---------- 涩度三档 —— **三分段**, 只在 NSFW 打开时出现 ---------- */
  function renderNsfwIntensity() {
    const on = getNsfwEffective(node);
    const wrap = container.querySelector(".tl-ninten-wrap");
    if (wrap) wrap.hidden = !on;
    const cur = Number(getState(node).nsfw_intensity || 0);
    container.querySelectorAll(".tl-ninten-seg button").forEach((b) =>
      b.classList.toggle("active", Number(b.dataset.ninten) === cur));
  }
  container.querySelector(".tl-ninten-seg").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-ninten]");
    if (!b) return;
    setState(node, { nsfw_intensity: Number(b.dataset.ninten) });
    renderNsfwIntensity();
    renderAll();
    rollFill();                       // 立刻按新强度重抽, 点了就见效
    toast("涩度: " + (NINTEN_LABEL[Number(b.dataset.ninten)] || ""));
  });

  /* ---------- 显示语言 / 预览模式 —— **下拉** ----------
     选择语义就该用下拉: 打开就看到全部选项、点一个就选定。
     原来是"点一下循环到下一档", 用户得点好几次才知道有哪些档。 */
  const langSel = container.querySelector(".tl-lang-sel");
  langSel.onchange = () => {
    setSetting(SET_LANG, langSel.value);
    renderAll();                      // chip 文案随语言变, 要整块重渲染
    toast("显示语言: " + (LANG_LABEL[langSel.value] || langSel.value));
  };
  const pvSel = container.querySelector(".tl-pv-sel");
  pvSel.onchange = () => {
    setState(node, { preview_mode: pvSel.value });
    ui.previewMode = pvSel.value;
    previewEl.textContent = outputPreview(getState(node).tags, pvSel.value);
    renderMenuState();
    toast("预览模式: " + (PV_LABEL[pvSel.value] || pvSel.value));
  };

  function toggleConflict() {
    const cur = getState(node).avoid_conflicts !== false;
    setState(node, { avoid_conflicts: !cur });
    renderConflictBtn(); renderMenuState();
  }

  /* 场景三档 (单人锁 / 简背景 / 特写) —— 与 NSFW、防冲突同为"开关"语义。
     ⚠ 必须同时更新 aria-checked: 曾经这里只 toggle 视觉类名, 读屏软件永远
     回报"关", 而屏幕上是开 —— 状态自相矛盾。 */
  function renderSceneBar() {
    const st = getState(node);
    const setSw = (el, on) => {
      if (!el) return;
      el.classList.toggle("on", on);
      el.setAttribute("aria-checked", on ? "true" : "false");
    };
    setSw(container.querySelector('[data-scene="solo"]'), !!st.solo_lock);
    setSw(container.querySelector('[data-scene="bg"]'), st.bg_mode === "simple");
    setSw(container.querySelector('[data-scene="focus"]'), st.focus_mode === "portrait");
  }

  /* 排除类目读数 + 入口 —— 这是审查里挂了很久的 P0:
     默认就排除了「画师」轴, 而面板上此前**没有任何地方显示或可改**,
     用户会判定"画师词抽不出来 = 库坏了"。 */
  function renderExcludeBtn() {
    const btn = container.querySelector('[data-act="exclude"]');
    if (!btn) return;
    const list = getState(node).exclude_categories || [];
    btn.textContent = list.length ? `${list.length} 项` : "无";
    btn.classList.toggle("on", list.length > 0);
    btn.title = list.length
      ? `已排除 ${list.length} 项 (抽取时整条跳过):\n${list.join("\n")}\n\n点这里修改`
      : "未排除任何类目。\n点这里打开排除设置\n(注意: 抽取时手动挑的词不受排除约束)";
  }

  /* ---------- 模式说明 (1.9.0) ----------
     「手动模式下总词数 40~60 还生效吗?」旧界面从不回答, 用户只能猜。
     实情: manual 走 chosen 列表原样输出 (不受配额约束), auto 才按配额随机组合。 */
  function renderModeHint() {
    const el = $(".tl-mode-hint");
    if (!el) return;
    el.innerHTML = ui.mode === "auto"
      ? `🎲 <b>自动</b>：queue 时按排除类目随机组合，受「总词数」配额与冲突规则约束；<b>下面挑的词不参与输出</b>。`
      : `✍ <b>手动</b>：只输出下面挑的词（按挑选顺序），<b>不受「总词数」配额约束</b>；🎲 填充才按配额抽。`;
  }

  function renderAll() {
    renderTags(); renderNsfw(); renderGender(); renderConflictBtn();
    renderModeHint();
    renderNsfwIntensity(); renderSceneBar(); renderMenuState(); renderExcludeBtn();
  }

  /* ---------- ⋯ 更多菜单 ----------
     低频操作集中于此 (性别 / 防冲突 / 显示语言 / 预览模式 / 清空),
     同时充当"当前状态"的读数板; ⋯ 上小圆点提示有非默认项。 */
  function renderMenuState() {
    // 语言/预览模式已改成**下拉**(选择语义就该用下拉, 不是点胶囊循环)
    const ls = container.querySelector(".tl-lang-sel");
    if (ls) ls.value = getSetting(SET_LANG, "bilingual");
    const ps = container.querySelector(".tl-pv-sel");
    if (ps) ps.value = getState(node).preview_mode || "simple";
    // 性别 / 防冲突 / NSFW 现在都直接摆在面板上, ⋯ 的圆点只提示"预设已选中"
    const presetSel = container.querySelector(".tl-preset-sel");
    moreBtn.classList.toggle("dirty", !!(presetSel && presetSel.value));
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
      else if (act === "ninten") cycleNsfwIntensity();
      else if (act === "lang") cycleLang();
      else if (act === "pv") cyclePvMode();
      else if (act === "explorer") openDrawExplorer();
      else if (act === "preset-mgr") openPresetMgr();
      // 管理页 (分类增删改 / 导入 / 备份 / 批量工具 / 标签文件同步) 的唯一入口就在
      // 这个菜单里: 原来右上角那个悬浮 🏷 按钮已删 (界面全部收进节点面板)。
      else if (act === "manager") openManagerDialog();
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

  // ---- 批量探索 (1.8.0): 一次生成 N 条完整 prompt, 点选即把节点 seed 对齐 ----
  async function openDrawExplorer() {
    const old = document.getElementById("taglib-explorer-dialog");
    if (old) old.remove();
    const dlg = document.createElement("dialog");
    dlg.id = "taglib-explorer-dialog";
    dlg.classList.add("p-inputtext");
    dlg.setAttribute("translate", "no");
    dlg.style.cssText = "background:#15171d;color:#e3e7ee;border:1px solid #333845;"
      + "border-radius:12px;padding:14px;width:min(720px,94vw);max-height:84vh;overflow:auto;";
    dlg.innerHTML = `
      <div style="font-weight:600;margin-bottom:8px;">🎲 批量探索 <span style="opacity:.6;font-size:11px;">(同一引擎同一确定性 — 点卡片把节点 seed 对齐, queue 即复现)</span></div>
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;font-size:12px;">
        <label>起始 seed <input id="tl-ex-seed" type="number" value="${Math.floor(Math.random() * 0xffffff)}" style="width:110px;background:#1c1f26;color:inherit;border:1px solid #333845;border-radius:6px;padding:2px 6px;" /></label>
        <label>条数 <select id="tl-ex-n" style="background:#1c1f26;color:inherit;border:1px solid #333845;border-radius:6px;padding:2px 4px;">
          <option>8</option><option selected>12</option><option>20</option><option>30</option></select></label>
        <button id="tl-ex-go" class="tl-btn primary" style="padding:4px 12px;">生成</button>
        <span style="flex:1"></span>
        <button id="tl-ex-close" class="tl-btn" style="padding:4px 10px;">关闭</button>
      </div>
      <div id="tl-ex-grid" style="display:grid;grid-template-columns:1fr;gap:6px;font-size:11px;"></div>
    `;
    document.body.appendChild(dlg);
    const grid = dlg.querySelector("#tl-ex-grid");
    dlg.querySelector("#tl-ex-close").onclick = () => dlg.close();
    dlg.querySelector("#tl-ex-go").onclick = async () => {
      grid.textContent = "生成中…";
      const d = await apiJson("/taglib/api/draw_batch", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          state: { ...getState(node), nsfw: getNsfwEffective(node) },
          seed_base: parseInt(dlg.querySelector("#tl-ex-seed").value) || 0,
          n: parseInt(dlg.querySelector("#tl-ex-n").value) || 12,
        }),
      });
      grid.innerHTML = "";
      if (!d?.ok) { grid.textContent = "生成失败"; return; }
      for (const it of d.items) {
        const card = document.createElement("div");
        card.style.cssText = "border:1px solid #2a2e39;border-radius:8px;padding:8px;cursor:pointer;";
        card.title = "点击: 把节点 seed 设为 " + it.seed + " (自动模式 queue 即出这条)";
        const head = document.createElement("div");
        head.style.cssText = "opacity:.6;margin-bottom:3px;display:flex;justify-content:space-between;";
        head.innerHTML = `<span>seed ${it.seed}</span><span class="tl-ex-copy" style="cursor:pointer;" title="复制 prompt">📋</span>`;
        const body = document.createElement("div");
        body.textContent = it.text;
        card.appendChild(head);
        card.appendChild(body);
        card.onclick = (e) => {
          if (e.target.classList.contains("tl-ex-copy")) {
            navigator.clipboard?.writeText(it.text);
            e.target.textContent = "✅";
            setTimeout(() => { e.target.textContent = "📋"; }, 1200);
            return;
          }
          const w = node.widgets?.find((x) => x.name === "seed");
          if (w) { w.value = it.seed; if (w.callback) w.callback(it.seed); }
          card.style.borderColor = "#5a8fd0";
        };
        grid.appendChild(card);
      }
    };
    dlg.showModal();
  }

  // ---- 预设管理 (1.8.1): 列表/详情/应用/编辑/删除 —— 预设从"下拉里盲选"变成可视可控 ----
  async function openPresetMgr() {
    await loadPresets();
    const old = document.getElementById("taglib-presetmgr-dialog");
    if (old) old.remove();
    const dlg = document.createElement("dialog");
    dlg.id = "taglib-presetmgr-dialog";
    dlg.classList.add("p-inputtext");
    dlg.setAttribute("translate", "no");
    dlg.style.cssText = "background:#15171d;color:#e3e7ee;border:1px solid #333845;"
      + "border-radius:12px;padding:14px;width:min(620px,94vw);max-height:84vh;overflow:auto;";
    dlg.innerHTML = `
      <div style="font-weight:600;margin-bottom:8px;">📦 预设管理
        <span style="opacity:.6;font-size:11px;">预设 = 当前面板的词标签快照 + 排除域 + 配置；召唤时快照里的词全部打钉, 自动模式不再覆盖它们</span></div>
      <div id="tl-pmgr-list" style="font-size:12px;"></div>
      <div style="display:flex;gap:8px;margin-top:10px;position:sticky;bottom:0;background:#15171d;padding:8px 0;">
        <button id="tl-pmgr-new" class="tl-btn primary" style="padding:4px 12px;">💾 把当前面板存为预设</button>
        <span style="flex:1"></span>
        <button id="tl-pmgr-close" class="tl-btn" style="padding:4px 10px;">关闭</button>
      </div>`;
    document.body.appendChild(dlg);
    const listEl = dlg.querySelector("#tl-pmgr-list");
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

    const summarize = (p) => {
      const bits = [];
      if (p.tags?.length) bits.push(`词 ${p.tags.length}`);
      if (p.pinned?.length) bits.push(`钉 ${p.pinned.length}`);
      if (p.exclude?.length) bits.push(`排除 ${p.exclude.length}`);
      if (p.config && Object.keys(p.config).length) bits.push(`配置 ${Object.keys(p.config).length}`);
      return bits.join(" · ") || "空预设";
    };

    const render = () => {
      listEl.innerHTML = "";
      const mkGroup = (label, arr, isUser) => {
        if (!arr.length) return;
        const h = document.createElement("div");
        h.style.cssText = "opacity:.6;margin:8px 0 4px;";
        h.textContent = label;
        listEl.appendChild(h);
        for (const p of arr) {
          const row = document.createElement("div");
          row.style.cssText = "border:1px solid #2a2e39;border-radius:8px;padding:8px;margin-bottom:6px;";
          const head = document.createElement("div");
          head.style.cssText = "display:flex;gap:8px;align-items:center;";
          head.innerHTML = `<b>${esc(p.name)}</b><span style="opacity:.55;font-size:11px;">${esc(p.kind || "")}</span>
            <span style="opacity:.5;font-size:11px;">${esc(summarize(p))}</span><span style="flex:1"></span>`;
          const btnApply = document.createElement("button");
          btnApply.className = "tl-btn primary";
          btnApply.style.cssText = "padding:2px 10px;font-size:11px;";
          btnApply.textContent = "载入";
          btnApply.onclick = async () => { await applyPreset(p); dlg.close(); };
          head.appendChild(btnApply);
          if (isUser) {
            const btnEdit = document.createElement("button");
            btnEdit.className = "tl-btn";
            btnEdit.style.cssText = "padding:2px 8px;font-size:11px;";
            btnEdit.textContent = "✎ JSON";
            btnEdit.onclick = () => editPresetJson(dlg, p, render);
            const btnDel = document.createElement("button");
            btnDel.className = "tl-btn";
            btnDel.style.cssText = "padding:2px 8px;font-size:11px;";
            btnDel.textContent = "🗑";
            btnDel.onclick = async () => {
              if (!confirm(`删除预设「${p.name}」?`)) return;
              const r = await apiJson("/taglib/api/settings");
              const list = (r?.settings?.presets || []).filter((x) => String(x.id) !== String(p.id));
              await apiJson("/taglib/api/settings", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ settings: { presets: list } }),
              });
              await loadPresets();
              render();
            };
            head.appendChild(btnEdit);
            head.appendChild(btnDel);
          }
          row.appendChild(head);
          const detail = document.createElement("div");
          detail.style.cssText = "opacity:.75;font-size:11px;margin-top:4px;word-break:break-all;";
          detail.textContent =
            (p.pinned?.length ? `钉选: ${p.pinned.join(", ")}
` : "")
            + (p.exclude?.length ? `排除: ${p.exclude.join(", ")}
` : "")
            + (p.note ? `备注: ${p.note}` : "");
          row.appendChild(detail);
          listEl.appendChild(row);
        }
      };
      mkGroup("出厂", _presetsCache.factory, false);
      mkGroup("我的", _presetsCache.user, true);
      if (!_presetsCache.factory.length && !_presetsCache.user.length)
        listEl.innerHTML = `<div style="opacity:.6;">还没有预设 — 点下方「存为预设」创建</div>`;
    };
    render();
    dlg.querySelector("#tl-pmgr-new").onclick = async () => { await savePreset(); render(); };
    dlg.querySelector("#tl-pmgr-close").onclick = () => dlg.close();
    dlg.showModal();
  }

  async function editPresetJson(mgrDlg, preset, rerender) {
    mgrDlg.close();
    const old = document.getElementById("taglib-presetedit-dialog");
    if (old) old.remove();
    const dlg = document.createElement("dialog");
    dlg.id = "taglib-presetedit-dialog";
    dlg.classList.add("p-inputtext");
    dlg.setAttribute("translate", "no");
    dlg.style.cssText = "background:#15171d;color:#e3e7ee;border:1px solid #333845;"
      + "border-radius:12px;padding:14px;width:min(560px,94vw);";
    dlg.innerHTML = `
      <div style="font-weight:600;margin-bottom:8px;">✎ 编辑预设「${preset.name}」(JSON)</div>
      <textarea id="tl-pe-json" rows="14" style="width:100%;box-sizing:border-box;background:#1c1f26;color:inherit;"
        border:1px solid #333845;border-radius:8px;padding:8px;font-size:11px;font-family:monospace;"></textarea>
      <div style="display:flex;gap:8px;margin-top:8px;">
        <button id="tl-pe-save" class="tl-btn primary" style="padding:4px 12px;">保存</button>
        <span id="tl-pe-err" style="color:#e77; font-size:11px;align-self:center;"></span>
        <span style="flex:1"></span>
        <button id="tl-pe-cancel" class="tl-btn" style="padding:4px 10px;">取消</button>
      </div>`;
    document.body.appendChild(dlg);
    const ta = dlg.querySelector("#tl-pe-json");
    ta.value = JSON.stringify(preset, null, 2);
    dlg.querySelector("#tl-pe-cancel").onclick = () => dlg.close();
    dlg.querySelector("#tl-pe-save").onclick = async () => {
      let obj;
      try { obj = JSON.parse(ta.value); }
      catch (e) { dlg.querySelector("#tl-pe-err").textContent = "JSON 不合法: " + e.message; return; }
      if (!obj.name) { dlg.querySelector("#tl-pe-err").textContent = "缺少 name"; return; }
      const r = await apiJson("/taglib/api/settings");
      const list = (r?.settings?.presets || []).map((x) =>
        String(x.id) === String(preset.id) ? obj : x);
      await apiJson("/taglib/api/settings", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: { presets: list } }),
      });
      await loadPresets();
      dlg.close();
      mgrDlg.showModal();
      rerender();
    };
    dlg.showModal();
  }

  /* ---------- ➕ 添加标签窗口 (全库挑选器) ---------- */
  async function openTagPicker(opts) {
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
      "width:min(92vw,1440px);height:min(90vh,900px);border:none;border-radius:14px;" +
      "padding:0;background:var(--tl-bg-solid);color:var(--tl-text);max-width:none;max-height:none;";
    // 翻译免疫 (同面板): 防止挑选器里的标签英文被翻译扩展改写
    dlg.classList.add("p-inputtext", "notranslate", "tl-scope");
    dlg.setAttribute("translate", "no");
    dlg.innerHTML = `<div id="taglib-picker-root" style="width:100%;height:100%;overflow:hidden"></div>`;
    document.body.appendChild(dlg);
    dlg.showModal();
    // 收尾统一走这里 —— **不依赖 dialog 的 close 事件**: Edge 153 在后台标签页里
    // 调 close() 不会派发 close 事件 (2026-09-19 实测), 那样 dialog 就永远留在 DOM 里,
    // 内嵌管理页改过库之后面板也不会刷新。
    let cleaned = false;
    const cleanupPicker = () => {
      if (cleaned) return;
      cleaned = true;
      handle?.destroy?.();
      if (document.getElementById("taglib-picker-dialog") === dlg) dlg.remove();
      if (handle?.libTouched()) {
        // 内嵌管理页可能改过库 -> 刷新缓存, 全部节点面板跟随
        invalidateLibraryCache();
        _profCache = null;      // 档案也可能被改过 -> 复合 chip 的换姿势菜单别用旧档案
        fetchPanelIndex().then(renderAll);
        window.dispatchEvent(new CustomEvent("taglib-updated"));
      }
    };
    const closePicker = () => { dlg.close(); cleanupPicker(); };
    const handle = mountTagPicker(dlg.querySelector("#taglib-picker-root"), {
      onCancel: () => closePicker(),
      onConfirm: (picked) => {
        // picked: [{en, zh?, nsfw?, gender?, weight?, _bundle?}] -> 追加到 state.tags
        // ⚠ 只落盘有意义的字段: weight 是功能字段 (手动权重), _bundle 是既有约定 (⚔ 标识);
        // _hands/_gaze/_axis 是挑选器的界面态, 写进 selection_state 会污染用户工作流。
        const st = getState(node);
        const have = new Set(st.tags.map((t) => t.en.toLowerCase()));
        for (const p of picked) {
          if (have.has(p.en.toLowerCase())) continue;
          const item = { en: p.en, zh: p.zh || "", enabled: true };
          if (p.nsfw) item.nsfw = true;
          if (p.gender) item.gender = p.gender;
          if (p._bundle) item._bundle = p._bundle;
          if (typeof p.weight === "number" && Math.abs(p.weight - 1) > 1e-6) item.weight = p.weight;
          st.tags.push(item);
          have.add(item.en.toLowerCase());
        }
        setState(node, { tags: st.tags });
        renderTags();
        closePicker();
      },
      getExisting: () => new Set(getState(node).tags.map((t) => t.en.toLowerCase())),
      getExcluded: () => getState(node).exclude_categories || [],
      setExcluded: (cats) => { setState(node, { exclude_categories: cats }); },
      onNodeState: renderAll,
      onGlobalChange: () => { applyScale(); renderAll(); },
      node,
    });
    // 面板上的「排除类目」控件直接跳到排除抽屉 —— 不在面板里重复实现一套排除 UI。
    // (opts 若来自 onclick 的 Event, 取不到 tab, 自然跳过)
    if (opts && opts.tab) handle.openTab(opts.tab, opts);
    // 点弹窗外遮罩 = 关闭 (与管理页一致); Esc 走 cancel/close 两条路兜底
    dlg.addEventListener("click", (e) => { if (e.target === dlg) closePicker(); });
    dlg.addEventListener("close", cleanupPicker);
    dlg.addEventListener("cancel", cleanupPicker);
  }

  /* ---------- 随机设置 (原 ⚙ 弹窗) 已并入「添加标签 → ⚙ 设置」页签 ---------- */

  /* ---------- events ---------- */
  container.querySelector('[data-act="addtags"]').onclick = openTagPicker;
  // 排除类目: 打开挑选器并展开侧栏排除抽屉 (不在面板里重复实现一套排除 UI)
  container.querySelector('[data-act="exclude"]').onclick = () =>
    openTagPicker({ tab: "pick", openExclude: true });
  container.querySelector('[data-act="roll"]').onclick = rollFill;
  // 1.8.0: 预设 / 吸收器
  // ⚠ 涩度原先是 [data-act="ninten"] 单按钮 → 已改成 .tl-ninten-seg 三分段,
  //   绑定在 renderNsfwIntensity 旁边 (留着这行会让 querySelector 取到 null,
  //   整个面板构建抛 TypeError —— 实测踩过)
  container.querySelectorAll("[data-scene]").forEach((b) => {
    b.onclick = () => {
      const st = getState(node);
      if (b.dataset.scene === "solo") setState(node, { solo_lock: !st.solo_lock });
      else if (b.dataset.scene === "bg")
        setState(node, { bg_mode: st.bg_mode === "simple" ? "normal" : "simple" });
      else if (b.dataset.scene === "focus")
        setState(node, { focus_mode: st.focus_mode === "portrait" ? "normal" : "portrait" });
      renderSceneBar();
      rollFill({ quiet: true });   // 切换立刻按新约束重抽 (面板词立即变化, 不用自己去按 🎲)
    };
  });
  container.querySelector('[data-act="preset-save"]').onclick = savePreset;
  container.querySelector('[data-act="preset-del"]').onclick = deletePreset;
  container.querySelector('[data-act="absorb"]').onclick = openAbsorb;
  container.querySelector(".tl-preset-sel").onchange = (e) => {
    const p = findPreset(e.target.value);
    if (p) applyPreset(p);
    e.target.value = "";   // 应用后回位, 再选同一预设也能再触发
  };
  loadPresets();
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
    // ⚠ 这里原来会往页面右上角注入一个 fixed 的 🏷 悬浮按钮 (直达管理页)。
    //   按用户要求删掉: 界面全部收进节点面板, 管理页入口 = 面板 ⋯ 菜单的
    //   「🏷 标签库管理」项。别再往回加 —— 独立页面 /taglib 仍保留, 只是不再挂悬浮按钮。
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
