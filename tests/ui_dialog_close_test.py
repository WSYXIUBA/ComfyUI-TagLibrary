"""弹层开/关功能测试 —— 每个可打开的界面都要能关掉。

    python tests/ui_dialog_close_test.py

背景 (2026-09-19): 用户报"很多功能界面打开都关不掉了"。本测试把每个可打开的
弹层/浮层走一遍「打开 → 断言已打开 → 关闭 → 断言真的关掉了」, 逐个报结果。

⚠ 本脚本用项目自带的 CDP 实例 (`C:\\EdgeForHermes` profile, 端口 9222) —— 这是
  门禁既有的自动化通道。它不碰用户的日常浏览器 (那里有用户自己的工作流)。
"""

from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _ui_bridge import ensure_bridge  # noqa: E402  浏览器层 = huashu-chrome 桥

FAILS: list[str] = []


def check(name: str, got, want, extra: str = "") -> None:
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {name}: {got!r}" + ("" if ok else f" (期望 {want!r})"))
    if not ok:
        FAILS.append(f"{name}={got!r} 期望 {want!r} {extra}")


def _run(cdp, tab) -> int:
    """cdp 现在是 UiBridge (huashu-chrome 桥)。缓存靠 URL 上的 ?dlg= 时间戳绕开 ——
    桥这一层没有 Network.setCacheDisabled。"""
    for _ in range(30):
        time.sleep(2)
        if cdp.ev("!!(window.app && window.app.graph)"):
            break
    print("app ready")

    # 建节点 + 等面板
    cdp.ev("""(() => {
      const g = window.app.graph;
      // ⚠ 只在画布上另建一个带标记的节点, 不动用户工作流里已有的 TagLibraryNode
      //   (跑完删掉自己这个)。断言一律通过 window.__tlGateNode 定位它。
      window.__tlGateView = window.__tlGateView || JSON.stringify({
        offset: window.app.canvas?.ds?.offset, scale: window.app.canvas?.ds?.scale });
      const n = LiteGraph.createNode('TagLibraryNode');
      n.pos=[60,60]; n.size=[520,780]; g.add(n); n.setSize([520,780]);
      n.title = '__tl_gate__';
      window.__tlGateNode = n;
      // 真浏览器里视图可能停在别处, 节点不在可视区就不会给 DOM widget 排布局
      // (面板 offsetHeight=0 → 后面取元素全部落空) → 把视图挪到节点上
      window.app.canvas?.centerOnNode?.(n);
      window.app.canvas?.setDirty?.(true, true); window.app.canvas?.draw?.(true, true);
      return 1;
    })()""")
    for _ in range(25):
        time.sleep(1)
        if cdp.ev("""(() => {
          const n = window.__tlGateNode;
          const w = n && n.widgets && n.widgets.find(x => x.name === 'taglib_panel');
          return !!(w && w.element && w.element.offsetHeight > 0
                    && w.element.querySelector('.tl-more-btn'));
        })()"""):
            break
    time.sleep(1)
    # 注入取面板的辅助函数 (只取可见的那份克隆)
    # ⚠ 必须是**单个表达式**: 桥的 eval 会把它包进 (...) 求值, 带顶层分号的多语句
    #   (老代码写的 `...; 1`) 会直接语法错。
    cdp.ev("""(() => {
      window.__tlp = () => [...document.querySelectorAll('.taglib-panel')]
        .filter(x => x.offsetHeight > 0).pop();
      return 1;
    })()""")
    check("面板可用", cdp.ev("!!window.__tlp()"), True)

    def js_open(sel: str) -> str:
        return f"(() => {{ const b = window.__tlp().querySelector('{sel}'); if (!b) return 'NO-BTN'; b.click(); return 'ok'; }})()"

    def js_vis(expr: str) -> str:
        return f"(() => {{ const e = {expr}; if (!e) return 'NO-EL'; return !e.hidden && getComputedStyle(e).display !== 'none'; }})()"

    # ⚠ 关闭判据必须是"点它自己的关闭控件", 不能拿 Escape 糊 —— 面板的 Esc 处理挂在
    #   container 上 (见 taglibrary.js 的 container.addEventListener("keydown")),
    #   往 document 上派发根本到不了它, 会造出一堆假失败。第一版就踩了这个坑。
    def force_open_menu() -> None:
        cdp.ev("""(() => { const p = window.__tlp();
                    const m = p.querySelector('.tl-menu');
                    if (m.hidden) p.querySelector('.tl-more-btn').click(); return 1; })()""")

    def esc_on_panel() -> None:
        cdp.ev("""window.__tlp().dispatchEvent(
                    new KeyboardEvent('keydown', {key:'Escape', bubbles:true})); 1""")

    # ---------------------------------------------------------------- 1. 面板 ⋯ 菜单
    print("\n[1] 面板 ⋯ 更多菜单")
    force_open_menu(); time.sleep(0.6)
    check("⋯ 已打开", cdp.ev(js_vis("window.__tlp().querySelector('.tl-menu')")), True)
    cdp.ev(js_open(".tl-more-btn")); time.sleep(0.5)
    check("再点 ⋯ 可关闭", cdp.ev(js_vis("window.__tlp().querySelector('.tl-menu')")), False)

    force_open_menu(); time.sleep(0.5)
    esc_on_panel(); time.sleep(0.5)
    check("Esc 可关闭 ⋯ 菜单", cdp.ev(js_vis("window.__tlp().querySelector('.tl-menu')")), False)

    force_open_menu(); time.sleep(0.5)
    cdp.ev("""(() => { const m = window.__tlp().querySelector('.tl-menu');
                 (m.querySelector('.tl-menu-sec') || m.firstElementChild)
                   ?.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true})); return 1; })()""")
    time.sleep(0.5)
    check("点菜单内分区标题不误关", cdp.ev(js_vis("window.__tlp().querySelector('.tl-menu')")), True)

    force_open_menu(); time.sleep(0.4)
    cdp.ev("""(() => { const p = window.__tlp();
                 p.querySelector('.tl-toolbar')?.dispatchEvent(
                   new PointerEvent('pointerdown', {bubbles:true})); return 1; })()""")
    time.sleep(0.5)
    check("点面板别处可关闭 ⋯ 菜单", cdp.ev(js_vis("window.__tlp().querySelector('.tl-menu')")), False)

    # ---------------------------------------------------------------- 2. 挑选器
    print("\n[2] 挑选器 (＋ 添加)")
    # ⚠ 判"关掉了"要看**是否还开着** (dialog[open]), 不能只看 DOM 里有没有节点 ——
    #   关掉后节点是收尾逻辑删的, 两件事要分开断言 (2026-09-19: Edge 后台标签页
    #   不派发 dialog 的 close 事件, 收尾一度全靠它, 节点就永远留着)。
    PICK_OPEN = "!!document.querySelector('dialog[open]#taglib-picker-dialog')"
    PICK_LEFT = "!!document.querySelector('#taglib-picker-dialog')"
    print("    open:", cdp.ev(js_open(".tl-btn.primary")))
    time.sleep(2.5)
    check("挑选器已打开", cdp.ev(PICK_OPEN), True)
    cdp.ev("document.querySelector('.tp-cancel')?.click(); 1")
    time.sleep(1.2)
    check("「取消」可关闭挑选器", cdp.ev(PICK_OPEN), False)
    check("挑选器 DOM 已回收 (不靠 close 事件)", cdp.ev(PICK_LEFT), False)

    cdp.ev(js_open(".tl-btn.primary")); time.sleep(2.5)
    cdp.ev("document.querySelector('.tp-close2')?.click(); 1")
    time.sleep(1.2)
    check("「✕ 关闭」可关闭挑选器", cdp.ev(PICK_OPEN), False)
    check("✕ 关闭后 DOM 也回收", cdp.ev(PICK_LEFT), False)

    # ---------------------------------------------------------------- 3. 面板内的独立弹层
    #  逐个: 记录浮层数 → 打开 → 再数 → 点它自己的关闭控件 → 再数。
    #  只要"关闭后仍比打开前多", 就是用户说的"打开关不掉"。
    print("\n[3] 面板内的独立弹层 (开 → 关 → 有没有回收)")
    COUNT = """(() => [...document.querySelectorAll('body > div, body > dialog')]
                 .filter(e => {
                   const s = getComputedStyle(e);
                   return s.position === 'fixed' && s.display !== 'none'
                          && s.visibility !== 'hidden' && e.offsetHeight > 0;
                 }).length)()"""

    def close_topmost() -> str:
        return cdp.ev("""(() => {
          const layers = [...document.querySelectorAll('body > div, body > dialog')]
            .filter(e => { const s = getComputedStyle(e);
              return s.position === 'fixed' && s.display !== 'none'
                     && s.visibility !== 'hidden' && e.offsetHeight > 0; });
          const top = layers[layers.length - 1];
          if (!top) return 'NO-LAYER';
          const btns = [...top.querySelectorAll('button, [role=button]')];
          const b = btns.find(x => /^(✕|×|关闭|取消|Close|Cancel)/.test(x.textContent.trim()))
                 || btns[btns.length - 1];
          if (!b) return 'NO-CLOSE-BTN:' + btns.length;
          // ⚠ 关闭控件必须落在视口内 —— 弹层内容长、关闭按钮在滚动区底部时,
          //   用户不滚到底就关不掉, 体感就是"打开了关不掉" (2026-09-19 实锤:
          //   预设管理弹层的「关闭」在 y=1510, 而视口只有 1308)。
          const r = b.getBoundingClientRect();
          const inView = r.top >= 0 && r.bottom <= innerHeight
                         && r.left >= 0 && r.right <= innerWidth;
          b.click();
          return JSON.stringify({how: 'clicked:' + b.textContent.trim().slice(0, 10),
                                 inView, btnTop: Math.round(r.top), vh: innerHeight});
        })()""")

    def parse_close(raw) -> dict:
        try:
            return json.loads(raw) if isinstance(raw, str) and raw.startswith("{") else {"how": raw}
        except Exception:  # noqa: BLE001
            return {"how": raw}

    for label, opener in (
        ("批量探索", ".tl-menu-item[data-act='explorer']"),
        ("吸收器", "[data-act='absorb']"),   # 1.12.2 起是 .tl-menu-item (原来是小图标按钮)
        ("预设管理", ".tl-menu-item[data-act='preset-mgr']"),
        # ⚠ 保存预设是 .tl-btn.icon 不是 .tl-menu-item (它在菜单里的 .tl-preset-row 内)
        ("保存预设", ".tl-btn.icon[data-act='preset-save']"),
    ):
        esc_on_panel()
        before = cdp.ev(COUNT)
        force_open_menu(); time.sleep(0.4)
        r = cdp.ev(f"""(() => {{ const b = window.__tlp().querySelector("{opener}");
                       if (!b) return 'NO-BTN'; b.click(); return 'ok'; }})()""")
        time.sleep(1.6)
        after_open = cdp.ev(COUNT)
        cv = parse_close(close_topmost())
        time.sleep(1.0)
        after_close = cdp.ev(COUNT)
        leaked = after_close - before
        opened = after_open > before
        ok = (r == "ok") and opened and leaked == 0 and cv.get("inView") is True
        print(f"    {label:<8} 打开={r}  浮层 {before}→{after_open}→{after_close}"
              f"  关闭方式={cv.get('how')}  关闭按钮在视口内={cv.get('inView')}"
              f"  {'✓ 已回收' if ok else '✗'}")
        if r != "ok":
            FAILS.append(f"{label} 打不开: {r}")
        elif not opened:
            FAILS.append(f"{label} 点了没反应 (浮层数没变 {before}→{after_open})")
        elif cv.get("inView") is not True:
            FAILS.append(f"{label} 关闭按钮不在视口内 (top={cv.get('btnTop')} 视口高={cv.get('vh')})"
                         f" —— 用户要滚到底才能关")
        elif leaked != 0:
            FAILS.append(f"{label} 弹层关闭后未回收 (多出 {leaked} 层)")

    # ---------------------------------------------------------------- 4. 管理页 (/taglib) 的弹窗
    print("\n[4] 管理页 (/taglib) 的弹窗")
    # 管理页是**独立页面**, 另开一个标签页来测 —— 而且从已经开着弹层的 ComfyUI 页
    # 直接 navigate 会被拦 (实测报 "Frame ... is showing error page")。
    mtab = cdp.new_tab("http://127.0.0.1:8188/taglib?dlg=" + str(int(time.time())),
                       label="TagLib 管理页门禁")
    time.sleep(4)
    for _ in range(15):
        time.sleep(1)
        if cdp.ev("!!document.querySelector('.tl-manager, #pasteDialog, .mg-wrap, main')"):
            break
    # 找管理页里所有"会打开弹窗"的按钮
    opened = cdp.ev("""(() => {
      const cands = [...document.querySelectorAll('button')].filter(b =>
        /粘贴|导入|预览|备份|恢复/.test(b.textContent));
      return JSON.stringify(cands.map(b => b.textContent.trim()).slice(0, 12));
    })()""")
    print("    管理页里候选按钮:", opened)
    for label, sel in (("批量粘贴", "粘贴"), ("导入预览", "导入")):
        before = cdp.ev(COUNT)
        r = cdp.ev(f"""(() => {{
          const b = [...document.querySelectorAll('button')].find(x => /{sel}/.test(x.textContent));
          if (!b) return 'NO-BTN'; b.click(); return 'ok';
        }})()""")
        time.sleep(1.5)
        after_open = cdp.ev(COUNT)
        cv = parse_close(close_topmost())
        time.sleep(1.0)
        after_close = cdp.ev(COUNT)
        leaked = after_close - before
        opened = after_open > before
        ok = (r == "ok") and opened and leaked == 0 and cv.get("inView") is True
        print(f"    {label:<8} 打开={r}  浮层 {before}→{after_open}→{after_close}"
              f"  关闭方式={cv.get('how')}  关闭按钮在视口内={cv.get('inView')}"
              f"  {'✓ 已回收' if ok else '✗'}")
        if r != "ok":
            FAILS.append(f"管理页 {label} 打不开: {r}")
        elif not opened:
            FAILS.append(f"管理页 {label} 点了没反应 (浮层数没变 {before}→{after_open})")
        elif cv.get("inView") is not True:
            FAILS.append(f"管理页 {label} 关闭按钮不在视口内 (top={cv.get('btnTop')} "
                         f"视口高={cv.get('vh')})")
        elif leaked != 0:
            FAILS.append(f"管理页 {label} 弹层关闭后未回收 (多出 {leaked} 层)")

    cdp.close_tab(mtab)

    print("\n" + "=" * 64)
    if FAILS:
        print(f"弹层开/关测试: {len(FAILS)} 项失败")
        for f in FAILS:
            print("   -", f)
        return 1
    print("弹层开/关测试: 全部通过")
    return 0


def main() -> int:
    ui = ensure_bridge()
    tab = ui.new_tab("http://127.0.0.1:8188/?dlg=" + str(int(time.time())),
                     label="TagLib 弹层门禁")
    try:
        return _run(ui, tab)
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
    sys.exit(main())
