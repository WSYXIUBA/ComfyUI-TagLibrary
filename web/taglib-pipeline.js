/**
 * 流水线首页 v3 —— 横向主轴 + 语义缩放 + 装配动效
 *
 * ## 架构（第三次重写，前两次为什么不行）
 *
 * v1 横向 + 固定 110px 双行方框: 15 个方框 + 7 段至少要 1734px, 而弹窗内
 *    `.pl-flow` 只有约 1164px —— 于是 flex-wrap 把段6 的 8 个框折成 4 行,
 *    纵跨 286→470px 穿过主轴, 把别的段压进框堆里。整块挤在左上角。
 * v2 纵向 + 段名固定栏: 不挤了, 但段与段宽度差太大, 左右交替产生大片空洞,
 *    且偏离了用户选定的"横向"。
 * v3 (本版) **横向 + 语义缩放**:
 *    - 总览态方框只显示**轴名**(单行胶囊, 40~64px), 15 个加起来约 852px,
 *      加站点间距与节点共约 1064px —— **横向一行放得下, 不需要滚动**。
 *    - `N 词 · M 槽` 与槽位信息**只在聚焦时以浮层卡片出现**; 卡片是
 *      `position:absolute`, 所以**不会引起整行回流**(v1 的致命问题)。
 *    - 主轴用 `::before` 定在节点行中心; 胶囊**逐颗按"当前更窄的那排"分上下**
 *      (先全挂上排、量真实宽度再搬), 段名留在主轴线上;
 *      两排高度用 `clamp(44px, 12vh, 132px)` 随视口撑开 —— 否则中间一条细线、
 *      上下各留一大片空档。
 *
 * ⚠ 一句话: **信息密度随"缩放层级"变化, 而不是塞进固定尺寸的方框**。
 *   以后要往方框里加内容, 先想清楚它属于总览态还是聚焦态 —— 别再撑大总览结构。
 *
 * ## 动效
 * - 打开时沿官方次序**自左向右依次落位**(每格 45ms 递延) + 主轴从左画出
 * - 聚焦: 胶囊原地轻微抬起(只用 transform, 不动布局) + 卡片弹出(cubic-bezier 回弹)
 *   卡片挂在胶囊上, 上排朝上、下排朝下 (朝离主轴远的一侧, 不遮别的胶囊)
 * - 再点同一个 → 进入该轴
 *
 * 数据全部来自 `GET /taglib/api/axes-overview`(后端直读 axes.AXIS_SECTION /
 * SECTION_NAMES / AXIS_NAME_ZH), 前端不抄次序。
 */

const API_OVERVIEW = "/taglib/api/axes-overview";

const CSS = `
.pl-wrap { position:relative; flex:1; overflow:auto; padding:12px 16px 16px;
           display:flex; flex-direction:column; }
.pl-head { display:flex; align-items:baseline; gap:10px; margin-bottom:18px; flex-wrap:wrap; }
.pl-title { font-size:14px; font-weight:500; color:var(--tl-text); }
.pl-sub { font-size:11.5px; color:var(--tl-text-2); }
.pl-badge { margin-left:auto; font-size:11.5px; padding:2px 9px; border-radius:11px;
            border:1px solid var(--tl-border-2); color:var(--tl-text-2); cursor:pointer;
            white-space:nowrap; }
.pl-badge.hot { color:var(--tl-warn); border-color:color-mix(in srgb, var(--tl-warn) 55%, transparent); }

/* 横向主板: 类目沿 X 轴排开, 每一类的**入口在 Y 方向竖成一列** (齿朝外)。
   站点 = 上侧 / 主轴 / 下侧 三行 —— 上侧底对齐、下侧顶对齐, 都紧贴主轴,
   入口列朝外长出去; 类目标签与入口列分居两侧并按段交替。
   站点等宽 (flex:1) → 7 颗齿沿主轴均匀分布, 不是挤在左边。 */
.pl-flow { position:relative; flex:1; display:flex; align-items:stretch;
           justify-content:center; gap:6px; padding:0;
           transition:transform .45s cubic-bezier(.2,.7,.3,1); transform-origin:50% 50%; }

/* 三行: 上下两行等分 (1fr) 且主轴行固定 → 7 个站点的主轴严格共线 */
.pl-station { position:relative; display:grid; flex:1 1 0; min-width:0;
              grid-template-rows:1fr 34px 1fr;
              justify-items:center; align-items:stretch;
              opacity:0; transform:translateY(6px);
              animation:pl-in .4s cubic-bezier(.2,.8,.3,1) forwards;
              animation-delay:calc(var(--i) * 45ms + 120ms); }
@keyframes pl-in { to { opacity:1; transform:none; } }

/* 主轴: **一条不带文字的线**, 每站画自己那一段 —— 站与站之间留 6px 缝,
   看上去就是"中断多个"的虚线轴, 而不是一根贯穿的实线。 */
.pl-axis { grid-row:2; grid-column:1; justify-self:stretch; height:4px; align-self:center;
           border-radius:2px; transform:scaleX(0); transform-origin:left center;
           background:color-mix(in srgb, var(--tl-accent) 40%, var(--tl-border-2));
           animation:pl-draw .5s cubic-bezier(.3,.8,.3,1) .05s forwards; }
@keyframes pl-draw { to { transform:scaleX(1); } }

/* 节点: 纯圆点, 不带编号 —— 编号挪去跟类目标签作伴 (轴上不留任何文字) */
.pl-dot { grid-row:2; grid-column:1; justify-self:center; align-self:center; z-index:2;
          width:20px; height:20px; border-radius:50%;
          background:var(--tl-card); border:2px solid
          color-mix(in srgb, var(--tl-accent) 55%, var(--tl-border-2)); }

/* 类目标签 / 入口列: 分居主轴上下, 按段交替; 两侧都**紧贴主轴**朝外长 */
.pl-label { display:flex; align-items:center; gap:5px; white-space:nowrap; }
.pl-entries { display:flex; flex-direction:column; align-items:center; gap:8px; }
.pl-label, .pl-entries { grid-column:1; }

/* 默认 (偶数段): 标签在上贴着轴, 入口列在下朝下长 */
.pl-station .pl-label { grid-row:1; align-self:end; }
.pl-station .pl-entries { grid-row:3; align-self:start; }
/* 奇数段反过来: 入口列在上朝上长, 标签在下贴着轴 */
.pl-station.alt .pl-label { grid-row:3; align-self:start; }
.pl-station.alt .pl-entries { grid-row:1; align-self:end; }

.pl-sec { font-size:12.5px; line-height:1; padding:5px 10px; border-radius:8px;
          color:var(--tl-text-2); border:1px solid var(--tl-border-2); }
.pl-segname { font-size:14px; color:var(--tl-text-2); white-space:nowrap; }

/* 总览态: 只显示轴名的胶囊。信息量小 → 才排得下 15 个。 */
.pl-chip { position:relative; padding:11px 20px; border-radius:999px; cursor:pointer; white-space:nowrap;
           font-size:15px; line-height:1; color:var(--tl-text);
           background:var(--tl-card); border:1px solid var(--tl-border-2);
           transition:transform .32s cubic-bezier(.2,.8,.3,1),
                      border-color .18s, box-shadow .18s, background .18s; }
.pl-chip:hover { border-color:var(--tl-accent); transform:translateY(-2px);
                 box-shadow:0 2px 10px rgba(0,0,0,.18); }
.pl-chip.on { border-color:var(--tl-accent); background:color-mix(in srgb, var(--tl-accent) 20%, var(--tl-card));
              transform:translateY(-3px) scale(1.06); }
.pl-chip.empty { border-style:dashed; opacity:.5; cursor:default; }

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
 * @param {HTMLElement} host
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
    host.querySelector(".pl-wrap").innerHTML = `<div class="pl-empty-row">首页数据异常</div>`;
    return;
  }

  const wrap = host.querySelector(".pl-wrap");
  wrap.innerHTML = "";

  const head = document.createElement("div");
  head.className = "pl-head";
  head.innerHTML =
    `<span class="pl-title">提示词拼接流水线</span>` +
    `<span class="pl-sub">按 Anima 官方次序自左向右拼接 · 共 ${data.total} 个标签 · ` +
    `点入口直接进入该类目</span>`;
  const badge = document.createElement("span");
  badge.className = "pl-badge";
  badge.textContent = "待完善 …";
  let inc = null;
  badge.onclick = () => opts.onIncomplete?.(inc);
  head.appendChild(badge);
  wrap.appendChild(head);

  const flow = document.createElement("div");
  flow.className = "pl-flow";
  wrap.appendChild(flow);   // 先入 DOM: 下面要靠真实布局量每段的行宽

  // 每段一个站点: 类目标签与入口胶囊分居主轴两侧, **按段交替**
  // (段1 标签在上/入口在下, 段2 反过来 —— 用户定的版式)。
  // 入口沿 X 排开: 段内胶囊是一行, 不换行也不在窄列里竖着堆。
  data.segments.forEach((seg, i) => {
    const station = document.createElement("div");
    station.className = "pl-station" + (i % 2 ? " alt" : "");
    station.style.setProperty("--i", String(i));

    const entries = document.createElement("div");
    entries.className = "pl-entries";
    if (!seg.axes.length) {
      const b = document.createElement("span");
      b.className = "pl-chip empty";
      b.textContent = "库内暂无对应轴";
      b.title = `Anima 官方次序第 ${seg.section} 段「${seg.name}」保留, 库内暂无对应轴`;
      entries.appendChild(b);
    } else {
      seg.axes.forEach((ax) => {
        const chip = document.createElement("button");
        chip.className = "pl-chip";
        chip.type = "button";
        chip.textContent = ax.zh;
        chip.title = `${ax.zh} · ${ax.count} 个标签 / ${ax.slots} 个槽位`;
        // 单击直接进入 —— 不再有"再点一下"的确认卡片 (用户: 那就是个叠在上面的图层)
        chip.onclick = () => opts.onPick?.(ax.id, ax.zh);
        entries.appendChild(chip);
      });
    }

    const label = document.createElement("div");
    label.className = "pl-label";
    label.innerHTML = `<span class="pl-sec">${seg.section}</span>` +
                      `<span class="pl-segname">${seg.name}</span>`;

    const axis = document.createElement("div");
    axis.className = "pl-axis";
    const dot = document.createElement("span");
    dot.className = "pl-dot";

    station.append(axis, dot, label, entries);
    flow.appendChild(station);
  });

  // (不再有"点空白/Esc 收卡片" —— 确认卡片已删, 单击入口直接进)

  (async () => {
    try {
      const r = await fetch("/taglib/api/tag/incomplete", { headers: { Accept: "application/json" } });
      const got = await r.json();
      if (!got?.ok) { badge.textContent = ""; return; }
      inc = got;
      if (got.total > 0) {
        badge.classList.add("hot");
        badge.textContent = `待完善 ${got.total}`;
        const c = got.counts || {};
        badge.title = `未建档武器 ${c.weapon_unregistered || 0} · ` +
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
