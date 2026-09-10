"""主题一致性验收 —— 真实浏览器 (Edge CDP) 下验证 面板 / 挑选器 / 管理弹窗
在深色与浅色两套 ComfyUI 主题中的配色是否都正确解析。

python tests/ui_theme_check.py
产出: tests/ui_theme_dark.png, tests/ui_theme_light.png, tests/ui_theme_manager.png
退出码 0 = 全部断言通过。
"""

import base64
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = HERE

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

DARK_BG = "rgba(23,23,24,0.94)"
LIGHT_BG = "rgba(255,255,255,0.96)"
LIGHT_DIALOG = "rgb(255, 255, 255)"


def http_json(path, method="GET"):
    r = urllib.request.Request("http://127.0.0.1:9222" + path, method=method)
    return json.loads(_OPENER.open(r, timeout=5).read())


class CDP:
    def __init__(self, tab):
        self.tab = tab
        self.ws = None
        self.mid = 0

    def connect(self):
        from websocket import create_connection
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.ws = create_connection(self.tab["webSocketDebuggerUrl"],
                                    timeout=25, suppress_origin=True)

    def cmd(self, method, **params):
        for _ in range(3):
            try:
                if not self.ws:
                    self.connect()
                self.mid += 1
                mid = self.mid
                self.ws.send(json.dumps({"id": mid, "method": method,
                                         "params": params}))
                while True:
                    m = json.loads(self.ws.recv())
                    if m.get("id") == mid:
                        return m.get("result", {})
            except Exception:
                self.ws = None
                time.sleep(1.5)
        raise RuntimeError("CDP 三连失败: " + method)

    def ev(self, expr):
        r = self.cmd("Runtime.evaluate", expression=expr,
                     returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            return "EXC:" + str(r["exceptionDetails"].get("exception", {})
                                .get("description", ""))[:200]
        return r.get("result", {}).get("value")

    def shot(self, name):
        r = self.cmd("Page.captureScreenshot", format="png")
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(base64.b64decode(r["data"]))
        return name


def ensure_browser():
    import subprocess
    try:
        http_json("/json/version")
        return
    except Exception:
        pass
    exe = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
                if os.path.exists(p)), None)
    subprocess.Popen([exe, "--remote-debugging-port=9222",
                      r"--user-data-dir=C:\EdgeForHermes",
                      "--no-proxy-server", "--no-first-run", "about:blank"],
                     creationflags=0x208)
    for _ in range(15):
        time.sleep(1.5)
        try:
            http_json("/json/version")
            return
        except Exception:
            pass
    raise RuntimeError("9222 起不来")


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
    topbarBg: (() => {
      const b = document.getElementById('taglib-topbar-btn');
      return b ? cs(b).backgroundColor : null;
    })(),
    topbarText: (() => {
      const b = document.getElementById('taglib-topbar-btn');
      return b ? cs(b).color : null;
    })(),
  });
})()"""


def set_theme(cdp, light: bool):
    """切换 ComfyUI 主题: 官方用 html.dark-theme 类区分明暗, 配色 id 存设置里。"""
    pid = "light" if light else "dark"
    cdp.ev(f"""(() => {{
      try {{ window.app.extensionManager.setting.set('Comfy.ColorPalette', '{pid}'); }} catch(e) {{}}
      document.documentElement.classList.toggle('dark-theme', {str(not light).lower()});
      return 'ok';
    }})()""")
    time.sleep(1.2)   # 等 MutationObserver -> applyTheme


def check(label, got, cond, errs):
    ok = cond(got)
    print(f"    {'✓' if ok else '✗'} {label}: {got}")
    if not ok:
        errs.append(f"{label}={got}")
    return ok


def main():
    ensure_browser()
    old = [t for t in http_json("/json/list") if t.get("type") == "page"]
    http_json("/json/new?url=about:blank", method="PUT")
    time.sleep(1)
    for t in old:
        try:
            http_json("/json/close/" + t["id"])
        except Exception:
            pass
    tab = next(t for t in http_json("/json/list") if t["type"] == "page")
    cdp = CDP(tab)
    cdp.cmd("Page.navigate", url="http://127.0.0.1:8188/")
    for _ in range(30):
        time.sleep(2)
        if cdp.ev("!!(window.app && window.app.graph)"):
            break
    else:
        print("app 未就绪")
        sys.exit(1)
    print("app ready")

    # 建节点 + 开挑选器
    cdp.ev("""(() => {
      const n = LiteGraph.createNode('TagLibraryNode');
      n.pos=[100,100]; n.size=[520,760]; window.app.graph.add(n);
      const sw = n.widgets && n.widgets.find(w=>w.name==='selection_state');
      if (sw) sw.value = JSON.stringify({tags:[{en:'katana',pinned:true,enabled:true}],
        fill_master:true, fill_master_min:2, fill_master_max:3, nl_tail:true});
      return 'node';
    })()""")
    time.sleep(2)
    print("picker:", cdp.ev("""(() => {
      const n = window.app.graph._nodes.find(x=>x.type==='TagLibraryNode');
      const w = n.widgets.find(x=>x.name==='taglib_panel');
      const btn = [...w.element.querySelectorAll('button')].find(b=>/添加标签/.test(b.textContent));
      btn.click(); return 'clicked';
    })()"""))
    time.sleep(2.5)

    errs = []

    # ---------- 深色 ----------
    set_theme(cdp, light=False)
    d = json.loads(cdp.ev(PROBE))
    cdp.shot("ui_theme_dark.png")
    print("  [深色主题]")
    check("面板 --tl-bg", d["panelVarBg"], lambda v: v == DARK_BG, errs)
    check("面板 tl-light", d["panelLight"], lambda v: v is False, errs)
    check("弹窗 --tl-bg-solid", d["dlgVarBg"], lambda v: v == "#15171d", errs)
    check("弹窗底色", d["dlgBg"], lambda v: v.startswith("rgb(21"), errs)
    check("面板文字为浅色", d["panelText"], lambda v: _lum(v) > 180, errs)
    check("分类项文字为浅色", d["catText"], lambda v: _lum(v) > 120, errs)
    check("顶栏按钮底色为深色", d["topbarBg"], lambda v: _lum(v) < 90, errs)
    check("顶栏按钮文字为浅色", d["topbarText"], lambda v: _lum(v) > 150, errs)

    # ---------- 浅色 ----------
    set_theme(cdp, light=True)
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
    check("顶栏按钮底色为浅色", l["topbarBg"], lambda v: _lum(v) > 200, errs)
    check("顶栏按钮文字为深色", l["topbarText"], lambda v: _lum(v) < 90, errs)
    check("顶栏按钮带 tl-light", cdp.ev(
        "document.getElementById('taglib-topbar-btn')?.classList.contains('tl-light')"),
        lambda v: v is True, errs)

    # ---------- 管理弹窗 (独立文档, 走 iframe + 主题参数) ----------
    print("  [管理页]")
    cdp.ev("document.getElementById('taglib-picker-dialog')?.close()")
    time.sleep(0.8)
    mgr = cdp.ev("""(() => {
      const b = document.getElementById('taglib-topbar-btn');
      if (!b) return 'NO-BTN';
      b.click(); return 'clicked';
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


if __name__ == "__main__":
    main()
