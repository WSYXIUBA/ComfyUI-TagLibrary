"""主题一致性验收 —— 真实浏览器 (Edge CDP) 下验证 面板 / 挑选器 / 管理弹窗
在深色与浅色两套 ComfyUI 主题中的配色是否都正确解析。

python tests/ui_theme_check.py
产出: tests/ui_theme_dark.png, tests/ui_theme_light.png, tests/ui_theme_manager.png
退出码 0 = 全部断言通过。
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

# 期望值 (深/浅两套主题的 --tl-bg / 弹窗底色, 与 tagpanel-css.js 对齐)
DARK_BG = "rgba(23,23,24,0.94)"
LIGHT_BG = "rgba(255,255,255,0.96)"
LIGHT_DIALOG = "rgb(255, 255, 255)"


PROBE = """(() => {
  const dlg = document.getElementById('taglib-picker-dialog');
  const panel = document.querySelector('.taglib-panel');
  const cs = (el) => el ? getComputedStyle(el) : null;
  const d = cs(dlg), p = cs(panel);
  const cat = dlg && dlg.querySelector('.tp-cat');
  const search = dlg && dlg.querySelector('.tp-search');
  return JSON.stringify({
    htmlClass: document.documentElement.className,
    panelVarBg: p ? p.getPropertyValue('--tl-bg').trim() : null,
    panelText: p ? p.color : null,
    panelLight: panel ? panel.classList.contains('tl-light') : null,
    dlgVarBg: d ? d.getPropertyValue('--tl-bg-solid').trim() : null,
    dlgBg: d ? d.backgroundColor : null,
    dlgText: d ? d.color : null,
    dlgLight: dlg ? dlg.classList.contains('tl-light') : null,
    catText: cat ? cs(cat).color : null,
  });
})()"""


def get_palette(cdp, tab=None):
    """读用户当前的配色 id (要还原的东西)。"""
    return cdp.ev("(() => { try { return window.app.extensionManager.setting"
                  ".get('Comfy.ColorPalette'); } catch(e) { return null; } })()", tab)


def set_palette(cdp, pid: str, tab=None):
    """设置配色。

    ⚠ 这个设置是**写进用户 `user/default/comfy.settings.json`** 的 —— 门禁切主题
    会把用户自己的配色 (例如 github) 覆盖掉, 跑完**必须还原** (2026-09-19 真踩过,
    用户当天就发现了)。
    """
    cdp.ev(f"""(() => {{
      try {{ window.app.extensionManager.setting.set('Comfy.ColorPalette', '{pid}'); }} catch(e) {{}}
      return 'ok';
    }})()""", tab)


def set_theme(cdp, light: bool, tab=None):
    """切到深/浅色: 官方用 html.dark-theme 类区分明暗, 配色 id 存设置里。"""
    pid = "light" if light else "dark"
    set_palette(cdp, pid, tab)
    cdp.ev(f"document.documentElement.classList.toggle('dark-theme', {str(not light).lower()})", tab)
    time.sleep(1.2)   # 等 MutationObserver -> applyTheme


def check(label, got, cond, errs):
    ok = cond(got)
    print(f"    {'✓' if ok else '✗'} {label}: {got}")
    if not ok:
        errs.append(f"{label}={got}")
    return ok


def _run(cdp, tab):
    """cdp 现在是 UiBridge —— cdp.ev / cdp.shot 的调用点语义与旧 CDP 一致。"""
    # 2) 等 app ready
    if not wait_app(cdp, tab, 60):
        print("app 未就绪")
        sys.exit(1)
    print("app ready")


    # 建节点 + 开挑选器
    cdp.ev("""(() => {
      // ⚠ 只在画布上另建一个带标记的节点, 不动用户工作流里已有的 TagLibraryNode
      //   (跑完删掉自己这个)。断言一律通过 window.__tlGateNode 定位它。
      window.__tlGateView = window.__tlGateView || JSON.stringify({
        offset: window.app.canvas?.ds?.offset, scale: window.app.canvas?.ds?.scale });
      const n = LiteGraph.createNode('TagLibraryNode');
      n.pos=[100,100]; n.size=[520,760]; window.app.graph.add(n);
      n.title = '__tl_gate__';
      window.__tlGateNode = n;
      // 真浏览器里视图可能停在别处, 节点不在可视区就不会给 DOM widget 排布局
      // (面板 offsetHeight=0 → 后面取元素全部落空) → 把视图挪到节点上
      window.app.canvas?.centerOnNode?.(n);
      const sw = n.widgets && n.widgets.find(w=>w.name==='selection_state');
      if (sw) sw.value = JSON.stringify({tags:[{en:'katana',pinned:true,enabled:true}],
        fill_master:true, fill_master_min:2, fill_master_max:3, nl_tail:true});
      return 'node';
    })()""")
    time.sleep(2)
    print("picker:", cdp.ev("""(() => {
      const n = window.__tlGateNode;
      const w = n.widgets.find(x=>x.name==='taglib_panel');
      // 按 data-act 取, 别按文案 —— 按钮文案改过一次(「＋ 添加标签」→「＋ 添加」),
      // 按文案找的断言就静默失效了。
      const btn = w.element.querySelector('[data-act="addtags"]');
      btn.click(); return 'clicked';
    })()"""))
    time.sleep(2.5)

    errs = []

    # ---------- 深色 ----------
    set_theme(cdp, light=False, tab=tab)
    d = json.loads(cdp.ev(PROBE))
    cdp.shot("ui_theme_dark.png")
    print("  [深色主题]")
    check("面板 --tl-bg", d["panelVarBg"], lambda v: v == DARK_BG, errs)
    check("面板 tl-light", d["panelLight"], lambda v: v is False, errs)
    check("弹窗 --tl-bg-solid", d["dlgVarBg"], lambda v: v == "#15171d", errs)
    check("弹窗底色", d["dlgBg"], lambda v: v.startswith("rgb(21"), errs)
    check("面板文字为浅色", d["panelText"], lambda v: _lum(v) > 180, errs)
    check("分类项文字为浅色", d["catText"], lambda v: _lum(v) > 120, errs)

    # ---------- 浅色 ----------
    set_theme(cdp, light=True, tab=tab)
    l = json.loads(cdp.ev(PROBE))
    cdp.shot("ui_theme_light.png")
    print("  [浅色主题]")
    check("面板 --tl-bg", l["panelVarBg"], lambda v: v == LIGHT_BG, errs)
    check("面板 tl-light", l["panelLight"], lambda v: v is True, errs)
    check("弹窗 --tl-bg-solid", l["dlgVarBg"], lambda v: v == "#ffffff", errs)
    check("弹窗底色", l["dlgBg"], lambda v: v == LIGHT_DIALOG, errs)
    check("弹窗 tl-light", l["dlgLight"], lambda v: v is True, errs)
    check("面板文字为深色", l["panelText"], lambda v: _lum(v) < 90, errs)
    check("弹窗文字为深色", l["dlgText"], lambda v: _lum(v) < 90, errs)
    check("分类项文字为深色", l["catText"], lambda v: _lum(v) < 130, errs)

    # ---------- 管理弹窗 (独立文档, 走 iframe + 主题参数) ----------
    print("  [管理页]")
    cdp.ev("document.getElementById('taglib-picker-dialog')?.close()")
    time.sleep(0.8)
    mgr = cdp.ev("""(() => {
      const p = [...document.querySelectorAll('.taglib-panel')].filter(x => x.offsetHeight > 0).pop();
      if (!p) return 'NO-PANEL';
      const more = p.querySelector('.tl-more-btn');
      if (!more) return 'NO-MORE-BTN';
      more.click();                       // ⋯ 菜单是同步展开的, 同一个 tick 里就能点
      const item = p.querySelector('.tl-menu-item[data-act="manager"]');
      if (!item) return 'NO-MENU-ITEM';
      item.click(); return 'clicked';
    })()""")
    print(f"    打开管理弹窗: {mgr}")
    time.sleep(3.5)
    mgrProbe = cdp.ev("""(() => {
      const dlg = document.getElementById('taglib-manager-dialog');
      if (!dlg) return JSON.stringify({found:false});
      const fr = dlg.querySelector('iframe');
      let inner = null;
      try {
        const doc = fr.contentDocument;
        inner = {
          src: fr.getAttribute('src'),
          htmlClass: doc.documentElement.className,
          bodyBg: doc.defaultView.getComputedStyle(doc.body).backgroundColor,
          textColor: doc.defaultView.getComputedStyle(doc.body).color,
          okBtnBorder: (() => {
            const el = doc.getElementById('btnSave');
            return el ? doc.defaultView.getComputedStyle(el).borderColor : null;
          })(),
        };
      } catch (e) { inner = {err: e.message}; }
      return JSON.stringify({found:true, dlgClass: dlg.className, inner});
    })()""")
    cdp.shot("ui_theme_manager.png")
    mi = json.loads(mgrProbe)
    if not mi.get("found"):
        errs.append("管理弹窗未创建")
        print("    ✗ 管理弹窗未创建")
    else:
        inner = mi.get("inner") or {}
        print(f"    iframe src: {inner.get('src')}")
        check("iframe 带 light=1 参数", str(inner.get("src", "")), lambda v: "light=1" in v, errs)
        check("管理页 html 有 tl-light", inner.get("htmlClass", ""), lambda v: "tl-light" in v, errs)
        check("管理页 body 底色为浅色", inner.get("bodyBg", ""), lambda v: _lum(v) > 240, errs)
        check("管理页文字为深色", inner.get("textColor", ""), lambda v: _lum(v) < 90, errs)

    print()
    if errs:
        print(f"❌ 主题巡检失败 ({len(errs)} 项):")
        for e in errs:
            print("   -", e)
        sys.exit(1)
    print("✅ 主题巡检全通过 (深色/浅色/管理页)")
    print("截图: tests/ui_theme_dark.png, ui_theme_light.png, ui_theme_manager.png")


def _lum(rgb: str) -> float:
    """'rgb(r, g, b)' -> 感知亮度 (0-255)。"""
    try:
        parts = rgb.replace("rgba(", "rgb(").split("(")[1].split(")")[0].split(",")
        r, g, b = (float(x) for x in parts[:3])
        return 0.299 * r + 0.587 * g + 0.114 * b
    except Exception:
        return -1.0


def main():
    ui = ensure_bridge()
    tab = ui.new_tab("http://127.0.0.1:8188/", label="TagLib UI 门禁")
    saved_palette = None
    try:
        wait_app(ui, tab, 60)
        saved_palette = get_palette(ui, tab)
        print(f"  [主题] 用户原配色: {saved_palette!r} (跑完还原)")
        _run(ui, tab)
    finally:
        # ⚠ 先还原用户的配色 —— 它是持久设置, 不还原等于把用户的主题改掉
        if saved_palette:
            try:
                set_palette(ui, str(saved_palette), tab)
                print(f"  [主题] 已还原为 {saved_palette!r}")
            except Exception:  # noqa: BLE001
                pass
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

