/**
 * 流水线首页 —— 详情页的默认视图 (2026-09-19 编辑体验改造)。
 *
 * 为什么要首页: 原来打开挑选器直接落到「挑标签」的 65 个槽位树上, 看不出
 * 提示词是**怎么拼起来的**。这里按 Anima 官方六段次序
 *   [质量·元信息·风格][人数][角色][作品][画师][通用]
 * 把 13 条轴摆成一条流水线 —— 首页看完整概括, 点进去看细节。
 *
 * ⚠ 段位/段名/轴名**全部来自 `GET /taglib/api/axes-overview`** (后端直读
 *   `axes.AXIS_SECTION` / `SECTION_NAMES` / `AXIS_NAME_ZH`)。前端不再抄一份,
 *   否则官方次序一改, 前端就静默漂移。
 *
 * ## 布局演进 (都是真机截图后才定的, 不是拍脑袋)
 *
 * 1.0 横向 + 上下交替 (最初原型): 实测 `.pl-flow` 只有约 730px 可用宽,
 *     13 个方框 + 7 段至少要 1200px —— 段6 (8 条轴) 被折成 4 行、纵跨
 *     286→470px 直接穿过流水线, 把段2/段4 的标签压进框堆里, 内容挤在左上角。
 * 2.0 纵向 + 左右交替: 不挤了, 但段与段宽度差太大 (段1 有 2 框、段2 只有 1 框),
 *     左右交替产生大片空洞 —— 左半边几乎全空、下方 240px 空着, 像"散落的方框"
 *     而不是流水线。轴线细到看不见。
 * 3.0 (本版) **纵向主轴靠左 + 段名固定栏 + 方框向右铺满整行**:
 *     段名有固定列宽, 方框区独占剩余约 980px, 段6 的 8 条轴刚好一行放下
 *     (8×118 + 7×6 = 986)。既保住了"按官方次序自上而下"的流水线感,
 *     又没有任何空洞。
 *
 * ⚠ 方框宽度是**算出来的**, 不是猜的: 980px 里塞 8 个最宽的段。
 *   改动 `.pl-flow` 的列宽或方框宽度前, 先确认 8 个方框还放得下一行。
 */

const API_OVERVIEW = "/taglib/api/axes-overview";
const API_INCOMPLETE = "/taglib/api/tag/incomplete";

// 方框固定宽度 —— 不用内容撑宽, 否则"外貌特征 / 1018 词 · 15 槽"会比
// "画师 / 0 词 · 1 槽"宽出一截, 整排参差不齐。
// ⚠ 110 是**算出来的上限**: 容器 1200 − 主轴列 34 − 段名列 164 − 两侧内边距 ≈ 940px,
//   段6 有 8 条轴, 8×110 + 7×6 = 922 < 940 (刚好一行)。实测 118 时"材质特效"会被挤到第二行。
const BOX_W = 110;

const CSS = `
.pl-wrap { position:relative; flex:1; overflow:auto; padding:12px 20px 18px; }
.pl-head { display:flex; align-items:baseline; gap:10px; margin-bottom:12px; flex-wrap:wrap; }
.pl-title { font-size:14px; font-weight:500; color:var(--tl-text); }
.pl-sub { font-size:11.5px; color:var(--tl-text-2); }
.pl-badge { margin-left:auto; font-size:11.5px; padding:2px 9px; border-radius:11px;
            border:1px solid var(--tl-border-2); color:var(--tl-text-2); cursor:pointer;
            white-space:nowrap; }
.pl-badge.hot { color:var(--tl-warn); border-color:color-mix(in srgb, var(--tl-warn) 55%, transparent); }

/* 三列: 主轴(圆点) | 段名固定栏 | 方框区。主轴在 17px 处 —— 列宽固定,
   所以轴线的 x 是确定的, 不依赖 50% 这种会被内容影响的算法。 */
.pl-flow { position:relative; display:grid; grid-template-columns:34px 164px 1fr;
           align-items:center; row-gap:7px; align-content:center; min-height:100%;
           transition:transform .42s cubic-bezier(.22,.61,.36,1); transform-origin:50% 50%; }
.pl-flow::before { content:''; position:absolute; left:16px; top:4px; bottom:4px; width:2px;
                   border-radius:2px;
                   background:color-mix(in srgb, var(--tl-accent) 45%, var(--tl-border-2)); }
.pl-flow.zoomed .pl-name, .pl-flow.zoomed .pl-boxes { opacity:.24; }
.pl-flow.zoomed .pl-name.on, .pl-flow.zoomed .pl-boxes.on { opacity:1; }

.pl-dot { width:22px; height:22px; border-radius:50%; display:flex; align-items:center;
          justify-content:center; font-size:11.5px; color:var(--tl-text);
          background:var(--tl-card); border:1px solid var(--tl-border-2);
          justify-self:center; z-index:1; }
.pl-flow.zoomed .pl-dot { opacity:.4; }

.pl-name { font-size:11.5px; color:var(--tl-text-2); line-height:1.35;
           text-align:right; padding-right:2px; }
.pl-name b { display:block; font-size:12.5px; font-weight:500; color:var(--tl-text); }

.pl-boxes { display:flex; flex-wrap:wrap; gap:6px; }
.pl-box { width:${BOX_W}px; box-sizing:border-box; display:flex; flex-direction:column;
          align-items:center; justify-content:center; gap:2px; padding:7px 6px;
          border-radius:9px; cursor:pointer; text-align:center;
          background:var(--tl-card); border:1px solid var(--tl-border-2);
          color:var(--tl-text); font-size:12.5px; line-height:1.25;
          transition:transform .42s cubic-bezier(.22,.61,.36,1),
                     box-shadow .2s, border-color .2s; }
.pl-box:hover { border-color:var(--tl-accent); }
.pl-box .pl-n { font-size:11px; color:var(--tl-text-2); white-space:nowrap; }
.pl-box.empty { border-style:dashed; opacity:.55; cursor:default; }
.pl-box.focus { border-color:var(--tl-accent);
                box-shadow:0 0 0 2px color-mix(in srgb, var(--tl-accent) 35%, transparent); }
.pl-box .pl-go { display:none; font-size:11px; color:var(--tl-accent); }
.pl-box.focus .pl-go { display:block; }

.pl-empty-row { padding:26px 4px; color:var(--tl-text-2); font-size:12px; }
`;

let _styleDone = false;
function injectStyle() {
  if (_styleDone) return;
  const s = document.createElement("style");
  s.textContent = CSS;
  document.head.appendChild(s);
  _styleDone = true;
}

/**
 * 渲染流水线首页。
 * @param {HTMLElement} host 容器
 * @param {{ onPick:(axisId:string, axisZh:string)=>void, onIncomplete?:(inc:object)=>void }} opts
 */
export async function renderPipeline(host, opts = {}) {
  injectStyle();
  host.innerHTML = `<div class="pl-wrap"><div class="pl-empty-row">加载中…</div></div>`;

  let data;
  try {
    const r = await fetch(API_OVERVIEW, { headers: { Accept: "application/json" } });
    data = await r.json();
  } catch (e) {
    host.querySelector(".pl-wrap").innerHTML =
      `<div class="pl-empty-row">首页数据加载失败: ${String(e.message || e)}</div>`;
    return;
  }
  if (!data?.ok || !Array.isArray(data.segments)) {
    host.querySelector(".pl-wrap").innerHTML =
      `<div class="pl-empty-row">首页数据异常</div>`;
    return;
  }

  const wrap = host.querySelector(".pl-wrap");
  wrap.innerHTML = "";

  const head = document.createElement("div");
  head.className = "pl-head";
  head.innerHTML =
    `<span class="pl-title">提示词拼接流水线</span>` +
    `<span class="pl-sub">按 Anima 官方六段次序 · 共 ${data.total} 个标签 · ` +
    `点方框放大，再点进入该类目</span>`;
  const badge = document.createElement("span");
  badge.className = "pl-badge";
  badge.textContent = "待完善 …";
  let inc = null;
  badge.onclick = () => opts.onIncomplete?.(inc);
  head.appendChild(badge);
  wrap.appendChild(head);

  const flow = document.createElement("div");
  flow.className = "pl-flow";

  let focused = null;          // 当前放大中的方框 (null = 未放大)

  function clearFocus() {
    if (!focused) return;
    const holder = focused.closest(".pl-boxes");
    focused.classList.remove("focus");
    holder?.classList.remove("on");
    if (holder?._nameEl) holder._nameEl.classList.remove("on");
    flow.classList.remove("zoomed");
    flow.style.transform = "";
    flow.style.transformOrigin = "";
    focused = null;
  }

  function focusBox(box) {
    focused = box;
    const holder = box.closest(".pl-boxes");
    box.classList.add("focus");
    holder?.classList.add("on");
    if (holder?._nameEl) holder._nameEl.classList.add("on");
    flow.classList.add("zoomed");
    // 以该方框为中心放大 —— "放大铺满"而不是整页平移
    const fr = flow.getBoundingClientRect();
    const br = box.getBoundingClientRect();
    flow.style.transformOrigin =
      `${((br.left + br.width / 2 - fr.left) / fr.width) * 100}% ` +
      `${((br.top + br.height / 2 - fr.top) / fr.height) * 100}%`;
    flow.style.transform = "scale(1.28)";
  }

  data.segments.forEach((seg, i) => {
    const row = String(i + 1);          // ⚠ 必须显式给行号: 三列 + 自动布局
                                        // 会按文档顺序填格子, 段与段会错行

    const dot = document.createElement("span");
    dot.className = "pl-dot";
    dot.textContent = String(seg.section);
    dot.style.gridColumn = "1";
    dot.style.gridRow = row;

    const name = document.createElement("div");
    name.className = "pl-name";
    name.innerHTML = `<b>${seg.name}</b>` +
      (seg.axes.length ? `${seg.axes.length} 条轴` : "保留段位");
    name.style.gridColumn = "2";
    name.style.gridRow = row;

    const boxes = document.createElement("div");
    boxes.className = "pl-boxes";
    boxes.style.gridColumn = "3";
    boxes.style.gridRow = row;
    boxes._nameEl = name;               // 放大时一起高亮, 见 focusBox

    if (seg.placeholder) {
      // 库内暂无对应轴 (段4 作品 / 段9 未归类)。**只画一条虚线, 不再放方框** ——
      // 段名列已经写了段名, 框里再写一遍是重复噪音 (实测第一版就是这样)。
      const b = document.createElement("div");
      b.className = "pl-box empty";
      b.innerHTML = `<span class="pl-n">Anima 官方次序保留此段, 库内暂无对应轴</span>`;
      b.style.width = "auto";
      b.style.padding = "7px 12px";
      boxes.appendChild(b);
    } else {
      seg.axes.forEach((ax) => {
        const b = document.createElement("button");
        b.className = "pl-box";
        b.innerHTML =
          `<span class="pl-zh">${ax.zh}</span>` +
          `<span class="pl-n">${ax.count} 词 · ${ax.slots} 槽</span>` +
          `<span class="pl-go">再点进入 ›</span>`;
        b.title = `${ax.zh} · ${ax.count} 个标签 / ${ax.slots} 个槽位`;
        b.onclick = (ev) => {
          ev.stopPropagation();
          if (focused === b) { opts.onPick?.(ax.id, ax.zh); return; }
          clearFocus();
          focusBox(b);
        };
        boxes.appendChild(b);
      });
    }

    flow.appendChild(dot);
    flow.appendChild(name);
    flow.appendChild(boxes);
  });

  wrap.appendChild(flow);

  // 点空白处 / Esc 复位
  wrap.addEventListener("click", (e) => {
    if (!e.target.closest(".pl-box")) clearFocus();
  });
  host._plEsc = (e) => { if (e.key === "Escape") clearFocus(); };
  document.addEventListener("keydown", host._plEsc);

  // 待完善角标 (异步, 不挡首页渲染)
  (async () => {
    try {
      const r = await fetch(API_INCOMPLETE, { headers: { Accept: "application/json" } });
      const got = await r.json();
      if (!got?.ok) { badge.textContent = ""; return; }
      inc = got;
      if (got.total > 0) {
        badge.classList.add("hot");
        badge.textContent = `待完善 ${got.total}`;
        const c = got.counts || {};
        badge.title =
          `未建档武器 ${c.weapon_unregistered || 0} · ` +
          `陈旧引用 ${c.dangling_ref || 0} · 缺句式族 ${c.pose_no_family || 0}`;
      } else {
        badge.textContent = "待完善 0";
      }
    } catch { badge.textContent = ""; }
  })();
}

/** 卸载时解绑 (挑选器关掉时调用, 避免 document 级监听堆积)。 */
export function disposePipeline(host) {
  if (host?._plEsc) {
    document.removeEventListener("keydown", host._plEsc);
    host._plEsc = null;
  }
}
