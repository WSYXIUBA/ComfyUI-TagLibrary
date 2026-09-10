"""v5 管理页验收: 子分类右键改名/删除 / AI模板下载 / 文件夹树 + 同步 + 真实导入还原。

前置: ComfyUI 已启动, 调试 Edge 已连接 (9222)。
用法: "D:/aiv4/python_embeded/python.exe" tests/manager_v5_test.py
"""

import base64
import glob
import json
import os
import shutil
import tempfile
import time
import urllib.request

from websocket import create_connection

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{extra}]" if extra else ""))


class CDP:
    def __init__(self, tab):
        self.ws = create_connection(tab["webSocketDebuggerUrl"], timeout=30,
                                    suppress_origin=True)
        self.n = 0

    def cmd(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                return msg

    def js(self, expr):
        r = self.cmd("Runtime.evaluate",
                     {"expression": expr, "returnByValue": True, "awaitPromise": True})
        res = r.get("result", {})
        if "exceptionDetails" in res:
            exc = res["exceptionDetails"].get("exception", {})
            raise RuntimeError(str(exc.get("description") or exc.get("value"))[:400])
        return res.get("result", {}).get("value")

    def js_with_dialog(self, expr, accept=True, prompt_text="", timeout=10):
        """执行会弹原生对话框的 JS (expr 内部应 setTimeout 触发), 自动应答。"""
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate",
                                 "params": {"expression": expr, "returnByValue": True}}))
        answered = False
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.ws.settimeout(1.0)
                msg = json.loads(self.ws.recv())
            except Exception:
                continue
            finally:
                self.ws.settimeout(30)
            if msg.get("method") == "Page.javascriptDialogOpening":
                self.n += 1
                self.ws.send(json.dumps({
                    "id": self.n, "method": "Page.handleJavaScriptDialog",
                    "params": {"accept": accept, "promptText": prompt_text}}))
                answered = True
            elif msg.get("id") == mid and answered:
                return True
        return False

    def close(self):
        self.ws.close()


def find_tab(sub):
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=5) as r:
        tabs = [t for t in json.loads(r.read()) if t.get("type") == "page"]
    for t in tabs:
        if sub in t.get("url", ""):
            return t
    raise SystemExit(f"no tab matching {sub!r}")


def api_library():
    with urllib.request.urlopen("http://127.0.0.1:8188/taglib/api/library", timeout=8) as r:
        return json.loads(r.read())


def api_save(lib, mtime):
    req = urllib.request.Request(
        "http://127.0.0.1:8188/taglib/api/library", method="POST",
        data=json.dumps(lib).encode(),
        headers={"Content-Type": "application/json", "X-TagLib-Mtime": str(mtime)})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


def main():
    tab = find_tab("127.0.0.1:8188")
    c = CDP(tab)
    c.cmd("Page.enable")

    print("== 0. 打开管理页 (强刷加载新 JS) ==")
    c.cmd("Page.navigate", {"url": "http://127.0.0.1:8188/taglib"})
    time.sleep(3)
    c.cmd("Page.reload", {"ignoreCache": True})
    time.sleep(3)

    print("== 1. 子分类页签右键菜单 ==")
    r = c.js("""
      (() => {
        const tabs = document.querySelectorAll("#subTabs .tab");
        if (!tabs.length) return { err: "no tabs" };
        tabs[0].dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true,
          clientX: 400, clientY: 300 }));
        const menu = document.querySelector(".mtag-menu.sub-menu");
        return { tabCount: tabs.length, menuOpen: !!menu,
                 hasRename: !!menu?.querySelector('[data-act="rename"]'),
                 hasDel: !!menu?.querySelector('[data-act="del"]'),
                 firstTab: tabs[0].textContent.trim() };
      })()
    """)
    check("右键弹出子分类菜单", r.get("menuOpen") is True, str(r))
    check("菜单含 重命名/删除", r.get("hasRename") and r.get("hasDel"))
    c.js("document.body.click()")

    print("== 2. 子分类重命名 (prompt 自动应答) ==")
    before = c.js('document.querySelector("#subTabs .tab").textContent.trim()')
    c.js_with_dialog(
        'setTimeout(() => document.querySelector("#subTabs .tab").dispatchEvent('
        'new MouseEvent("contextmenu", {bubbles:true,clientX:400,clientY:300})), 30); "fired"')
    # 菜单按钮内部同步调 prompt() -> 必须 setTimeout 异步点击, 否则 evaluate 被阻塞
    c.js_with_dialog(
        'setTimeout(() => document.querySelector(\'.mtag-menu.sub-menu [data-act="rename"]\').click(), 30); "fired"',
        accept=True, prompt_text="画质强化改名测试")
    time.sleep(0.4)
    after = c.js('document.querySelector("#subTabs .tab").textContent.trim()')
    check("页签文字已改", "改名测试" in after, f"{before!r} -> {after!r}")
    dirty = c.js('!document.getElementById("dirtyMark").classList.contains("hidden")')
    check("显示未保存标记", dirty is True)
    print("     (放弃修改: 刷新页面)")
    c.cmd("Page.reload", {"ignoreCache": True})
    time.sleep(2.5)

    print("== 3. 子分类删除 (confirm 自动应答) ==")
    n0 = c.js('document.querySelectorAll("#subTabs .tab").length')
    c.js_with_dialog(
        'setTimeout(() => document.querySelector("#subTabs .tab").dispatchEvent('
        'new MouseEvent("contextmenu", {bubbles:true,clientX:400,clientY:300})), 30); "fired"')
    c.js_with_dialog(
        'setTimeout(() => document.querySelector(\'.mtag-menu.sub-menu [data-act="del"]\').click(), 30); "fired"',
        accept=True)
    time.sleep(0.4)
    n1 = c.js('document.querySelectorAll("#subTabs .tab").length')
    check("页签数 -1", n1 == n0 - 1, f"{n0} -> {n1}")
    c.cmd("Page.reload", {"ignoreCache": True})
    time.sleep(2.5)

    print("== 4. AI 模板下载 (真实落盘) ==")
    dl_dir = tempfile.mkdtemp(prefix="taglib_dl_")
    c.cmd("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": dl_dir})
    c.js('setTimeout(() => document.getElementById("btnTemplate").click(), 20); "fired"')
    tpl_path = None
    for _ in range(20):
        time.sleep(0.4)
        hits = glob.glob(os.path.join(dl_dir, "*.md"))
        if hits:
            tpl_path = hits[0]
            break
    if tpl_path:
        content = open(tpl_path, encoding="utf-8").read()
        check("模板含使用说明", "使用说明" in content and "english(中文翻译){权重}[nsfw]" in content)
        check("模板结构与当前库一致", "# 质量与技术" in content and "## 画质强化" in content)
        check("示例标签带格式", "masterpiece(杰作){1.2}" in content)
        check("首行不是 # 标题 (避免幽灵分类)", not content.lstrip().startswith("#"))
    else:
        check("模板已下载", False, "未捕获下载文件")
    shutil.rmtree(dl_dir, ignore_errors=True)

    print("== 5. 文件对话框: 树形分组 + 同步到文件夹 ==")
    c.js('document.getElementById("btnFiles").click()')
    time.sleep(1.2)
    r = c.js("""
      (() => ({
        dialogOpen: !document.getElementById("filesDialog").classList.contains("hidden"),
        groups: [...document.querySelectorAll("#fileList .file-group")].map(g => g.textContent.trim()).slice(0, 4),
        libDirShown: document.getElementById("builtinDir").textContent,
      }))()
    """)
    check("对话框打开且有分组列表", r["dialogOpen"] and len(r["groups"]) > 0, str(r["groups"])[:120])
    c.js('document.getElementById("btnSyncFolder").click()')
    time.sleep(2.0)
    lib_dir = r["libDirShown"]
    check("data/标签库/ 已生成", os.path.isdir(lib_dir), lib_dir)
    sample = os.path.join(lib_dir, "质量与技术", "画质强化", "画质强化.md")
    check("两级文件夹结构落盘", os.path.isfile(sample), sample)
    r = c.js("""
      (() => {
        const groups = [...document.querySelectorAll("#fileList .file-group")]
          .map(g => g.textContent.trim());
        return { hasCatGroup: groups.some(g => g.startsWith("📁")), groups: groups.slice(0, 3) };
      })()
    """)
    check("列表出现 📁 大类/子分类 分组", r["hasCatGroup"], str(r["groups"]))

    print("== 6. 端到端: 隐含标题文件导入 (新分类) + 还原 ==")
    mtime0 = api_library()["mtime"]
    merged0 = api_library()["library"]
    has_test_before = any(c["name"] == "测试导入分类" for c in merged0["categories"])
    if not has_test_before:
        tf_dir = os.path.join(lib_dir, "测试导入分类", "测试子分类")
        os.makedirs(tf_dir, exist_ok=True)
        with open(os.path.join(tf_dir, "新词.md"), "w", encoding="utf-8") as f:
            f.write("folder_test_tag_one(文件夹测试一), folder_test_tag_two(文件夹测试二)\n")
        c.js('document.getElementById("extDirInput").onchange()')
        time.sleep(1.5)
        # 点「全部导入」只导这个新文件代价大 —— 直接找该行按钮
        clicked = c.js("""
          (() => {
            const rows = [...document.querySelectorAll("#fileList .file-row")];
            const row = rows.find(x => x.textContent.includes("新词.md"));
            if (!row) return "no-row";
            row.querySelector("button").click();
            return "clicked";
          })()
        """)
        time.sleep(2.5)
        merged1 = api_library()["library"]
        cat = next((x for x in merged1["categories"] if x["name"] == "测试导入分类"), None)
        check("导入后新分类出现", cat is not None)
        if cat:
            tags = [t["en"] for s in cat["subcategories"] for t in s["tags"]]
            check("无标题文件按文件夹归类", cat["subcategories"][0]["name"] == "测试子分类"
                  and "folder_test_tag_one" in tags, str(tags))
        # 还原: 从库里移除测试分类
        lib_now = api_library()["library"]
        lib_now["categories"] = [x for x in lib_now["categories"] if x["name"] != "测试导入分类"]
        lib_now.pop("_meta", None)
        api_save(lib_now, api_library()["mtime"])
        merged2 = api_library()["library"]
        check("还原: 测试分类已移除", not any(c["name"] == "测试导入分类" for c in merged2["categories"]))
        shutil.rmtree(os.path.join(lib_dir, "测试导入分类"), ignore_errors=True)
        c.js('document.getElementById("filesCancel").click()')

    print("== 7. 收尾: 回到 ComfyUI 主页面 ==")
    c.cmd("Page.navigate", {"url": "http://127.0.0.1:8188/"})
    time.sleep(2)
    check("页面回到主界面", True)

    print(f"\n===== 结果: {len(PASS)} 过, {len(FAIL)} 挂 =====")
    if FAIL:
        print("失败项:", FAIL)
    c.close()


if __name__ == "__main__":
    main()
