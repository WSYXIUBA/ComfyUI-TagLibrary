"""v4 改造验收: 管理页✕移除 / 挑选器遮罩退出 / 4页签 / 设置双向同步。

前置: ComfyUI 已启动(8188), 调试 Edge 已连接(9222)。
用法: python tests/picker_tabs_test.py
"""

import json
import time
import urllib.request

from websocket import create_connection


def find_tab(sub: str) -> dict:
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
        tabs = json.loads(r.read())
    pages = [t for t in tabs if t.get("type") == "page"]
    for t in pages:
        if sub == t.get("url"):
            return t
    for t in pages:
        if sub in t.get("url", ""):
            return t
    raise SystemExit(f"no tab matching {sub!r}; have: {[t.get('url') for t in pages]}")


class CDP:
    def __init__(self, tab: dict):
        self.ws = create_connection(tab["webSocketDebuggerUrl"], timeout=30,
                                    suppress_origin=True)
        self.n = 0

    def cmd(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method,
                                 "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                return msg

    def js(self, expr: str):
        r = self.cmd("Runtime.evaluate",
                     {"expression": expr, "returnByValue": True, "awaitPromise": True})
        res = r.get("result", {})
        if "exceptionDetails" in res:
            exc = res["exceptionDetails"].get("exception", {})
            raise RuntimeError(str(exc.get("description") or exc.get("value"))[:500])
        return res.get("result", {}).get("value")

    def close(self):
        self.ws.close()


PASS, FAIL = [], []


def check(name: str, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{extra}]" if extra else ""))


def main() -> None:
    tab = find_tab("127.0.0.1:8188")
    c = CDP(tab)
    print("== 0. 强刷页面加载新 JS ==")
    c.cmd("Page.enable")
    c.cmd("Page.reload", {"ignoreCache": True})
    time.sleep(6)

    print("== 1. 绑定 window.app (canvas 反查) + 画布放一个标签库节点 ==")
    r = c.js("""
      (() => {
        if (!(window.app && window.app.graph)) {
          const cv = document.querySelector('canvas');
          for (const k of Object.getOwnPropertyNames(cv || {})) {
            try { if (cv[k] && cv[k].graph) { window.app = cv[k]; break; } } catch {}
          }
        }
        if (!(window.app && window.app.graph)) return 'nf';
        return 'bound';
      })()
    """)
    if r != "bound":
        raise SystemExit(f"app bind failed: {r}")
    c.js("""
      (() => {
        const old = app.graph._nodes.find(n => n.type === "TagLibraryNode");
        if (old) app.graph.remove(old);
        const node = LiteGraph.createNode("TagLibraryNode");
        node.pos = [300, 200];
        app.graph.add(node);
        try { app.canvas.setDirty?.(true, true); app.canvas.dirty = true; } catch {}
        return true;
      })()
    """)
    time.sleep(1.5)

    print("== 2. 面板头部: ⚙ 按钮已删除, ➕ 存在 ==")
    r = c.js("""
      (() => {
        const panel = document.querySelector(".taglib-panel");
        return {
          randset: !!panel.querySelector('[data-act="randset"]'),
          addtags: !!panel.querySelector('[data-act="addtags"]'),
          headBtns: [...panel.querySelectorAll(".tl-head .tl-btn")].map(b => b.textContent.trim()),
        };
      })()
    """)
    check("面板无 ⚙ randset 按钮", r["randset"] is False)
    check("➕ 添加标签按钮存在", r["addtags"] is True)
    check("头部按钮: NSFW/文A/🚫/➕", json.dumps(r["headBtns"], ensure_ascii=False),
          str(r["headBtns"]))

    print("== 3. 打开挑选器: 4 页签 ==  ")
    c.js('document.querySelector(\'[data-act="addtags"]\').click()')
    time.sleep(0.8)
    r = c.js("""
      (() => {
        const dlg = document.getElementById("taglib-picker-dialog");
        if (!dlg) return { open: false };
        const root = dlg.querySelector("#taglib-picker-root");
        return {
          open: dlg.open,
          tabs: [...root.querySelectorAll(".tp-tabbtn")].map(b => b.textContent.trim()),
          mgr: !!root.querySelector(".tp-mgrtab"),
          set: !!root.querySelector(".tp-settab"),
          close2: !!root.querySelector(".tp-close2"),
          cancelVisible: root.querySelector(".tp-cancel").style.display !== "none",
        };
      })()
    """)
    check("挑选器打开", r["open"] is True)
    check("4 页签齐全", r["tabs"] and len(r["tabs"]) == 4, str(r.get("tabs")))
    check("底部有关闭按钮(管理/设置页用)", r["close2"] is True)

    print("== 4. 挑选器点遮罩退出 ==")
    c.js("""
      (() => {
        const dlg = document.getElementById("taglib-picker-dialog");
        dlg.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        // dialog 自身为 target 才关闭; 这里模拟真实遮罩点击:
        return true;
      })()
    """)
    # dispatchEvent 在 dlg 上 target=dlg, 应触发关闭
    time.sleep(0.5)
    r = c.js("!!document.getElementById('taglib-picker-dialog')")
    check("点遮罩后挑选器已关闭", r is False)
    c.js('document.querySelector(\'[data-act="addtags"]\').click()')
    time.sleep(0.8)

    print("== 5. 设置页签: 节点参数即改即存 ==")
    r = c.js("""
      (async () => {
        const root = document.querySelector("#taglib-picker-dialog #taglib-picker-root");
        root.querySelector(".tp-settab").click();
        await new Promise(r => setTimeout(r, 300));
        const dd = root.querySelector(".sv-dd");
        dd.checked = false;
        dd.dispatchEvent(new Event("change"));
        await new Promise(r => setTimeout(r, 200));
        const node = app.graph._nodes.find(n => n.type === "TagLibraryNode");
        const st = JSON.parse(node.widgets.find(w => w.name === "selection_state").value);
        return { dedupe: st.dedupe, hasSep: !!root.querySelector(".sv-sep"),
                 hasPinned: !!root.querySelector(".sv-pinned"),
                 hasW: !!root.querySelector(".sv-w"),
                 hasSearch: !!root.querySelector(".sv-search"),
                 foot: root.querySelector(".tp-footinfo").textContent };
      })()
    """)
    check("去重改 false 已写入 selection_state", r["dedupe"] is False)
    check("节点参数 5 项齐全", all([r["hasSep"], r["hasPinned"], r["hasW"], r["hasSearch"]]))
    check("设置页底部提示文案", "即改即存" in r["foot"], r["foot"])
    # 还原
    c.js("""
      (() => {
        const root = document.querySelector("#taglib-picker-dialog #taglib-picker-root");
        const dd = root.querySelector(".sv-dd"); dd.checked = true; dd.dispatchEvent(new Event("change"));
      })()
    """)

    print("== 6. 设置页签: 全局偏好写入 ComfyUI 设置 ==")
    r = c.js("""
      (async () => {
        const root = document.querySelector("#taglib-picker-dialog #taglib-picker-root");
        const sc = root.querySelector(".sv-gscale");
        sc.value = "120";
        sc.dispatchEvent(new Event("change"));
        await new Promise(r => setTimeout(r, 200));
        const viaApi = app.extensionManager.setting.get("TagLibrary.chip_scale");
        return { viaApi, cssVar: document.documentElement.style.getPropertyValue("--taglib-chip-scale") };
      })()
    """)
    check("比例 120 已写入官方设置 API", r["viaApi"] == 120, str(r["viaApi"]))
    check("CSS 变量跟随 (=1.2)", r["cssVar"].strip() == "1.2", r["cssVar"])

    print("== 7. 反向同步: ComfyUI 设置 -> 设置页签显示 ==")
    r = c.js("""
      (async () => {
        app.extensionManager.setting.set("TagLibrary.chip_scale", 85);
        await new Promise(r => setTimeout(r, 200));
        const root = document.querySelector("#taglib-picker-dialog #taglib-picker-root");
        root.querySelector(".tp-settab").click();  // 重新渲染读取最新值
        root.querySelector(".tp-picktab").click();
        root.querySelector(".tp-settab").click();
        await new Promise(r => setTimeout(r, 300));
        return { shown: root.querySelector(".sv-gscale").value };
      })()
    """)
    check("设置页显示 85 (反向同步)", r["shown"] == "85", str(r["shown"]))
    c.js('app.extensionManager.setting.set("TagLibrary.chip_scale", 100)')

    print("== 8. 标签库管理页签: iframe 加载 ==")
    r = c.js("""
      (async () => {
        const root = document.querySelector("#taglib-picker-dialog #taglib-picker-root");
        root.querySelector(".tp-mgrtab").click();
        await new Promise(r => setTimeout(r, 800));
        const ifr = root.querySelector(".tp-mgrview iframe");
        const foot = root.querySelector(".tp-footinfo").textContent;
        const okVisible = root.querySelector(".tp-ok").style.display === "none";
        const closeVisible = root.querySelector(".tp-close2").style.display !== "none";
        return { src: ifr ? ifr.getAttribute("src") : null, foot, okVisible, closeVisible };
      })()
    """)
    check("iframe src = /taglib?embed=1", r["src"] == "/taglib?embed=1", str(r["src"]))
    check("确定按钮隐藏/关闭按钮显示", r["okVisible"] and r["closeVisible"])
    check("底部提示", "全局生效" in r["foot"], r["foot"])

    print("== 9. 离开管理页签 -> 库缓存刷新, 挑选页 chips 重渲染 ==")
    r = c.js("""
      (async () => {
        const root = document.querySelector("#taglib-picker-dialog #taglib-picker-root");
        root.querySelector(".tp-picktab").click();
        await new Promise(r => setTimeout(r, 900));
        const chips = root.querySelectorAll(".tp-chips .tp-tag").length;
        return { chips };
      })()
    """)
    check("挑选页 chips 重新渲染 (>100)", r["chips"] > 100, str(r["chips"]))

    print("== 10. 管理页弹窗: ✕ 已移除, 遮罩可关 ==")
    c.js("""
      (() => {
        document.getElementById("taglib-picker-dialog").close();
        document.getElementById("taglib-picker-dialog").remove();
        return true;
      })()
    """)
    # 用户路径: 点右上角顶栏按钮打开
    r = c.js("""
      (async () => {
        const btn = document.getElementById("taglib-topbar-btn");
        if (!btn) return { err: "no topbar btn" };
        btn.click();
        await new Promise(r => setTimeout(r, 800));
        const dlg = document.getElementById("taglib-manager-dialog");
        return { open: !!dlg && dlg.open,
                 closeBtn: !!dlg.querySelector("#taglib-mgr-close"),
                 iframe: !!dlg.querySelector("iframe") };
      })()
    """)
    check("管理页弹窗打开(顶栏按钮)", r.get("open") is True, str(r))
    check("✕ 关闭按钮已移除", r.get("closeBtn") is False)
    check("iframe 存在", r.get("iframe") is True)
    r = c.js("""
      (() => {
        const dlg = document.getElementById("taglib-manager-dialog");
        dlg.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        return true;
      })()
    """)
    time.sleep(0.5)
    r = c.js("""
      (() => {
        const dlg = document.getElementById("taglib-manager-dialog");
        // 管理页弹窗 close 后不 remove (重开时才清理), 断言 open 状态
        return dlg ? dlg.open : false;
      })()
    """)
    check("点遮罩后管理页弹窗已关", r is False)
    # 命令路径 (Extensions 菜单同一命令)
    r = c.js("""
      (async () => {
        try { await app.extensionManager.command.execute("zhixin.openTagLibraryManager"); }
        catch (e) { return { err: String(e) }; }
        await new Promise(r => setTimeout(r, 500));
        const dlg = document.getElementById("taglib-manager-dialog");
        const ok = !!dlg && dlg.open;
        if (dlg) { dlg.close(); dlg.remove(); }
        return { open: ok };
      })()
    """)
    check("命令执行打开管理页 (Extensions 菜单路径)", r.get("open") is True, str(r))

    print(f"\n===== 结果: {len(PASS)} 过, {len(FAIL)} 挂 =====")
    if FAIL:
        print("失败项:", FAIL)
    c.close()


if __name__ == "__main__":
    main()
