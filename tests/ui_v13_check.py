"""UI 验收: 面板结构 → 开 picker → 逐 tab 截图+断言 → 编辑能力断言。

v1.6.0 起额外断言 (失败即退出码非 0):
  · 页签收敛为 5 个 (挑标签/武器档案/互斥域/NL句式/设置), 排除类目与防冲突已合并
  · 排除类目出现在侧栏抽屉里
  · 武器档案 / 互斥域 / NL 三个视图是**可编辑**的 (存在 input.tp-ecell / 增删按钮 / 保存按钮)
  · 跨池互斥规则已并入互斥域页


python tests/ui_v13_check.py
产出: tests/ui_panel.png, ui_axis.png, ui_prof.png, ui_grp.png, ui_nl.png, ui_set.png
退出码 0 = 面板结构断言全过。
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


def http_json(path, method="GET"):
    r = urllib.request.Request("http://127.0.0.1:9222" + path, method=method)
    return json.loads(_OPENER.open(r, timeout=5).read())


class CDP:
    """每次操作自动重连的极简 CDP 客户端 (页面导航/冻结不炸整轮)。"""

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
        for attempt in range(3):
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
        res = r.get("result", {})
        if r.get("exceptionDetails"):
            return "EXC:" + str(r["exceptionDetails"].get("exception", {})
                                .get("description", ""))[:160]
        return res.get("value")

    def shot(self, name):
        r = self.cmd("Page.captureScreenshot", format="png")
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(base64.b64decode(r["data"]))
        return name


def ensure_browser():
    """9222 不活就自己拉 Edge 调试实例。"""
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


def main():
    ensure_browser()
    # 先开新页签再关旧的 (关光最后页签 = Edge 整个退出, 别再自杀)
    old = [t for t in http_json("/json/list")
           if t.get("type") == "page"]
    tab = http_json("/json/new?url=about:blank", method="PUT")
    time.sleep(1)
    for t in old:
        try:
            http_json("/json/close/" + t["id"])
        except Exception:
            pass
    tab = http_json("/json/list")
    tab = next(t for t in tab if t["type"] == "page")
    cdp = CDP(tab)
    cdp.cmd("Page.navigate", url="http://127.0.0.1:8188/")
    # 2) 等 app ready
    for _ in range(30):
        time.sleep(2)
        ok = cdp.ev("!!(window.app && window.app.graph)")
        if ok:
            break
        cdp = CDP(http_json("/json/list")[0] if False else tab)
    else:
        print("app 未就绪")
        sys.exit(1)
    print("app ready")

    # 3) 建测试节点 (带一把钉选 katana)
    r = cdp.ev("""(() => {
      const n = LiteGraph.createNode('TagLibraryNode');
      n.pos=[100,100]; n.size=[520,760]; window.app.graph.add(n);
      const sw = n.widgets && n.widgets.find(w=>w.name==='selection_state');
      if (sw) sw.value = JSON.stringify({tags:[{en:'katana',pinned:true,enabled:true}],
        fill_master:true, fill_master_min:2, fill_master_max:3, nl_tail:true});
      return 'node';
    })()""")
    print("node:", r)
    time.sleep(2)

    # ---- 节点面板结构 (面板瘦身: 死 UI 已删, 低频项收进 ⋯ 菜单) ----
    panel_errs = []
    probe = cdp.ev("""(() => {
      const n = window.app.graph._nodes.find(x=>x.type==='TagLibraryNode');
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
        gender: label('.tl-gender-val'),
        conflict: label('.tl-conflict-val'),
        lang: label('.tl-lang-val'),
        pv: label('.tl-pv-val'),
        hasRoll: !!p.querySelector('.tl-roll-btn'),
        hasClearBtn: !!p.querySelector('.tl-clear-btn'),
      });
    })()""")
    pv = json.loads(probe)
    print("PANEL:", json.dumps(pv, ensure_ascii=False))

    def chk(name, got, want):
        ok = got == want
        print(f"    {'✓' if ok else '✗'} {name}: {got!r}" + ("" if ok else f" (期望 {want!r})"))
        if not ok:
            panel_errs.append(f"{name}={got!r} 期望 {want!r}")

    chk("头部常驻按钮数", pv["headButtons"], 3)          # NSFW / ⋯ / ＋添加标签
    chk("Fast-Smart 死 UI 已删", pv["hasEngineSeg"], False)
    chk("⋯ 菜单默认隐藏", pv["menuHidden"], True)
    chk("⋯ 菜单项数", pv["menuItems"], 5)                # 性别/防冲突/语言/预览/清空
    chk("清空按钮已移入菜单", pv["hasClearBtn"], False)
    chk("🎲 填充常驻", pv["hasRoll"], True)
    for k, name in [("gender", "菜单·性别"), ("conflict", "菜单·防冲突"),
                    ("lang", "菜单·语言"), ("pv", "菜单·预览")]:
        if not pv[k]:
            print(f"    ✗ {name} 无状态文案")
            panel_errs.append(f"{name} 无状态文案")
        else:
            print(f"    ✓ {name}: {pv[k]}")

    # 展开 ⋯ 菜单, 确认可正常打开
    cdp.ev("""(() => {
      const n = window.app.graph._nodes.find(x=>x.type==='TagLibraryNode');
      const p = n.widgets.find(x=>x.name==='taglib_panel').element;
      p.querySelector('.tl-more-btn').click(); return 'ok';
    })()""")
    time.sleep(0.6)
    opened = cdp.ev("""(() => {
      const n = window.app.graph._nodes.find(x=>x.type==='TagLibraryNode');
      const p = n.widgets.find(x=>x.name==='taglib_panel').element;
      const m = p.querySelector('.tl-menu');
      return JSON.stringify({hidden: m.hidden, visible: m.offsetHeight > 0});
    })()""")
    ov = json.loads(opened)
    print(f"    ⋯ 菜单展开: {ov}")
    if ov["hidden"] or not ov["visible"]:
        panel_errs.append("⋯ 菜单展开失败")
    cdp.shot("ui_panel.png")
    cdp.ev("""(() => {
      const n = window.app.graph._nodes.find(x=>x.type==='TagLibraryNode');
      const p = n.widgets.find(x=>x.name==='taglib_panel').element;
      p.querySelector('.tl-more-btn').click(); return 'ok';
    })()""")
    time.sleep(0.3)

    # 打开挑选器
    r = cdp.ev("""(() => {
      const n = window.app.graph._nodes.find(x=>x.type==='TagLibraryNode');
      const w = n.widgets.find(x=>x.name==='taglib_panel');
      if (!w || !w.element) return 'NO-PANEL-WIDGET';
      const btn = [...w.element.querySelectorAll('button')].find(b=>/添加标签/.test(b.textContent));
      if (!btn) return 'NO-ADD-BTN';
      btn.click();
      return 'clicked';
    })()""")
    print("picker:", r)
    time.sleep(2.5)

    tabs = cdp.ev("[...document.querySelectorAll('.tp-tabbtn')].map(b=>b.textContent.trim()).join(' | ')")
    print("TABS:", tabs)

    # ---- 页签收敛 + 排除抽屉 (v1.6.0) ----
    ui_errs = []
    want_tabs = ["挑标签", "⚔ 武器档案", "🧬 互斥域", "✍ NL 句式", "⚙ 设置"]
    for t in want_tabs:
        ok = t in tabs
        print(f"    {'✓' if ok else '✗'} 页签存在: {t}")
        if not ok:
            ui_errs.append(f"缺页签 {t}")
    for bad in ("排除类目", "防冲突关系", "标签库管理"):
        ok = bad not in tabs
        print(f"    {'✓' if ok else '✗'} 页签已合并/删除: {bad}")
        if not ok:
            ui_errs.append(f"未删除页签 {bad}")
    n_tabs = len([x for x in tabs.split(" | ") if x.strip()])
    print(f"    {'✓' if n_tabs == 5 else '✗'} 页签总数 = {n_tabs} (期望 5)")
    if n_tabs != 5:
        ui_errs.append(f"页签数 {n_tabs} != 5")

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

    # 4) 轴视图
    cdp.ev("""(() => {
      const b=[...document.querySelectorAll('.tp-vm')].find(x=>x.dataset.vm==='axis');
      if(b) b.click(); return !!b;
    })()""")
    time.sleep(2)
    click_tab(".tp-picktab", "ui_axis.png",
              """(() => {
                const heads=[...document.querySelectorAll('.tp-axis-head')].map(h=>h.textContent.trim().split(' ')[0]+'×'+(h.querySelector('.tp-axis-n')||{}).textContent);
                const b=document.querySelectorAll('.tp-tag.bundled').length;
                const secs=[...document.querySelectorAll('.tp-sec-head')].map(x=>x.textContent.trim());
                return JSON.stringify({axisHeads: heads.slice(0,8), bundleChips: b, sections: secs});
              })()""", "AXIS")

    # 5) 武器档案 (可编辑)
    click_tab(".tp-proftab", "ui_prof.png",
              """(() => {
                const cards=document.querySelectorAll('.tp-pcard').length;
                const rows=document.querySelectorAll('.tp-ptab tr').length;
                const h1=(document.querySelector('.tp-h1')||{}).textContent;
                const cells=document.querySelectorAll('.tp-ecell').length;
                const chips=document.querySelectorAll('.tp-echip').length;
                const adds=document.querySelectorAll('.tp-eadd').length;
                const saves=document.querySelectorAll('.tp-save').length;
                return JSON.stringify({h1:h1, cards, poseRows:rows, editableCells:cells,
                                       editableChips:chips, addBtns:adds, saveBtns:saves});
              })()""", "PROF")
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
    if not (grp_v["groups"] == 50 and grp_v["cells"] >= 50 and grp_v["cfRules"] >= 1):
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

    print("\n截图在 tests/ 下: ui_panel ui_axis ui_prof ui_grp ui_nl ui_set")

    all_errs = panel_errs + ui_errs
    if all_errs:
        print(f"\n❌ UI 巡检失败 ({len(all_errs)} 项):")
        for e in all_errs:
            print("   -", e)
        sys.exit(1)
    print("✅ UI 巡检通过 (面板瘦身 / 页签 8→5 / 三个数据视图可编辑)")


if __name__ == "__main__":
    main()
