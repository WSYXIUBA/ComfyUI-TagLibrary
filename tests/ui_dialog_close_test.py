"""弹层开/关功能测试 —— 每个可打开的界面都要能关掉。

    python tests/ui_dialog_close_test.py

背景 (2026-09-19): 用户报"很多功能界面打开都关不掉了"。本测试把每个可打开的
弹层/浮层走一遍「打开 → 断言已打开 → 关闭 → 断言真的关掉了」, 逐个报结果。

⚠ 本脚本用项目自带的 CDP 实例 (`C:\\EdgeForHermes` profile, 端口 9222) —— 这是
  门禁既有的自动化通道。它不碰用户的日常浏览器 (那里有用户自己的工作流)。
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ui_v13_check as U  # noqa: E402  复用 CDP / ensure_browser / http_json

FAILS: list[str] = []


def check(name: str, got, want, extra: str = "") -> None:
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {name}: {got!r}" + ("" if ok else f" (期望 {want!r})"))
    if not ok:
        FAILS.append(f"{name}={got!r} 期望 {want!r} {extra}")


def main() -> int:
    U.ensure_browser()
    tab = next(t for t in U.http_json("/json/list") if t["type"] == "page")
    cdp = U.CDP(tab)
    cdp.cmd("Page.enable")
    cdp.cmd("Network.enable")
    cdp.cmd("Network.setCacheDisabled", cacheDisabled=True)
    cdp.cmd("Page.navigate", url="http://127.0.0.1:8188/?dlg=" + str(int(time.time())))
    for _ in range(30):
        time.sleep(2)
        if cdp.ev("!!(window.app && window.app.graph)"):
            break
    print("app ready")

    # 建节点 + 等面板
    cdp.ev("""(() => {
      const g = window.app.graph;
      for (const o of [...g._nodes].filter(x => x.type === 'TagLibraryNode')) g.remove(o);
      const n = LiteGraph.createNode('TagLibraryNode');
      n.pos=[60,60]; n.size=[520,780]; g.add(n); n.setSize([520,780]);
      window.app.canvas?.setDirty?.(true, true); window.app.canvas?.draw?.(true, true);
      return 1;
    })()""")
    for _ in range(25):
        time.sleep(1)
        if cdp.ev("""(() => {
          const n = window.app.graph._nodes.filter(x => x.type === 'TagLibraryNode').pop();
          const w = n && n.widgets && n.widgets.find(x => x.name === 'taglib_panel');
          return !!(w && w.element && w.element.offsetHeight > 0
                    && w.element.querySelector('.tl-more-btn'));
        })()"""):
            break
    time.sleep(1)
    # 注入取面板的辅助函数 (只取可见的那份克隆)
    cdp.ev("""window.__tlp = () => [...document.querySelectorAll('.taglib-panel')]
                 .filter(x => x.offsetHeight > 0).pop(); 1""")
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
    print("    open:", cdp.ev(js_open(".tl-btn.primary")))
    time.sleep(2.5)
    check("挑选器已打开", cdp.ev("!!document.querySelector('.tp-wrap')"), True)
    cdp.ev("document.querySelector('.tp-cancel')?.click(); 1")
    time.sleep(1.2)
    check("「取消」可关闭挑选器", cdp.ev("!!document.querySelector('.tp-wrap')"), False)

    cdp.ev(js_open(".tl-btn.primary")); time.sleep(2.5)
    cdp.ev("document.querySelector('.tp-close2')?.click(); 1")
    time.sleep(1.2)
    check("「✕ 关闭」可关闭挑选器", cdp.ev("!!document.querySelector('.tp-wrap')"), False)

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
          b.click(); return 'clicked:' + b.textContent.trim().slice(0, 10);
        })()""")

    for label, opener in (
        ("批量探索", ".tl-menu-item[data-act='explorer']"),
        ("吸收器", ".tl-btn.icon[data-act='absorb']"),
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
        how = close_topmost()
        time.sleep(1.0)
        after_close = cdp.ev(COUNT)
        leaked = after_close - before
        ok = (r == "ok") and leaked == 0
        print(f"    {label:<8} 打开={r}  浮层 {before}→{after_open}→{after_close}"
              f"  关闭方式={how}  {'✓ 已回收' if ok else '✗ 泄漏 ' + str(leaked)}")
        if r == "ok" and leaked != 0:
            FAILS.append(f"{label} 弹层关闭后未回收 (多出 {leaked} 层)")

    # ---------------------------------------------------------------- 4. 管理页 (/taglib) 的弹窗
    print("\n[4] 管理页 (/taglib) 的弹窗")
    cdp.cmd("Page.navigate", url="http://127.0.0.1:8188/taglib?dlg=" + str(int(time.time())))
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
    for label, sel in (("批量粘贴", "paste"), ("导入预览", "导入")):
        before = cdp.ev(COUNT)
        r = cdp.ev(f"""(() => {{
          const b = [...document.querySelectorAll('button')].find(x => /{sel}/.test(x.textContent));
          if (!b) return 'NO-BTN'; b.click(); return 'ok';
        }})()""")
        time.sleep(1.5)
        after_open = cdp.ev(COUNT)
        how = close_topmost()
        time.sleep(1.0)
        after_close = cdp.ev(COUNT)
        leaked = after_close - before
        ok = (r == "ok") and leaked == 0
        print(f"    {label:<8} 打开={r}  浮层 {before}→{after_open}→{after_close}"
              f"  关闭方式={how}  {'✓ 已回收' if ok else '✗ 泄漏 ' + str(leaked)}")
        if r == "ok" and leaked != 0:
            FAILS.append(f"管理页 {label} 弹层关闭后未回收 (多出 {leaked} 层)")



    print("\n" + "=" * 64)
    if FAILS:
        print(f"弹层开/关测试: {len(FAILS)} 项失败")
        for f in FAILS:
            print("   -", f)
        return 1
    print("弹层开/关测试: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
