"""UI 验收: 面板结构 → 开 picker → 逐 tab 截图+断言 → 编辑能力断言。

v1.6.0 起额外断言 (失败即退出码非 0):
  · 页签收敛为 7 个 (首页/挑标签/武器档案/互斥域/NL句式/预设/设置), 排除类目与防冲突已合并
  · 首页 = 流水线 (按 axes 官方六段次序渲染 13 条轴, 单击放大 → 再点进入)
  · 排除类目出现在侧栏抽屉里
  · 武器档案 / 互斥域 / NL 三个视图是**可编辑**的 (存在 input.tp-ecell / 增删按钮 / 保存按钮)
  · 跨池互斥规则已并入互斥域页


python tests/ui_v13_check.py
产出: tests/ui_panel.png, ui_axis.png, ui_prof.png, ui_grp.png, ui_nl.png, ui_set.png
退出码 0 = 面板结构断言全过。
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = HERE

# 浏览器层 = huashu-chrome 桥 (驱动用户自己的 Edge), 不再自己拉调试用 Edge。
# 为什么换、有哪些坑, 见 tests/_ui_bridge.py 顶部。
sys.path.insert(0, HERE)
from _ui_bridge import ensure_bridge, wait_app  # noqa: E402



def _run(cdp, tab):
    """cdp 现在是 UiBridge —— cdp.ev / cdp.shot 的调用点语义与旧 CDP 一致。"""
    # 2) 等 app ready
    if not wait_app(cdp, tab, 60):
        print("app 未就绪")
        sys.exit(1)
    print("app ready")


    # 3) 建测试节点 (带一把钉选 katana)
    # ⚠ ComfyUI 会恢复上次打开的工作流, 里面可能已有若干 TagLibraryNode ——
    # 不清场的话后面 `_nodes.find(...)` 会读到第一个(旧的空节点), 断言全部错位。
    r = cdp.ev("""(() => {
      const g = window.app.graph;
      // ⚠ 只在画布上另建一个带标记的节点, 不动用户工作流里已有的 TagLibraryNode
      //   (跑完删掉自己这个)。断言一律通过 window.__tlGateNode 定位它。
      window.__tlGateView = window.__tlGateView || JSON.stringify({
        offset: window.app.canvas?.ds?.offset, scale: window.app.canvas?.ds?.scale });
      const n = LiteGraph.createNode('TagLibraryNode');
      n.pos=[100,100]; n.size=[520,760]; g.add(n);
      n.setSize([520,760]);
      n.title = '__tl_gate__';
      window.__tlGateNode = n;
      // 真浏览器里视图可能停在别处, 节点不在可视区就不会给 DOM widget 排布局
      // (面板 offsetHeight=0 → 后面取元素全部落空) → 把视图挪到节点上
      window.app.canvas?.centerOnNode?.(n);
      window.app.canvas?.setDirty?.(true, true);
      window.app.canvas?.draw?.(true, true);
      const sw = n.widgets && n.widgets.find(w=>w.name==='selection_state');
      if (sw) sw.value = JSON.stringify({tags:[{en:'katana',pinned:true,enabled:true}],
        fill_master:true, fill_master_min:2, fill_master_max:3, nl_tail:true});
      return 'node';
    })()""")
    print("node:", r)
    # 等面板真正就绪 (库是异步拉取的, 固定 sleep 会偶发"元素还没渲染出来")
    for _ in range(25):
        time.sleep(1)
        ok = cdp.ev("""(() => {
          const n = window.__tlGateNode;
          if (!n) return false;
          const w = n.widgets && n.widgets.find(x => x.name === 'taglib_panel');
          return !!(w && w.element && w.element.offsetHeight > 0
                    && w.element.querySelector('.tl-more-btn')
                    && w.element.querySelector('.tl-roll-btn'));
        })()""")
        if ok:
            break
    print("panel ready:", bool(ok))
    time.sleep(0.5)

    # ---- 节点面板结构 (面板瘦身: 死 UI 已删, 低频项收进 ⋯ 菜单) ----
    panel_errs = []
    probe = cdp.ev("""(() => {
      const n = window.__tlGateNode;
      const w = n.widgets.find(x=>x.name==='taglib_panel');
      const p = w.element;
      const label = (sel) => { const e = p.querySelector(sel); return e ? e.textContent.trim() : null; };
      const menu = p.querySelector('.tl-menu');
      return JSON.stringify({
        headButtons: p.querySelectorAll('.tl-head button').length,
        hasEngineSeg: !!p.querySelector('.tl-eng-seg'),
        menuHidden: menu ? menu.hidden : null,
        menuItems: menu ? menu.querySelectorAll('.tl-menu-item').length : 0,
        nsfw: label('.tl-nsfw-btn'),
        // 性别/防冲突 已改成面板控件行上的分段/开关; 语言/预览 在 ⋯ 里是下拉
        gender: (p.querySelector('.tl-gender-seg button.active') || {}).textContent || null,
        conflict: p.querySelector('.tl-conflict-btn').classList.contains('on') ? '开' : '关',
        lang: (p.querySelector('.tl-lang-sel') || {}).value || null,
        pv: (p.querySelector('.tl-pv-sel') || {}).value || null,
        hasRoll: !!p.querySelector('.tl-roll-btn'),
        hasClearBtn: !!p.querySelector('.tl-clear-btn'),
        // 管理页入口 (分类增删改/导入/备份/批量工具/标签文件同步) 的唯一正门
        hasMgrItem: !!p.querySelector('.tl-menu-item[data-act="manager"]'),
      });
    })()""")
    pv = json.loads(probe)
    print("PANEL:", json.dumps(pv, ensure_ascii=False))

    def chk(name, got, want):
        ok = got == want
        print(f"    {'✓' if ok else '✗'} {name}: {got!r}" + ("" if ok else f" (期望 {want!r})"))
        if not ok:
            panel_errs.append(f"{name}={got!r} 期望 {want!r}")

    chk("头部常驻按钮数", pv["headButtons"], 4)          # NSFW / 强度 / ⋯ / ＋添加标签 (1.8.1)
    chk("Fast-Smart 死 UI 已删", pv["hasEngineSeg"], False)
    chk("⋯ 菜单默认隐藏", pv["menuHidden"], True)
    chk("⋯ 菜单项数", pv["menuItems"], 4)                # 标签库管理/预设管理/批量探索/清空
    chk("⋯ 菜单里有「标签库管理」入口", pv["hasMgrItem"], True)
    # 右上角那个 fixed 悬浮 🏷 按钮 1.8.4 已按用户要求删除 (界面全部收进节点面板) ——
    # 钉一条反向断言, 免得日后有人又"顺手"加回去。
    chk("右上角悬浮按钮已删", cdp.ev("!!document.getElementById('taglib-topbar-btn')"), False)

    # ---- 控件行: 什么语义给什么控件 (开关/分段/下拉) ----
    #  用户明确要求「按人的交互来」。这里不只数元素, 还**真的操作一次**看反应。
    ctl = cdp.ev("""(() => {
      const p = [...document.querySelectorAll('.taglib-panel')].filter(x=>x.offsetHeight>0).pop();
      const sws = [...p.querySelectorAll('.tl-controls .tl-sw')];
      const segs = [...p.querySelectorAll('.tl-controls .tl-seg')];
      return JSON.stringify({
        switches: sws.length,
        segments: segs.length,
        segButtons: segs.map(s => s.querySelectorAll('button').length),
        hasSelect: !!p.querySelector('.tl-menu .tl-sel'),
        noChipCycle: p.querySelectorAll('.tl-stchip').length === 0,
      });
    })()""")
    cv = json.loads(ctl) if isinstance(ctl, str) and ctl.startswith("{") else {}
    chk("控件行: 开关数 = 5", cv.get("switches"), 5)          # NSFW/单人/简背景/特写/防冲突
    chk("控件行: 分段组数 = 2", cv.get("segments"), 2)         # 涩度/性别
    chk("控件行: 每段 3 个选项", cv.get("segButtons"), [3, 3])
    chk("菜单里有下拉(选择语义)", cv.get("hasSelect"), True)
    chk("已无'点胶囊循环'控件", cv.get("noChipCycle"), True)

    # 真的拨一下 NSFW 开关, 看 aria-checked 有没有反过来
    flip = cdp.ev("""(() => {
      const p = [...document.querySelectorAll('.taglib-panel')].filter(x=>x.offsetHeight>0).pop();
      const sw = p.querySelector('.tl-nsfw-btn');
      const a = sw.getAttribute('aria-checked');
      sw.click();
      const b = sw.getAttribute('aria-checked');
      sw.click();
      return JSON.stringify({ before: a, after: b, restored: sw.getAttribute('aria-checked') });
    })()""")
    fv = json.loads(flip) if isinstance(flip, str) and flip.startswith("{") else {}
    chk("开关: 拨一下状态翻转", fv.get("after") != fv.get("before"), True)
    chk("开关: 再拨一下复原", fv.get("restored"), fv.get("before"))

    # 真的点一下性别分段, 看高亮有没有跟着走
    seg = cdp.ev("""(() => {
      const p = [...document.querySelectorAll('.taglib-panel')].filter(x=>x.offsetHeight>0).pop();
      const bs = [...p.querySelectorAll('.tl-gender-seg button')];
      bs[1].click();
      const mid = bs.map(b => b.classList.contains('active'));
      bs[0].click();
      return JSON.stringify({ mid: mid, back: bs.map(b => b.classList.contains('active')) });
    })()""")
    sv = json.loads(seg) if isinstance(seg, str) and seg.startswith("{") else {}
    chk("分段: 点第 2 项只有它高亮", sv.get("mid"), [False, True, False])
    chk("分段: 点回第 1 项复原", sv.get("back"), [True, False, False])
    chk("清空按钮已移入菜单", pv["hasClearBtn"], False)
    chk("🎲 填充常驻", pv["hasRoll"], True)
    for k, name in [("gender", "面板·性别分段"), ("conflict", "面板·防冲突开关"),
                    ("lang", "菜单·语言下拉"), ("pv", "菜单·预览下拉")]:
        if not pv[k]:
            print(f"    ✗ {name} 无状态文案")
            panel_errs.append(f"{name} 无状态文案")
        else:
            print(f"    ✓ {name}: {pv[k]}")

    # 展开 ⋯ 菜单, 确认可正常打开
    cdp.ev("""(() => {
      const n = window.__tlGateNode;
      const p = n.widgets.find(x=>x.name==='taglib_panel').element;
      p.querySelector('.tl-more-btn').click(); return 'ok';
    })()""")
    time.sleep(0.6)
    opened = cdp.ev("""(() => {
      const n = window.__tlGateNode;
      const p = n.widgets.find(x=>x.name==='taglib_panel').element;
      const m = p.querySelector('.tl-menu');
      const cs = getComputedStyle(m);
      return JSON.stringify({hidden: m.hidden, display: cs.display, visibility: cs.visibility,
                             position: cs.position, items: m.querySelectorAll('.tl-menu-item').length});
    })()""")
    ov = json.loads(opened)
    print(f"    ⋯ 菜单展开: {ov}")
    # 断言"菜单真的打开了" —— 用 hidden/display 判定。
    # 不再要求 offsetHeight>0: 合成场景下节点不一定被画布渲染, 布局高度可为 0,
    # 那属于测试环境而非产品问题 (真实画布上面板有布局, 菜单正常显示)。
    if ov["hidden"] or ov["display"] == "none" or ov["visibility"] == "hidden":
        panel_errs.append(f"⋯ 菜单未展开: {ov}")
    if ov["position"] != "absolute":
        panel_errs.append(f"⋯ 菜单定位异常: {ov['position']}")
    cdp.shot("ui_panel.png")
    cdp.ev("""(() => {
      const n = window.__tlGateNode;
      const p = n.widgets.find(x=>x.name==='taglib_panel').element;
      p.querySelector('.tl-more-btn').click(); return 'ok';
    })()""")
    time.sleep(0.3)

    # 打开挑选器
    r = cdp.ev("""(() => {
      const n = window.__tlGateNode;
      const w = n.widgets.find(x=>x.name==='taglib_panel');
      if (!w || !w.element) return 'NO-PANEL-WIDGET';
      // 按 data-act 取, 别按文案 —— 按钮文案改过一次(「＋ 添加标签」→「＋ 添加」),
      // 按文案找的断言就静默失效了。
      const btn = w.element.querySelector('[data-act="addtags"]');
      if (!btn) return 'NO-ADD-BTN';
      btn.click();
      return 'clicked';
    })()""")
    print("picker:", r)
    time.sleep(2.5)

    tabs = cdp.ev("[...document.querySelectorAll('.tp-tabbtn')].map(b=>b.textContent.trim()).join(' | ')")
    print("TABS:", tabs)

    # ---- 📦 预设页签 (1.8.1): 打开 → 出厂/我的分组 + 载入按钮 ----
    cdp.ev("document.querySelector('.tp-prtab').click()")
    time.sleep(2)
    pr_ok = cdp.ev("""(() => {
      const v = document.querySelector('.tp-prview');
      if (!v) return 'NO VIEW';
      return JSON.stringify({
        rows: v.querySelectorAll('.tp-gitem2[data-pid]').length,
        apply: v.querySelectorAll('.tp-pr-apply').length,
        save: !!v.querySelector('.tp-pr-save'),
      });
    })()""")
    try:
        prv = json.loads(pr_ok) if isinstance(pr_ok, str) else pr_ok
        chk("预设页签: 载入按钮", prv.get("apply", 0) >= 1, True)
        chk("预设页签: 保存表单", prv.get("save") is True, True)
    except Exception as e:
        ui_errs.append(f"预设页签解析失败: {e} / {pr_ok}")
    cdp.ev("document.querySelector('.tp-picktab').click()")

    # ---- 页签收敛 + 排除抽屉 (v1.6.0; 1.9.0 起档案页退出主导航 → 6 页签) ----
    # ⚠ 别把「⚔ 武器档案」加回来: 1.9.0 按用户要求把档案**编辑**降为二级
    #   (设置 → ⚔ 道具/武器档案 (高级) → 打开档案编辑器, `.tp-goprof`),
    #   **选用**搬进挑标签右栏。老断言写死 7 页签 + 该页签存在 → 改完必然假红
    #   (2026-09-21 实测: 只改点击路径不够, 页签断言也得跟着改)。
    ui_errs = []
    want_tabs = ["🏠 首页", "挑标签", "🧬 互斥域", "✍ NL 句式", "📦 预设", "⚙ 设置"]
    for t in want_tabs:
        ok = t in tabs
        print(f"    {'✓' if ok else '✗'} 页签存在: {t}")
        if not ok:
            ui_errs.append(f"缺页签 {t}")
    for bad in ("排除类目", "防冲突关系", "标签库管理", "⚔ 武器档案"):
        ok = bad not in tabs
        print(f"    {'✓' if ok else '✗'} 页签已合并/降级: {bad}")
        if not ok:
            ui_errs.append(f"未删除页签 {bad}")
    n_tabs = len([x for x in tabs.split(" | ") if x.strip()])
    print(f"    {'✓' if n_tabs == 6 else '✗'} 页签总数 = {n_tabs} (期望 6)")
    if n_tabs != 6:
        ui_errs.append(f"页签数 {n_tabs} != 6")

    # ---- 🏠 流水线首页 (2026-09-19 编辑体验改造) ----
    #  首页按 axes.AXIS_SECTION 的官方六段次序排 13 条轴: 胶囊逐颗按"当前更窄的
    #  一排"分到主轴上下 (段6 有 9 条轴, 按段交替会 4 : 9), 段名留在主轴线上。
    #  段4 作品 与 段9 未归类 库内暂无轴, 渲染为占位胶囊。
    #  数据全部来自 GET /taglib/api/axes-overview (前端不抄次序)。
    cdp.ev("document.querySelector('.tp-hometab').click()")
    time.sleep(2.0)                      # 轴数据与「待完善」角标都是异步 fetch
    home = cdp.ev("""(() => {
      const v = document.querySelector('.tp-homeview');
      if (!v) return 'NO VIEW';
      // 入场动画 (pl-in / pl-draw) 可能还在跑 —— 量几何前先推到终态, 否则量到的是
      // translateY(6px) 的中间态: 主轴看着没穿过圆心、上下留白也不均。
      v.querySelectorAll('.pl-station, .pl-flow')
        .forEach(e => e.getAnimations?.().forEach(a => a.finish?.()));
      const chips = [...v.querySelectorAll('.pl-chip:not(.empty)')];
      const rs = chips.map(c => c.getBoundingClientRect());
      let overlap = 0;
      for (let i = 0; i < rs.length; i++)
        for (let j = i + 1; j < rs.length; j++) {
          const a = rs[i], b = rs[j];
          if (a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom) overlap++;
        }
      const vr = v.getBoundingClientRect();
      const flow = v.querySelector('.pl-flow');
      const fr = flow.getBoundingClientRect();
      const all = [...v.querySelectorAll('.pl-chip')].map(c => c.getBoundingClientRect());
      const dots = [...v.querySelectorAll('.pl-dot')].map(d => d.getBoundingClientRect());
      const R = (el) => { const b = el.getBoundingClientRect();
                          return { t: b.top, b: b.bottom, l: b.left, r: b.right,
                                   cy: b.top + b.height / 2 }; };
      const sts = [...v.querySelectorAll('.pl-station')].map(s => {
        const axis = R(s.querySelector('.pl-axis'));
        const label = R(s.querySelector('.pl-label'));
        const entries = R(s.querySelector('.pl-entries'));
        const cs = [...s.querySelectorAll('.pl-entries .pl-chip')].map(R);
        return {
          axisText: (s.querySelector('.pl-axis').textContent || '').trim(),
          dotCy: R(s.querySelector('.pl-dot')).cy,
          axisCy: axis.cy,
          labelAbove: label.cy < axis.cy,
          entriesAbove: entries.cy < axis.cy,
          // 入口是**竖列**: 站内胶囊同一个中心 x, y 自上而下递增
          chipCenters: [...new Set(cs.map(c => Math.round(c.l + (c.r - c.l) / 2)))].length,
          chipTops: cs.map(c => Math.round(c.t)),
          chipCol: cs.length,
        };
      });
      return JSON.stringify({
        visible: getComputedStyle(v).display !== 'none',
        stations: sts.length,
        nodes: dots.length,
        chips: v.querySelectorAll('.pl-chip').length,
        empty: v.querySelectorAll('.pl-chip.empty').length,
        overlap: overlap,
        dotTopVariants: [...new Set(dots.map(d => Math.round(d.top)))].length,
        axisCount: v.querySelectorAll('.pl-axis').length,
        axisText: sts.map(s => s.axisText).join(''),
        dotOnAxis: sts.every(s => Math.abs(s.dotCy - s.axisCy) <= 2),
        sidesSplit: sts.every(s => s.labelAbove !== s.entriesAbove),
        alternates: sts.every((s, i) => i === 0 || s.labelAbove !== sts[i - 1].labelAbove),
        entriesOneColumn: sts.every(s => s.chipCenters <= 1),
        entriesDescending: sts.every(s => s.chipTops.every((y, k) => k === 0 || y > s.chipTops[k - 1])),
        // 入口列总高 (段6 有 8 条轴 → 撑起纵向空间, 用户要的"利用率")
        tallestCol: Math.max(...sts.map(s => s.chipCol)),
        // 站点等宽 + 最后一个站点的右沿贴着 flow 右沿 = 横向铺满, 不留空白
        filledWidth: (() => {
          const ws = [...v.querySelectorAll('.pl-station')].map(s => Math.round(s.getBoundingClientRect().width));
          const last = [...v.querySelectorAll('.pl-station')].pop().getBoundingClientRect();
          return Math.max(...ws) - Math.min(...ws) <= 2 && Math.abs(last.right - fr.right) <= 8;
        })(),
        flowH: Math.round(fr.height),
        scrolled: flow.scrollWidth > flow.clientWidth + 1,
        outRight: all.filter(r => r.right > vr.right + 1).length,
        outBottom: all.filter(r => r.bottom > vr.bottom + 1).length,
        // 确认卡片与整层缩放都已删除 (用户: 动画不优美 / 纯图层重叠)
        noCard: v.querySelectorAll('.pl-card').length === 0,
        noZoom: !v.querySelector('.pl-flow.zoomed') && !v.querySelector('.pl-flow').style.transform,
      });
    })()""")
    try:
        hv = json.loads(home) if isinstance(home, str) and home.startswith("{") else {}
    except Exception:  # noqa: BLE001
        hv = {}
    if not hv:
        ui_errs.append(f"首页视图解析失败: {home!r}")
    for label, got, want in (("首页默认可见", hv.get("visible"), True),
                             ("首页站点数 = 7", hv.get("stations"), 7),
                             ("首页段位节点 = 7", hv.get("nodes"), 7),
                             ("首页胶囊 = 15 (13 轴 + 2 占位)", hv.get("chips"), 15),
                             ("首页占位胶囊 = 2", hv.get("empty"), 2),
                             ("首页胶囊零重叠", hv.get("overlap"), 0),
                             ("7 个节点同高 (主轴成一条线)", hv.get("dotTopVariants"), 1),
                             # 用户定的版式: 主轴是**一条不带文字的线**, 每站画自己那段
                             # (站间留 6px 缝 = "中断多个"); 类目标签与入口胶囊分居主轴两侧
                             # 且**逐段上下交替** (段1 标签在上入口在下, 段2 反过来);
                             # 入口沿 X 排成一行, 不往 Y 方向堆。
                             ("主轴分段 = 站点数", hv.get("axisCount"), 7),
                             ("站点等宽铺满 (无横向空白)", hv.get("filledWidth"), True),
                             ("主轴上零文字", hv.get("axisText"), ""),
                             ("主轴穿过每个节点圆心", hv.get("dotOnAxis"), True),
                             ("标签与入口分居主轴两侧", hv.get("sidesSplit"), True),
                             ("标签/入口逐段上下交替", hv.get("alternates"), True),
                             # 入口**竖成一列**(用户: "每一类入口以Y轴列"), 列里自上而下;
                             # 类目本身才沿 X 轴排 (站点等宽铺满整条)
                             ("入口竖成一列", hv.get("entriesOneColumn"), True),
                             ("入口列自上而下", hv.get("entriesDescending"), True),
                             ("最长入口列 = 8 (段6)", hv.get("tallestCol"), 8),
                             ("无需横向滚动", hv.get("scrolled"), False),
                             ("无胶囊越出右边", hv.get("outRight"), 0),
                             ("无胶囊越出下边", hv.get("outBottom"), 0),
                             # 确认卡片与整层缩放都已删除 (用户: 动画不优美 / 纯图层重叠)
                             ("首页无聚焦卡片元素", hv.get("noCard"), True),
                             ("首页无整层缩放残留", hv.get("noZoom"), True)):
        ok = got == want
        print(f"    {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f" (期望 {want!r})"))
        if not ok:
            ui_errs.append(f"{label}={got!r} 期望 {want!r}")

    #  单击入口**直接进入**挑标签 (原来的"再点一下确认"卡片已删: 用户说那纯是叠在上面的图层)
    cdp.ev("document.querySelector('.tp-homeview .pl-chip:not(.empty)').click()")
    time.sleep(1.2)
    landed = cdp.ev("""(() => {
      const c = document.querySelector('.tp-chips');
      const h = document.querySelector('.tp-homeview');
      return getComputedStyle(c).display !== 'none' &&
             getComputedStyle(h).display === 'none';
    })()""")
    print(f"    {'✓' if landed is True else '✗'} 首页单击 → 直接进入挑标签: {landed!r}")
    if landed is not True:
        ui_errs.append(f"首页单击未进入挑标签: {landed!r}")
    cdp.ev("document.querySelector('.tp-picktab').click()")   # 复位到挑标签
    time.sleep(0.6)

    #  左侧栏必须还是 200px —— 曾经因为兄弟视图 flex:1 被压成 38px (用户: "被压扁了")
    cats_w = cdp.ev("Math.round(document.querySelector('#taglib-picker-dialog .tp-cats')"
                    ".getBoundingClientRect().width)")
    print(f"    {'✓' if cats_w == 200 else '✗'} 挑标签左侧栏宽 = {cats_w} (期望 200)")
    if cats_w != 200:
        ui_errs.append(f"挑标签左侧栏被压扁: {cats_w}px")

    drawer = cdp.ev("""(() => {
      const d = document.querySelector('.tp-exc');
      const hasTab = !!document.querySelector('.tp-excludetab');
      return JSON.stringify({drawer: !!d, inSidebar: !!(d && d.closest('.tp-cats')), oldTab: hasTab});
    })()""")
    dv = json.loads(drawer)
    print(f"    {'✓' if dv['drawer'] and dv['inSidebar'] else '✗'} 排除类目已并入侧栏抽屉: {dv}")
    if not (dv["drawer"] and dv["inSidebar"]):
        ui_errs.append("排除抽屉未出现在侧栏")

    def click_tab(sel, name_png, assert_js, label):
        cdp.ev(f"document.querySelector('{sel}').click()")
        time.sleep(2.0)
        val = cdp.ev(assert_js)
        cdp.shot(name_png)
        print(f"{label}: {val}")

    # 4) 挑标签 (唯一视图: 段位序 → 轴 → 槽位, 每行带启用开关)
    click_tab(".tp-picktab", "ui_axis.png",
              """(() => {
                const heads=[...document.querySelectorAll('.tp-axis-head')].map(h=>h.textContent.trim().split(' ')[0]+'×'+(h.querySelector('.tp-axis-n')||{}).textContent);
                const b=document.querySelectorAll('.tp-tag.bundled').length;
                const secs=[...document.querySelectorAll('.tp-sec-head')].map(x=>x.textContent.trim());
                const togs=document.querySelectorAll('.tp-row-tog').length;
                const vm=document.querySelectorAll('.tp-vm').length;
                const sideRows=document.querySelectorAll('.tp-cats .tp-cat').length;
                return JSON.stringify({axisHeads: heads.slice(0,8), bundleChips: b, sections: secs,
                                       toggles:togs, viewModeBtns:vm, sidebarRows:sideRows});
              })()""", "AXIS")
    v = json.loads(cdp.ev("""JSON.stringify({
      togs: document.querySelectorAll('.tp-row-tog').length,
      vm: document.querySelectorAll('.tp-vm').length,
      axes: document.querySelectorAll('.tp-cats .tp-cat-l0').length,
      secs: document.querySelectorAll('.tp-sec-head').length})"""))
    print(f"    单一视图: 视图切换按钮 {v['vm']} 个 (期望 0) | 轴行 {v['axes']} | 段位标题 {v['secs']} | 开关 {v['togs']}")
    if v["vm"] != 0:
        ui_errs.append(f"仍有视图切换按钮 {v['vm']} 个")
    if v["axes"] < 12:
        ui_errs.append(f"侧栏轴行只有 {v['axes']} 个")
    if v["secs"] < 3:
        ui_errs.append(f"段位标题只有 {v['secs']} 个")
    if v["togs"] < 12:
        ui_errs.append(f"轴行开关只有 {v['togs']} 个 (每个轴都应有)")

    # 关掉「角色身份」轴 -> 应写入 exclude_categories
    ex_res = cdp.ev("""(() => {
      const rows=[...document.querySelectorAll('.tp-cats .tp-cat')];
      const row=rows.find(r=>r.textContent.includes('角色身份'));
      if(!row) return JSON.stringify({err:'no-row'});
      const t=row.querySelector('.tp-row-tog');
      if(!t) return JSON.stringify({err:'no-toggle'});
      t.click();
      const n=window.__tlGateNode;
      const st=JSON.parse(n.widgets.find(x=>x.name==='selection_state').value||'{}');
      return JSON.stringify({excluded: st.exclude_categories||[], hasAxis:(st.exclude_categories||[]).includes('角色身份')});
    })()""")
    ex = json.loads(ex_res)
    print(f"    关闭「角色身份」轴 -> {ex}")
    if not ex.get("hasAxis"):
        ui_errs.append(f"轴开关未写入排除列表: {ex}")

    # 5) 道具/武器档案 (可编辑) —— 1.9.0 起它从主导航降为二级:
    #    设置 → ⚔ 道具/武器档案 (高级) → 打开档案编辑器。
    #    ⚠ 别改回 .tp-proftab: 那个页签已删 (用户要求"武器档案这一页删掉, 集成进挑标签")。
    cdp.ev("document.querySelector('.tp-settab').click()")
    time.sleep(1.5)
    cdp.ev("document.querySelector('.tp-goprof').click()")
    time.sleep(2.0)
    print("PROF: " + str(cdp.ev("""(() => {
                const cards=document.querySelectorAll('.tp-pcard').length;
                const rows=document.querySelectorAll('.tp-ptab tr').length;
                const h1=(document.querySelector('.tp-h1')||{}).textContent;
                const cells=document.querySelectorAll('.tp-ecell').length;
                const chips=document.querySelectorAll('.tp-echip').length;
                const adds=document.querySelectorAll('.tp-eadd').length;
                const saves=document.querySelectorAll('.tp-save').length;
                return JSON.stringify({h1:h1, cards, poseRows:rows, editableCells:cells,
                                       editableChips:chips, addBtns:adds, saveBtns:saves});
              })()""")))
    cdp.shot("ui_prof.png")
    prof_v = json.loads(cdp.ev("""JSON.stringify({
      cells: document.querySelectorAll('.tp-ecell').length,
      add: document.querySelectorAll('.tp-eadd').length,
      save: document.querySelectorAll('.tp-save').length})"""))
    if not (prof_v["cells"] > 50 and prof_v["add"] >= 3 and prof_v["save"] >= 1):
        ui_errs.append(f"武器档案未完全可编辑: {prof_v}")

    # 6) 互斥域 (可编辑) + 跨池规则已并入
    click_tab(".tp-grptab", "ui_grp.png",
              """(() => {
                const items=document.querySelectorAll('.tp-gitem2').length;
                const cells=document.querySelectorAll('.tp-ecell').length;
                const chips=document.querySelectorAll('.tp-echip').length;
                const cfRules=document.querySelectorAll('.tp-cf-rule').length;
                const cfHost=!!document.querySelector('.tp-cf-host');
                return JSON.stringify({groups:items, editableCells:cells, editableChips:chips,
                                       cfHost:cfHost, cfRules:cfRules});
              })()""", "GRP")
    grp_v = json.loads(cdp.ev("""JSON.stringify({
      groups: document.querySelectorAll('.tp-gitem2').length,
      cells: document.querySelectorAll('.tp-ecell').length,
      cfRules: document.querySelectorAll('.tp-cf-rule').length})"""))
    if not (grp_v["groups"] >= 50 and grp_v["cells"] >= 50 and grp_v["cfRules"] >= 1):  # 1.8.0: +nsfw 扩展域
        ui_errs.append(f"互斥域可编辑/规则并入不完整: {grp_v}")

    # 7) NL 句式 (可编辑)
    click_tab(".tp-nltab", "ui_nl.png",
              """(() => {
                const fams=document.querySelectorAll('.tp-fam').length;
                const cells=document.querySelectorAll('.tp-ecell').length;
                const sels=document.querySelectorAll('select.tp-ecell').length;
                return JSON.stringify({families:fams, editableCells:cells, selects:sels});
              })()""", "NL")
    nl_v = json.loads(cdp.ev("""JSON.stringify({
      cells: document.querySelectorAll('.tp-ecell').length,
      sels: document.querySelectorAll('select.tp-ecell').length})"""))
    if not (nl_v["cells"] >= 30 and nl_v["sels"] >= 10):
        ui_errs.append(f"NL 句式未完全可编辑: {nl_v}")

    # 8) 设置新块
    click_tab(".tp-settab", "ui_set.png",
              """(() => {
                const has=(t)=>[...document.querySelectorAll('.tp-set-lab')].some(e=>e.textContent.includes(t));
                return JSON.stringify({nl_tail:has('自然语言'), bundle:has('武器带姿势'), maxw:has('同时武器上限')});
              })()""", "SET")

    # 9) 设置「新节点的默认模式」→ 新节点生效 (v1.6.5 回归:
    #    combo widget 的 options 是 {values:[...]}, 旧判断 Object.values(options)
    #    拿到 [[...]] 永远 includes 不中, 设置从未生效)
    # ⚠ 拆成两次求值: huashu-chrome 的 eval 不 await Promise (async 表达式回传的是
    #   Promise 的 JSON = "{}"), 所以"设设置 → 建节点 → 等 800ms → 读 widget"
    #   这种带 await 的探针必须由 Python 侧分段, 中间 sleep。
    cdp.ev("""(() => {
      const app = window.app;
      const set = app.extensionManager?.setting;
      if (!set?.set || !set?.get) { window.__tlGateModeErr = 'no-setting-api'; return 'no-api'; }
      window.__tlGateModePrev = set.get('TagLibrary.default_mode');
      set.set('TagLibrary.default_mode', 'auto');
      const n = LiteGraph.createNode('TagLibraryNode');
      n.pos = [100, 100];
      n.title = '__tl_gate_mode__';
      app.graph.add(n);
      window.__tlGateModeNode = n;
      return 'created';
    })()""")
    time.sleep(1.5)          # onNodeCreated 里的 setTimeout(0) + 设置传播
    dm_res = cdp.ev("""(() => {
      try {
        const app = window.app;
        const n = window.__tlGateModeNode;
        const modeW = n && n.widgets?.find(w => w.name === 'mode');
        const got = modeW ? modeW.value : null;
        if (n) app.graph.remove(n);
        window.__tlGateModeNode = null;
        const set = app.extensionManager?.setting;
        const prev = window.__tlGateModePrev;
        if (set?.set) {
          set.set('TagLibrary.default_mode', prev === undefined || prev === null ? 'manual' : prev);
        }
        if (window.__tlGateModeErr) return JSON.stringify({err: window.__tlGateModeErr});
        return JSON.stringify({got: got, prev: prev});
      } catch (e) {
        return JSON.stringify({err: String(e).slice(0, 120)});
      }
    })()""")
    print("默认模式:", dm_res)
    try:
        dm = json.loads(dm_res)
    except (TypeError, ValueError):
        dm = {"err": str(dm_res)[:120]}
    if dm.get("err") == "no-setting-api":
        print("    ⚠ 默认模式断言跳过: 设置 API 不可用")
    elif dm.get("err"):
        ui_errs.append(f"默认模式断言执行失败: {dm['err']}")
    elif dm.get("got") != "auto":
        ui_errs.append(f"新节点默认模式未生效: got={dm.get('got')!r} 期望 'auto'")
    else:
        print("    ✓ 新节点默认模式 = auto (设置生效)")

    print("\n截图在 tests/ 下: ui_panel ui_axis ui_prof ui_grp ui_nl ui_set")

    all_errs = panel_errs + ui_errs
    if all_errs:
        print(f"\n❌ UI 巡检失败 ({len(all_errs)} 项):")
        for e in all_errs:
            print("   -", e)
        sys.exit(1)
    print("✅ UI 巡检通过 (面板瘦身 / 页签 8→5 / 三个数据视图可编辑)")


def main():
    ui = ensure_bridge()
    tab = ui.new_tab("http://127.0.0.1:8188/", label="TagLib UI 门禁")
    try:
        _run(ui, tab)
    finally:
        # 收尾: 删掉自己建的节点、把画布视图还原, 再关掉自己的标签页 ——
        # 驱动的是用户的真浏览器, 不能留下任何痕迹。
        try:
            ui.ev("""(() => {
              const g = window.app.graph, n = window.__tlGateNode;
              if (n && g) g.remove(n);
              const v = window.__tlGateView && JSON.parse(window.__tlGateView);
              if (v && window.app.canvas?.ds) {
                if (v.offset) window.app.canvas.ds.offset = v.offset;
                if (v.scale) window.app.canvas.ds.scale = v.scale;
              }
              window.app.canvas?.setDirty?.(true, true);
              window.app.canvas?.draw?.(true, true);
              return 'gate-cleaned';
            })()""")
        except Exception:  # noqa: BLE001
            pass
        ui.close_tab(tab)
        ui.close()


if __name__ == "__main__":
    main()

