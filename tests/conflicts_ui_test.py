"""v8 反冲突机制 CDP 验收: 右键入口 / 设置弹窗勾选保存 / 导出 / 导入 / 填充互斥生效。

用法: "D:/aiv4/python_embeded/python.exe" tests/conflicts_ui_test.py
"""

import json
import os
import time
import urllib.request

from manager_v5_test import CDP, check, find_tab, PASS, FAIL

BASE = "http://127.0.0.1:8188"
CONFLICTS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "data", "taglib", "conflicts.json")


def wait_cats(c, timeout=15):
    """等管理页分类列表渲染完成 (load 异步)。"""
    for _ in range(int(timeout / 1.5)):
        try:
            if c.js("document.querySelectorAll('#catList .cat-item').length > 0"):
                return True
        except Exception:
            pass
        time.sleep(1.5)
    return False


def api_json(path, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    tab = find_tab("127.0.0.1:8188")
    c = CDP(tab)
    c.cmd("Page.enable")
    print("== 0. 打开管理页 (强刷) ==")
    c.cmd("Page.navigate", {"url": BASE + "/taglib"})
    time.sleep(3)
    c.cmd("Page.reload", {"ignoreCache": True})
    time.sleep(3)

    print("== 1. 反冲突文件自动生成: 默认规则 + 旧组迁移 ==")
    st = api_json("/taglib/api/conflicts")
    ids = [r["id"] for r in st["rules"]]
    check("默认规则存在 (nude-vs-clothes 等)", "nude-vs-clothes" in ids, str(len(ids)))
    check("旧 20 组已迁移", sum(1 for i in ids if i.startswith("legacy.")) >= 15,
          str(sum(1 for i in ids if i.startswith("legacy."))))
    bad_invalid = [x for x in st["invalid"] if not str(x.get("id", "")).startswith("legacy.")]
    check("非迁移规则零失效 (失效识别只在旧组上, 因库演变)", not bad_invalid, str(bad_invalid[:2]))
    check("文件在 taglib 根目录", os.path.isfile(CONFLICTS_PATH))

    print("== 2. 标签右键 → 反冲突设置 → 勾选保存 ==")
    # 先切到 服装系统/上装 (corset 所在)
    wait_cats(c)
    c.js("""
      (async () => {
        const li = [...document.querySelectorAll("#catList .cat-item")].find(x => x.textContent.includes("服装系统"));
        li.click();
        await new Promise(r => setTimeout(r, 300));
        const tab = [...document.querySelectorAll("#subTabs .tab")].find(x => x.textContent.includes("上装"));
        if (tab) tab.click();
        await new Promise(r => setTimeout(r, 300));
      })()
    """)
    time.sleep(0.6)
    # 打开 corset (上装) 的右键菜单
    r = c.js("""
      (() => {
        const chips = [...document.querySelectorAll("#tagFlow .mtag")];
        const chip = chips.find(x => x.querySelector(".mt-en")?.textContent === "corset");
        if (!chip) return "no-chip";
        chip.dispatchEvent(new MouseEvent("contextmenu", {bubbles:true, clientX:500, clientY:300}));
        const menu = document.querySelector(".mtag-menu");
        return { menuOpen: !!menu, confBtn: !!menu?.querySelector('[data-act="conf"]') };
      })()
    """)
    check("chip 右键菜单含反冲突设置", isinstance(r, dict) and r.get("menuOpen") and r.get("confBtn"), str(r))
    c.js('document.querySelector(\'.mtag-menu [data-act="conf"]\').click(); 1')
    time.sleep(1.2)
    r = c.js("""
      (() => {
        const dlg = document.getElementById("conflictDialog");
        return { open: !dlg.classList.contains("hidden"),
                 subject: document.getElementById("cfSubject").textContent,
                 relations: [...document.querySelectorAll("#cfRelations .cf-rel")]
                   .map(x => x.textContent.replace("✕","").trim()),
                 treeRows: document.querySelectorAll("#cfTree .cf-row").length };
      })()
    """)
    check("反冲突设置弹窗打开", r["open"] is True, str(r))
    check("弹窗主题正确 (corset 无字面规则, 显示暂无)",
          r["subject"] == "corset" and isinstance(r["relations"], list), str(r["relations"]))
    # 勾选一个新目标: 展开人物主体 → 身体特征 → 勾 nude
    r = c.js("""
      (async () => {
        const tree = document.getElementById("cfTree");
        const rows = [...tree.querySelectorAll(".cf-row")];
        const subjRow = rows.find(x => x.textContent.includes("人物主体"));
        subjRow.querySelector(".cf-chev").click();
        await new Promise(r => setTimeout(r, 200));
        const rows2 = [...tree.querySelectorAll(".cf-row")];
        const bodyRow = rows2.find(x => x.textContent.includes("身体特征"));
        bodyRow.querySelector(".cf-chev").click();
        await new Promise(r => setTimeout(r, 200));
        const nudeChip = [...tree.querySelectorAll(".cf-tag")]
          .find(x => x.textContent.trim() === "nude");
        if (!nudeChip) return "no-nude";
        nudeChip.querySelector("input").click();
        await new Promise(r => setTimeout(r, 150));
        return { nudeChecked: nudeChip.querySelector("input").checked };
      })()
    """)
    check("勾选 nude 为冲突对象", r.get("nudeChecked") is True, str(r))
    c.js('document.getElementById("cfSave").click(); 1')
    time.sleep(1.5)
    st = api_json("/taglib/api/conflicts")
    rule = next((x for x in st["rules"] if x["left"].get("kind") == "tag"
                 and x["left"].get("value") == "corset"), None)
    check("保存后规则落盘 (corset ↔ nude)",
          rule is not None and any(ref.get("value") == "nude" for ref in rule["right"]),
          str(rule)[:150])
    disk = json.load(open(CONFLICTS_PATH, encoding="utf-8"))
    check("conflicts.json 磁盘同步", any(x["id"] == rule["id"] for x in disk["rules"]))

    print("== 3. 删除关系 (点 ✕) ==")
    wait_cats(c)
    c.js("""
      (async () => {
        const li = [...document.querySelectorAll("#catList .cat-item")].find(x => x.textContent.includes("服装系统"));
        li.click();
        await new Promise(r => setTimeout(r, 300));
        const tab = [...document.querySelectorAll("#subTabs .tab")].find(x => x.textContent.includes("上装"));
        if (tab) tab.click();
        await new Promise(r => setTimeout(r, 300));
      })()
    """)
    time.sleep(0.6)
    r = c.js("""
      (async () => {
        // 重开弹窗, 删掉 corset↔nude 关系
        const chips = [...document.querySelectorAll("#tagFlow .mtag")];
        const chip = chips.find(x => x.querySelector(".mt-en")?.textContent === "corset");
        chip.dispatchEvent(new MouseEvent("contextmenu", {bubbles:true, clientX:500, clientY:300}));
        document.querySelector('.mtag-menu [data-act="conf"]').click();
        await new Promise(r => setTimeout(r, 900));
        const rels = [...document.querySelectorAll("#cfRelations .cf-rel")];
        const nudeRel = rels.find(x => x.textContent.includes("nude"));
        if (!nudeRel) return "no-rel";
        nudeRel.querySelector(".cf-x").click();
        await new Promise(r => setTimeout(r, 300));
        document.getElementById("cfSave").click();
        return "removed";
      })()
    """)
    time.sleep(1.5)
    st = api_json("/taglib/api/conflicts")
    rule = next((x for x in st["rules"] if x["left"].get("kind") == "tag"
                 and x["left"].get("value") == "corset"), None)
    still = bool(rule and any(ref.get("value") == "nude" for ref in rule["right"]))
    check("关系删除并落盘", not still, str(rule)[:120] if rule else "规则已随空删除")

    print("== 4. 导出反冲突文件 / 双文件 ==")
    import glob, shutil, tempfile
    dl = tempfile.mkdtemp(prefix="taglib_cf_")
    c.cmd("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": dl})
    c.js('document.getElementById("btnTemplate").click(); 1')
    time.sleep(0.4)
    check("导出弹窗四选一",
          c.js("['tplBasic','tplFull','tplConflicts','tplConflictsFull'].every(id => document.getElementById(id))"))
    c.js('document.getElementById("tplConflicts").click(); 1')
    cf_path = None
    for _ in range(20):
        time.sleep(0.4)
        hits = glob.glob(os.path.join(dl, "conflicts.json"))
        if hits:
            cf_path = hits[0]
            break
    if cf_path:
        data = json.load(open(cf_path, encoding="utf-8"))
        check("conflicts.json 下载成功且带说明", "_说明" in data and len(data["rules"]) > 5)
    else:
        check("conflicts.json 下载成功", False)
    shutil.rmtree(dl, ignore_errors=True)

    print("== 5. 反冲突导入预览 → 替换 ==")
    probe_rules = [
        {"id": "probe.a", "left": {"kind": "tag", "value": "nude"},
         "right": [{"kind": "tag", "value": "jacket"}]},
        {"id": "probe.bad", "left": {"kind": "tag", "value": "不存在词"},
         "right": [{"kind": "tag", "value": "x"}]},
    ]
    r = c.js(f"window.__taglib.openConflictsImport({json.dumps(probe_rules, ensure_ascii=False)}); 1")
    time.sleep(1.2)
    r = c.js("""
      (() => {
        const dlg = document.getElementById("conflictImportDialog");
        return { open: !dlg.classList.contains("hidden"),
                 total: document.getElementById("cfiTotal").textContent,
                 valid: document.getElementById("cfiValid").textContent,
                 invalid: document.getElementById("cfiInvalid").textContent };
      })()
    """)
    # 失效按引用条数计: probe.bad 的 left("不存在词") 与 right("x") 两条引用失效
    check("导入预览: 2 规则全保留, 2 条引用失效",
          r["open"] and r["total"] == "2" and r["valid"] == "2" and r["invalid"] == "2", str(r))
    c.js('document.getElementById("cfiOk").click(); 1')
    time.sleep(1.5)
    st = api_json("/taglib/api/conflicts")
    ids = [x["id"] for x in st["rules"]]
    check("替换模式生效 (只剩 probe 规则, 失效规则带标记导入)", ids == ["probe.a", "probe.bad"],
          str(ids[:5]))
    check("失效引用清单返回", any("不存在词" in str(x.get("value")) for x in st["invalid"]))

    print("== 6. 恢复默认+迁移的完整规则集 ==")
    os.remove(CONFLICTS_PATH)
    st = api_json("/taglib/api/conflicts")
    ids = [r["id"] for r in st["rules"]]
    check("删除文件后自动重建 (默认+旧组迁移)",
          "nude-vs-clothes" in ids and sum(1 for i in ids if i.startswith("legacy.")) >= 15,
          f"{len(ids)} 条")

    print("== 7. 子分类/一级分类右键入口 ==")
    wait_cats(c)
    r = c.js("""
      (async () => {
        // 刷新页面确保 UI 干净
        location.reload();
        return "reloading";
      })()
    """)
    time.sleep(3.5)
    r = c.js("""
      (() => {
        const tab = document.querySelector("#subTabs .tab");
        tab.dispatchEvent(new MouseEvent("contextmenu", {bubbles:true, clientX:400, clientY:250}));
        const subConf = !!document.querySelector('.mtag-menu.sub-menu [data-act="conf"]');
        document.body.click();
        const li = document.querySelector("#catList .cat-item");
        li.dispatchEvent(new MouseEvent("contextmenu", {bubbles:true, clientX:400, clientY:250}));
        const menu = document.querySelector(".mtag-menu.sub-menu");
        const catConf = !!menu?.querySelector('[data-act="conf"]');
        const catRename = !!menu?.querySelector('[data-act="rename"]');
        document.body.click();
        return { subConf, catConf, catRename };
      })()
    """)
    check("子分类右键含反冲突设置", r.get("subConf") is True)
    check("一级分类右键菜单 (重命名/删除/反冲突)",
          r.get("catConf") and r.get("catRename"), str(r))

    print("== 8. 填充互斥实测 (面板) ==")
    c.cmd("Page.navigate", {"url": BASE + "/"})
    time.sleep(6)
    state = "loading"
    for _ in range(15):
        time.sleep(2)
        state = c.js("""
          (() => {
            if (typeof LiteGraph === "undefined" || !LiteGraph.registered_node_types?.["TagLibraryNode"]) return "reg-wait";
            if (!(window.app && window.app.graph)) {
              const cv = document.querySelector("canvas");
              for (const k of Object.getOwnPropertyNames(cv || {})) {
                try { if (cv[k] && cv[k].graph) { window.app = cv[k]; break; } } catch {}
              }
            }
            if (!(window.app && window.app.graph)) return "bind-wait";
            let node = app.graph._nodes.find(n => n.type === "TagLibraryNode");
            if (!node) {
              node = LiteGraph.createNode("TagLibraryNode");
              if (!node) return "create-null";
              node.pos = [200, 120];
              app.graph.add(node);
            }
            return "ready";
          })()
        """)
        if state == "ready":
            break
    print("step8:", state)
    time.sleep(2)
    c.js('document.querySelector(".taglib-panel [data-act=nsfw]").click(); 1')
    time.sleep(0.4)
    # 多轮填充: 若出现裸露类标签, 上装类必须缺席
    ok_rounds, bad_rounds = 0, []
    for i in range(10):
        c.js('document.querySelector(".taglib-panel [data-act=roll]").click(); 1')
        time.sleep(0.8)
        r = c.js("""
          (() => {
            const tags = [...document.querySelectorAll(".taglib-panel .tl-ttag b")]
              .map(x => x.textContent.trim().toLowerCase());
            const nudity = ["nude","topless","completely nude","partially nude","bottomless",
                            "naked towel","naked ribbon","naked apron"];
            const hasNudity = tags.some(t => nudity.includes(t));
            const tops = [...document.querySelectorAll("#tagFlow .mtag")].length; // unused
            const topsTags = tags.filter(t => ["corset","jacket","shirt","hoodie","dress",
              "bikini","micro bikini","string bikini","swimsuit","sailor collar","jacket on shoulders"].includes(t));
            return { hasNudity, topsTags, n: tags.length };
          })()
        """)
        if isinstance(r, dict):
            if r["hasNudity"]:
                if not r["topsTags"]:
                    ok_rounds += 1
                else:
                    bad_rounds.append(r)
            else:
                ok_rounds += 1
    check(f"填充互斥: {ok_rounds} 轮无违规", len(bad_rounds) == 0, str(bad_rounds[:2]))

    # 清理: 删除测试节点
    c.js("""
      (() => {
        const old = window.app?.graph?._nodes?.find(n => n.type === "TagLibraryNode");
        if (old) app.graph.remove(old);
      })()
    """)

    print(f"\n===== 结果: {len(PASS)} 过, {len(FAIL)} 挂 =====")
    if FAIL:
        print("失败项:", FAIL)
    c.close()


if __name__ == "__main__":
    main()
