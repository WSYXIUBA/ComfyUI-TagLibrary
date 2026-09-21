/**
 * tagpanel-css.js —— 面板样式 (由 JS 注入, ComfyUI 只自动加载 web/ 下的 .js)
 * 注入一次, style#taglib-panel-style; 幂等可重复加载。
 */

const CSS = `
/* ================= TagLibrary 共享主题变量 (.tl-scope) ================= */
/* 主题适配: ComfyUI 前端在 html 上切 .dark-theme 类 (arc/dark/github/light/
   solarized/nord 六套内置), JS 再把主题 id 写到 data-theme 上。
   这套变量同时服务三种载体 —— 节点面板、挑选器弹窗、管理弹窗 ——
   三者都由 JS 挂上 .tl-scope, 因此配色在任何主题下保持一致。
   浅色 = html 无 .dark-theme, 或元素显式挂 .tl-light。 */
.tl-scope {
  /* 默认 = dark 主题 */
  --tl-bg: rgba(23,23,24,0.94);
  --tl-bg-top: rgba(30,34,44,0.94);
  --tl-bg-solid: #15171d;
  --tl-card: rgba(255,255,255,0.045);
  --tl-card-2: rgba(255,255,255,0.025);
  --tl-border: rgba(255,255,255,0.10);
  --tl-border-2: rgba(255,255,255,0.16);
  --tl-hover: rgba(255,255,255,0.05);
  --tl-text: #e3e7ee;
  --tl-text-2: #aab3c5;
  --tl-text-3: #98a1b3;
  --tl-muted: #8b93a5;
  --tl-dim: #6b7385;
  --tl-accent: #54a0ff;
  --tl-accent-text: #cfe4ff;
  --tl-input-bg: rgba(0,0,0,0.35);
  --tl-code-bg: #12141a;
  --tl-danger: #ff6b6b;
  --tl-danger-soft: #ff9d9d;
  --tl-ok: #7dd47d;
  --tl-warn: #f0a35e;
}
/* ---------- 深色系主题的底色微调 (fg/bg 取自各主题声明值) ---------- */
/* arc: fg #fff, bg #2b2f38, menu #242730 */
.tl-scope[data-theme="arc"] {
  --tl-bg: rgba(36,39,48,0.94);
  --tl-bg-top: rgba(43,47,56,0.94);
  --tl-bg-solid: #242730;
  --tl-card: rgba(255,255,255,0.05);
}
/* github: fg #e5eaf0, bg #161b22, menu #13171d */
.tl-scope[data-theme="github"] {
  --tl-bg: rgba(19,23,29,0.94);
  --tl-bg-top: rgba(22,27,34,0.94);
  --tl-bg-solid: #13171d;
}
/* solarized: fg #fdf6e3, bg #002b36, menu #073642 */
.tl-scope[data-theme="solarized"] {
  --tl-bg: rgba(7,54,66,0.94);
  --tl-bg-top: rgba(11,66,80,0.94);
  --tl-bg-solid: #073642;
  --tl-card: rgba(253,246,227,0.06);
  --tl-card-2: rgba(253,246,227,0.035);
  --tl-border: rgba(253,246,227,0.14);
  --tl-border-2: rgba(253,246,227,0.22);
  --tl-hover: rgba(253,246,227,0.07);
  --tl-text: #fdf6e3;
  --tl-text-2: #cbd6d6;
  --tl-text-3: #aebcbc;
  --tl-muted: #93a1a1;
  --tl-dim: #7e8e8e;
  --tl-accent: #b58900;
  --tl-accent-text: #f0d68a;
  --tl-input-bg: rgba(0,0,0,0.30);
  --tl-code-bg: #04242c;
}
/* nord: fg #e5eaf0, bg #2e3440, menu #161b22 */
.tl-scope[data-theme="nord"] {
  --tl-bg: rgba(22,27,34,0.94);
  --tl-bg-top: rgba(46,52,64,0.94);
  --tl-bg-solid: #161b22;
  --tl-accent: #88c0d0;
  --tl-accent-text: #d8e9ef;
}
/* ---------- 浅色主题 (必须排在深色系覆盖之后: 同特异性靠顺序取胜) ---------- */
html:not(.dark-theme) .tl-scope,
.tl-scope.tl-light,
.tl-scope[data-theme="light"] {
  --tl-bg: rgba(255,255,255,0.96);
  --tl-bg-top: #ffffff;
  --tl-bg-solid: #ffffff;
  --tl-card: rgba(0,0,0,0.045);
  --tl-card-2: rgba(0,0,0,0.025);
  --tl-border: rgba(0,0,0,0.14);
  --tl-border-2: rgba(0,0,0,0.20);
  --tl-hover: rgba(0,0,0,0.05);
  --tl-text: #222;
  --tl-text-2: #4b5563;
  --tl-text-3: #5b6472;
  --tl-muted: #6b7280;
  --tl-dim: #9ca3af;
  --tl-accent: #0071e3;
  --tl-accent-text: #0b4a8f;
  --tl-input-bg: #ffffff;
  --tl-code-bg: #f6f7f9;
  --tl-danger: #d92b2b;
  --tl-danger-soft: #b91c1c;
  --tl-ok: #1f7a34;
  --tl-warn: #a15c14;
}

/* ================= TagLibrary 节点面板 ================= */
.tl-scope *, .tl-scope *::before, .tl-scope *::after { box-sizing: inherit; }
.taglib-widget-holder { all: initial; display: block; font-family: inherit; min-width: 0; width: 100%; height: var(--comfy-widget-height, 60%); min-height: var(--comfy-widget-min-height, 160px); overflow: hidden; box-sizing: border-box; }
.taglib-panel {
  position: relative;      /* ⋯ 菜单的定位上下文 */
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  /* 面板挂了 .p-inputtext 以对翻译扩展免疫, 这里中和 PrimeVue 输入框样式泄漏 */
  appearance: none;
  padding: 0;
  margin: 0;
  border: 0;
  border-radius: 0;
  box-shadow: none;
  outline: none;
  border: 1px solid var(--tl-border);
  border-radius: 10px;
  background: linear-gradient(180deg, var(--tl-bg-top), var(--tl-bg));
  color: var(--tl-text);
  font: 12px/1.45 "Segoe UI", "Microsoft YaHei", sans-serif;
  user-select: none;
  overflow: hidden;
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
  background: color-mix(in srgb, var(--tl-ok) 30%, transparent);
  border-color: color-mix(in srgb, var(--tl-ok) 62%, transparent);
  color: var(--tl-ok);
}
.tl-nsfw-btn.on:hover { box-shadow: 0 0 10px -2px rgba(46,204,113,.55); }


/* 标签 chip 前缀性别符号: ♀粉 / ♂蓝; 通用(无符号)=绿, NSFW=红(已有) */
.tl-gsym { font-weight: 700; margin-right: 3px; }
.tl-gsym.g-f { color: #ff6b9d; }
.tl-gsym.g-m { color: #54a0ff; }
.tl-bsym { font-weight: 700; margin-right: 3px; color: #f0a35e; }
/* 手调权重标记 (1.9.0): chip 上直接看得见 (词:权重) 的效果 */
.tl-wsym { margin-left: 4px; font-size: .78em; opacity: .85; color: var(--tl-warn); }
/* 性别词 chip 边框提亮 (旧值 .25/.35 观感发灰发浅) */
.tl-ttag.gender { border-color: color-mix(in srgb, #54a0ff 45%, rgba(255,255,255,.16)); }
.tl-ttag.gender:has(.g-f) { border-color: rgba(255,107,157,.6); }
.tl-ttag.gender:has(.g-m) { border-color: rgba(84,160,255,.6); }
.tl-ttag.gender.on { background: color-mix(in srgb, #2ecc71 20%, transparent); }
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

/* ---------- 工具行 ---------- */
.tl-toolbar { display: flex; align-items: center; gap: 6px; padding: 7px 10px 2px; }
.tl-search {
  flex: 1; min-width: 40px;
  background: var(--tl-input-bg);
  border: 1px solid var(--tl-border);
  border-radius: 7px;
  color: var(--tl-text);
  font: inherit; font-size: 11px;
  padding: 4px 9px;
  outline: none;
}
.tl-search:focus {
  border-color: color-mix(in srgb, var(--tl-accent) 60%, transparent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--tl-accent) 12%, transparent);
}
.tl-search::placeholder { color: var(--tl-muted); }

/* ⚠ 分段按钮样式统一在下方「控件原语」一节定义, 此处不得重复定义。
   历史事故: 这里原本另有一份同名规则, 靠书写顺序取胜, 静默覆盖了下方定义,
   使选中态与悬停态同色 —— 用户看不出当前选中哪一档。 */


/* ---------- chips 区 ---------- */
.tl-chipzone {
  margin: 4px 10px 6px;
  border: 1px solid var(--tl-border);
  border-radius: 9px;
  background: var(--tl-card-2);
  padding: 7px;
  flex: 1;
  min-height: 58px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,.18) transparent;
}
.tl-empty { color: var(--tl-muted); font-size: 11px; padding: 12px 4px; text-align: center; }

/* ---------- chip 上小按钮 (钉选 / 移除) ---------- */
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

/* 停用: 中性灰 (走 token —— 曾经的 rgba(255,255,255,.16) 在白底上边框消失) */
.tl-ttag {
  background: var(--tl-card);
  border: 1px solid var(--tl-border-2);
  color: var(--tl-text-2);
}

/* 启用: 绿 (走 --tl-ok —— 曾经的 #d9ffe8 在浅色主题下几乎不可读) */
.tl-ttag.on {
  background: color-mix(in srgb, var(--tl-ok) 20%, transparent);
  border-color: color-mix(in srgb, var(--tl-ok) 58%, transparent);
  color: var(--tl-ok);
  box-shadow: 0 0 6px -2px color-mix(in srgb, var(--tl-ok) 55%, transparent);
}
.tl-ttag.on:hover { background: color-mix(in srgb, var(--tl-ok) 30%, transparent); }
.tl-ttag.nsfw:not(.on) {
  border-color: color-mix(in srgb, var(--tl-danger) 45%, transparent);
  color: var(--tl-danger-soft);
}
/* mutex 让位 (auto 回显): 灰显 + 删除线 */
.tl-ttag.tl-dropped { opacity: .42; text-decoration: line-through; }
.tl-ttag.tl-dropped::before { content: "🚫 "; font-size: 9px; }
/* 性别过滤剔除 (♀ 时男性专属 / ♂ 时女性专属): 虚线 + 灰显 + 删除线, chip 自带 ♂♀ 符号 */
.tl-ttag.tl-gdrop { opacity: .45; border-style: dashed; text-decoration: line-through; }
.tl-ttag.tl-gdrop.on { background: transparent; box-shadow: none; }
/* NSFW 开关为「关」时不输出的词: 同样虚线+删除线, 但描红边区分原因 */
.tl-ttag.tl-ndrop { opacity: .45; border-style: dashed; text-decoration: line-through;
                    border-color: color-mix(in srgb, var(--tl-danger) 55%, transparent) !important; }
.tl-ttag.tl-ndrop.on { background: transparent; box-shadow: none; }
/* ---------- ⋯ 更多菜单 (低频操作集中地, 同时是状态读数板) ---------- */
.tl-more-btn { position: relative; font-size: 14px; line-height: 1; padding: 2px 7px; }
.tl-more-dot { display: none; }
.tl-more-btn.dirty::after {
  content: ""; position: absolute; top: 3px; right: 4px;
  width: 5px; height: 5px; border-radius: 50%; background: var(--tl-accent);
}
.tl-menu {
  position: absolute; right: 8px; bottom: 38px; z-index: 20; min-width: 172px;
  border: 1px solid var(--tl-border-2); border-radius: 9px;
  background: var(--tl-bg-solid); box-shadow: 0 6px 20px rgba(0,0,0,.35);
  overflow: hidden; display: flex; flex-direction: column;
}
.tl-menu[hidden] { display: none; }
.tl-menu-item {
  display: flex; align-items: center; gap: 8px;
  border: 0; background: transparent; color: var(--tl-text); text-align: left;
  font: inherit; font-size: 11.5px; padding: 6px 10px; cursor: pointer;
  transition: background .12s;
}
.tl-menu-item + .tl-menu-item { border-top: 1px solid var(--tl-border); }
.tl-menu-item:hover { background: var(--tl-hover); }
.tl-menu-item:focus-visible { outline: 2px solid var(--tl-accent); outline-offset: -2px; }
.tl-menu-item .tl-mi-k { flex: 1; color: var(--tl-text-2); }
.tl-menu-item .tl-mi-v { color: var(--tl-muted); font-size: 11px; }
.tl-menu-item.on .tl-mi-v { color: var(--tl-accent-text); font-weight: 600; }
.tl-menu-item.g-female .tl-mi-v { color: #ff6b9d; }
.tl-menu-item.g-male .tl-mi-v { color: var(--tl-accent); }

/* 控件行 —— 什么语义给什么控件:
   开关(.tl-sw) / 三分段(.tl-seg) / 下拉(.tl-sel)。
   ⚠ 不再有"点胶囊循环": 用户看不出能不能点、也不知道点完会变成什么。 */
.tl-controls { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center;
               padding: 6px 10px 2px; }
.tl-ctl { display: inline-flex; align-items: center; gap: 6px; }
.tl-ctl[hidden] { display: none; }
.tl-ctl-k { font-size: 11.5px; color: var(--tl-text-2); white-space: nowrap; }

.tl-sw { position: relative; width: 30px; height: 17px; flex: 0 0 auto; padding: 0;
         border-radius: 9px; cursor: pointer; border: 1px solid var(--tl-border-2);
         background: var(--tl-input-bg); transition: background .16s, border-color .16s; }
.tl-sw i { position: absolute; top: 1px; left: 1px; width: 13px; height: 13px;
           border-radius: 50%; background: var(--tl-muted);
           transition: transform .16s, background .16s; }
.tl-sw.on { background: color-mix(in srgb, var(--tl-accent) 55%, transparent);
            border-color: var(--tl-accent); }
.tl-sw.on i { transform: translateX(13px); background: #fff; }
.tl-sw:focus-visible { outline: 2px solid var(--tl-accent); outline-offset: 2px; }

/* ---------- 分段按钮 (多档语义: 手动/自动 · 性别 · 涩度三档) ----------
   ⚠ 全文件只此一份定义。历史事故: 上方原本还有第二份同名规则, 同特异性
   靠书写顺序取胜, 使选中态被悬停色覆盖 —— 用户看不出选了哪档。 */
.tl-seg { display: inline-flex; background: var(--tl-input-bg);
          border: 1px solid var(--tl-border-2); border-radius: 6px; padding: 1px; }
.tl-seg button { border: none; background: transparent; color: var(--tl-text-2);
                 font-size: 11px; padding: 2px 7px; border-radius: 4px; cursor: pointer;
                 transition: background .13s, color .13s; }
.tl-seg button:hover { color: var(--tl-text); }
.tl-seg button.active {
  background: color-mix(in srgb, var(--tl-accent) 28%, transparent);
  color: var(--tl-accent-text); font-weight: 500;
}

.tl-mi-row { display: flex; align-items: center; gap: 8px; padding: 6px 10px; }
.tl-mi-row .tl-mi-k { flex: 1; color: var(--tl-text-2); }
.tl-sel { background: var(--tl-input-bg); border: 1px solid var(--tl-border-2);
          border-radius: 5px; color: var(--tl-text); font-size: 11.5px; padding: 2px 6px; }
/* 排除类目读数按钮: 「无」= 中性; 「N 项」= 警示色 (有东西被排除掉) */
.tl-excbtn { border: 1px solid var(--tl-border-2); background: var(--tl-input-bg);
             color: var(--tl-muted); font: inherit; font-size: 11px; padding: 2px 8px;
             border-radius: 6px; cursor: pointer; transition: background .13s, color .13s; }
.tl-excbtn:hover { color: var(--tl-text); }
.tl-excbtn.on { background: color-mix(in srgb, var(--tl-warn) 22%, transparent);
                border-color: color-mix(in srgb, var(--tl-warn) 55%, transparent);
                color: var(--tl-text); font-weight: 500; }
.tl-stchip.hot { border-color: #4aa564; background: color-mix(in srgb, #4aa564 18%, transparent); }
.tl-stchip.warn { border-color: var(--tl-warn); background: color-mix(in srgb, var(--tl-warn) 16%, transparent); }

/* ⋯ 菜单里的分区标题 + 场景/预设行 (它们从面板主体搬进来了) */
.tl-menu-sec {
  padding: 7px 10px 3px; font-size: 10.5px; color: var(--tl-muted);
  border-top: 1px solid var(--tl-border);
}
.tl-menu-sec:first-child { border-top: none; }
.tl-menu .tl-preset-row { display: flex; gap: 4px; align-items: center; padding: 2px 10px 6px; }
.tl-menu .tl-preset-row .tl-preset-sel { flex: 1; min-width: 0; }
.tl-menu .tl-nsfw-btn { margin: 2px 10px 6px; }
.tl-menu-item.danger .tl-mi-k { color: var(--tl-danger); }
.tl-menu-item.danger:hover { background: rgba(255,71,87,.10); }
.tl-ttag.nsfw.on {
  background: color-mix(in srgb, #ff4757 22%, transparent);
  border-color: rgba(255,71,87,.7);
  color: #ffdada;
  box-shadow: 0 0 6px -2px rgba(255,71,87,.55);
}

/* ---------- 模式说明 (1.9.0) ----------
   「手动模式下总词数 40~60 还生效吗?」—— 旧界面从不回答这个问题, 用户只能靠猜。
   实情: manual 走 chosen 列表原样输出 (不受配额约束), auto 才按配额随机组合。 */
.tl-mode-hint {
  padding: 0 10px 6px;
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--tl-muted);
}
.tl-mode-hint b { color: var(--tl-text-2); font-weight: 600; }
/* 档案束复合 chip: [⚔ 武士刀 · 拔刀 ✕] —— 一束是一个对象, 不是一个词 */
.tl-ttag.tl-bundle { border-color: color-mix(in srgb, #f0a35e 55%, rgba(255,255,255,.16)); }
.tl-ttag.tl-bundle.on { background: color-mix(in srgb, #f0a35e 22%, transparent); }
.tl-ttag.tl-bundle .tl-bw {
  margin-left: 5px; font-size: .78em; opacity: .7;
  border: 1px solid currentColor; border-radius: 99px; padding: 0 5px;
}
.tl-bundle-menu {
  position: fixed; z-index: 10050; display: flex; flex-direction: column;
  min-width: 190px; max-height: 60vh; overflow-y: auto;
  background: var(--tl-card); border: 1px solid var(--tl-border-2); border-radius: 10px;
  box-shadow: 0 12px 32px rgba(0,0,0,.45); padding: 5px; font-size: 12px;
}
.tl-bundle-menu .bm-h {
  padding: 5px 9px 6px; font-size: 10.5px; color: var(--tl-muted);
  border-bottom: 1px solid var(--tl-border); margin-bottom: 4px;
}
.tl-bundle-menu button {
  display: flex; align-items: center; gap: 7px; width: 100%; text-align: left;
  background: transparent; border: 0; color: var(--tl-text-2); font: inherit;
  font-size: 12px; padding: 5px 9px; border-radius: 7px; cursor: pointer;
}
.tl-bundle-menu button:hover { background: var(--tl-hover); color: var(--tl-text); }
.tl-bundle-menu button.checked { color: var(--tl-ok); font-weight: 600; }
.tl-bundle-menu button.danger { color: var(--tl-danger); }
.tl-bundle-menu .bm-sep { height: 1px; background: var(--tl-border); margin: 4px 2px; }

/* ---------- 底部预览 ---------- */
.tl-preview-row {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 10px 8px;
}
.tl-preview {
  flex: 1;
  font-size: 10.5px;
  color: var(--tl-text-2);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  background: var(--tl-code-bg);
  border: 1px solid var(--tl-border);
  border-radius: 7px;
  padding: 4px 8px;
}
.tl-roll-btn {
  display: inline-flex; align-items: center; gap: 5px;
  border: 1px solid color-mix(in srgb, var(--tl-accent) 50%, transparent);
  background: linear-gradient(135deg,
              color-mix(in srgb, var(--tl-accent) 30%, transparent),
              color-mix(in srgb, var(--tl-accent) 14%, transparent));
  color: var(--tl-accent-text);
  border-radius: 8px;
  font: inherit; font-size: 11px; font-weight: 600;
  padding: 4px 12px;
  cursor: pointer;
  transition: all .15s ease;
}
.tl-roll-btn:hover { box-shadow: 0 0 12px -2px rgba(84,160,255,.55); transform: translateY(-1px); }
.tl-roll-btn:active { transform: translateY(0); }


/* chip 右键菜单 (钉选/移除) —— 单例复用, 配色跟随主题变量 */
.tl-chip-menu {
  position: fixed; z-index: 99999; min-width: 180px;
  background: var(--tl-bg-solid); border: 1px solid var(--tl-border-2);
  border-radius: 8px; padding: 4px; box-shadow: 0 6px 20px rgba(0,0,0,.35);
  display: flex; flex-direction: column;
}
.tl-chip-menu button {
  background: none; border: none; color: var(--tl-text); text-align: left;
  padding: 6px 12px; font-size: 12.5px; cursor: pointer; border-radius: 5px;
}
.tl-chip-menu button:hover { background: var(--tl-hover); }
.tl-chip-menu button.danger { color: var(--tl-danger); }
/* 自动载入标签的 📌 (半透明, 仅提示可右键钉选) — 已废弃: 只在真钉选时显示 */

/* ---- 1.8.1 场景条 + 强度按钮 (全部走主题变量, 深浅主题自适应) ----
   ⚠ .tl-scene-row / .tl-scene-btn 已删除 (2026-09-20):
   场景三档 (单人锁/简背景/特写) 已改为面板上的标准开关 (.tl-sw), 与 NSFW、
   防冲突统一为蓝色拨杆。旧类名是"菜单宽按钮"时代的遗留, 它把同一个元素
   既当 30×17 拨杆又当 flex:1 宽按钮, 并把 .on 刷成绿色 (#2ecc71) —— 于是
   同一个面板里"开"出现了两种颜色。类名在 JS 中已无创建点。 */
.tl-preset-sel {
  flex: 1; min-width: 0; font: inherit; font-size: 11px; padding: 3px 4px;
  background: var(--tl-input-bg); color: var(--tl-text);
  border: 1px solid var(--tl-border-2); border-radius: 7px;
}
/* 预设行 (1.11.0): 从 ⋯ 菜单搬到主区, 让预设「可见 + 可选」 */
.tl-preset-bar {
  display: flex; align-items: center; gap: 5px;
  padding: 4px 10px 5px;
}
.tl-preset-bar .tl-preset-k {
  font-size: 11px; color: var(--tl-muted); white-space: nowrap;
}
.tl-preset-bar .tl-preset-sel { flex: 1; min-width: 0; }
.tl-preset-bar .tl-btn.icon { padding: 2px 6px; }
.tl-preset-tip { font-size: 10.5px; color: var(--tl-muted); }
.tl-ninten-btn { padding: 3px 8px; font-size: 10px; }
.tl-ninten-btn.on {
  background: color-mix(in srgb, #e67e22 26%, var(--tl-card));
  border-color: rgba(230, 126, 34, .65);
  color: #f0b27a;
  font-weight: 600;
}
`;

export function injectPanelStyle() {
  if (document.getElementById("taglib-panel-style")) return;
  const el = document.createElement("style");
  el.id = "taglib-panel-style";
  el.textContent = CSS;
  document.head.appendChild(el);
}
