"""v6 验收: 导出模板双选 / 导入预览确认 / 清空三键弹窗 / 备份-清空-恢复回滚。

用法: "D:/aiv4/python_embeded/python.exe" tests/manager_v6_test.py
"""

import glob
import json
import os
import shutil
import tempfile
import time
import urllib.request

from manager_v5_test import CDP, check, find_tab, PASS, FAIL

BASE = "http://127.0.0.1:8188"
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DIR = os.path.join(PLUGIN_ROOT, "data", "标签库")


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

    print("== 1. 顶栏按钮: 导出已移除 / 导出模板+备份+清空 就位 ==")
    r = c.js("""
      (() => ({
        exportGone: !document.getElementById("btnExport"),
        resetGone: !document.getElementById("btnReset"),
        tpl: !!document.getElementById("btnTemplate"),
        bkSave: !!document.getElementById("btnBackupSave"),
        bkRestore: !!document.getElementById("btnBackupRestore"),
        clear: !!document.getElementById("btnClearLib"),
      }))()
    """)
    check("导出按钮已移除", r["exportGone"] is True)
    check("恢复默认库按钮已由清空标签库取代", r["resetGone"] is True)
    check("导出模板/存为默认库/恢复备份库/清空标签库 就位",
          all([r["tpl"], r["bkSave"], r["bkRestore"], r["clear"]]))

    print("== 2. 导出模板: 双选弹窗 + 两种文件真实落盘 ==")
    dl = tempfile.mkdtemp(prefix="taglib_tpl_")
    c.cmd("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": dl})
    c.js('document.getElementById("btnTemplate").click(); 1')
    time.sleep(0.4)
    r = c.js("""
      (() => ({
        dlg: !document.getElementById("templateDialog").classList.contains("hidden"),
        basic: !!document.getElementById("tplBasic"),
        full: !!document.getElementById("tplFull"),
      }))()
    """)
    check("模板选择弹窗 (基础/全量)", r["dlg"] and r["basic"] and r["full"])
    c.js('document.getElementById("tplBasic").click(); 1')
    basic_path = None
    for _ in range(20):
        time.sleep(0.4)
        hits = [p for p in glob.glob(os.path.join(dl, "*.md")) if "全量" not in p]
        if hits:
            basic_path = hits[0]
            break
    if basic_path:
        txt = open(basic_path, encoding="utf-8").read()
        check("基础模板: 文件名+骨架+示例上限注释",
              os.path.basename(basic_path) == "taglib_模板.md" and "基础" in txt and "使用说明" in txt
              and "# 质量与技术" in txt)
    else:
        check("基础模板已下载", False)
    c.js('document.getElementById("btnTemplate").click(); document.getElementById("tplFull").click(); 1')
    full_path = None
    for _ in range(20):
        time.sleep(0.4)
        hits = [p for p in glob.glob(os.path.join(dl, "*.md")) if "全量" in p]
        if hits:
            full_path = hits[0]
            break
    if full_path:
        txt = open(full_path, encoding="utf-8").read()
        check("全量模板: 文件名+全标签 (含 masterpiece 与重构说明)",
              os.path.basename(full_path) == "taglib_模板_全量.md"
              and "masterpiece(杰作){1.2}" in txt and "重构" in txt)
    else:
        check("全量模板已下载", False)
    shutil.rmtree(dl, ignore_errors=True)

    print("== 3. 导入预览 (上传文本路径): 取消不入库 / 确认才写入 ==")
    # 注: 标签库文件夹内的文件会被热同步抢先吸入 (那是预期行为),
    #     所以预览流走 📥导入 的文本路径 (模板场景) 测试。
    PROBE = ("# 测试预览分类\n## 测试预览子类\n"
             "preview_probe_tag(预览探针), another_probe(另一个探针)\n")
    payload_js = json.dumps({"items": [{"text": PROBE}]}, ensure_ascii=False)
    c.js(f'window.__taglib.openImportPreview({payload_js}); 1')
    time.sleep(1.2)
    r = c.js("""
      (() => {
        const dlg = document.getElementById("previewDialog");
        return { open: !dlg.classList.contains("hidden"),
                 count: document.getElementById("pvCount").textContent,
                 dup: document.getElementById("pvDup").textContent,
                 groups: [...document.querySelectorAll("#previewList .pv-group")].map(g => g.textContent),
                 tags: [...document.querySelectorAll("#previewList .pv-tag")].map(t => t.textContent) };
      })()
    """)
    check("预览弹窗打开, 新增 2 / 分组正确",
          r["open"] and r["count"] == "2" and any("测试预览分类" in g for g in r["groups"]),
          str(r["groups"]))
    check("新增标签列出", "preview_probe_tag" in "".join(r["tags"]), str(r["tags"])[:100])
    # 取消
    c.js('document.getElementById("pvCancel").click(); 1')
    lib = api_json("/taglib/api/library")["library"]
    still_absent = not any(c["name"] == "测试预览分类" for c in lib["categories"])
    check("取消后未入库", still_absent)
    # 再来一次 → 确认
    c.js(f'window.__taglib.openImportPreview({payload_js}); 1')
    time.sleep(1.2)
    c.js('document.getElementById("pvOk").click(); 1')
    time.sleep(2.0)
    lib = api_json("/taglib/api/library")["library"]
    cat = next((x for x in lib["categories"] if x["name"] == "测试预览分类"), None)
    check("确认后入库 (按分类归位)", cat is not None and
          any(t["en"] == "preview_probe_tag" for s in cat["subcategories"] for t in s["tags"]))

    print("== 4. 备份 → 清空 → 恢复 回滚周期 ==")
    # 记录当前状态 (用户库应含 人物补充)
    lib0 = api_json("/taglib/api/library")["library"]
    names0 = [x["name"] for x in lib0["categories"]]
    # 存为默认库
    c.js('document.getElementById("btnBackupSave").click(); 1')
    time.sleep(1.5)
    info = api_json("/taglib/api/library/backup")
    check("备份文件已生成", info["exists"] is True)
    # 清空 (直接确定)
    c.js('document.getElementById("btnClearLib").click(); 1')
    time.sleep(0.4)
    r = c.js("""
      (() => {
        const dlg = document.getElementById("clearDialog");
        return { open: !dlg.classList.contains("hidden"),
                 bOk: !!document.getElementById("clearOk"),
                 bExp: !!document.getElementById("clearExport"),
                 bCancel: !!document.getElementById("clearCancel") };
      })()
    """)
    check("清空弹窗三按钮", r["open"] and r["bOk"] and r["bExp"] and r["bCancel"])
    # 先试取消
    c.js('document.getElementById("clearCancel").click(); 1')
    lib = api_json("/taglib/api/library")["library"]
    check("取消后未清空", any(x["name"] == "人物补充" for x in lib["categories"]) or len(lib["categories"]) == len(names0))
    # 真清空
    c.js('document.getElementById("btnClearLib").click(); document.getElementById("clearOk").click(); 1')
    time.sleep(2.5)
    lib = api_json("/taglib/api/library")["library"]
    check("清空后回到出厂默认 (人物补充消失)", not any(x["name"] == "人物补充" for x in lib["categories"]),
          str(len(lib["categories"])) + " 分类")
    check("清空后文件夹同步重建", not os.path.exists(os.path.join(LIB_DIR, "测试预览分类")))
    # 恢复备份 (带 confirm 应答)
    c.js_with_dialog(
        'setTimeout(() => document.getElementById("btnBackupRestore").click(), 30); "fired"',
        accept=True)
    time.sleep(2.5)
    lib = api_json("/taglib/api/library")["library"]
    names_restored = [x["name"] for x in lib["categories"]]
    check("恢复备份后数据完整回滚", sorted(names_restored) == sorted(names0),
          f"{len(names0)} -> {len(names_restored)}")
    check("预览测试的分类也随备份回来了",
          any(x["name"] == "测试预览分类" for x in lib["categories"]))

    print("== 5. 清理: 移除测试分类 (走保存→文件夹镜像自清) ==")
    data = api_json("/taglib/api/library")
    lib = data["library"]
    lib["categories"] = [x for x in lib["categories"] if x["name"] != "测试预览分类"]
    lib.pop("_meta", None)
    req = urllib.request.Request(BASE + "/taglib/api/library", method="POST",
                                 data=json.dumps(lib).encode(),
                                 headers={"Content-Type": "application/json",
                                          "X-TagLib-Mtime": str(data["mtime"])})
    with urllib.request.urlopen(req, timeout=10) as r2:
        json.loads(r2.read())
    time.sleep(0.5)
    check("测试分类已清理且文件夹同步删除",
          not any(x["name"] == "测试预览分类" for x in api_json("/taglib/api/library")["library"]["categories"])
          and not os.path.exists(os.path.join(LIB_DIR, "测试预览分类")))
    shutil.rmtree(os.path.join(LIB_DIR, '测试预览分类'), ignore_errors=True)

    print(f"\n===== 结果: {len(PASS)} 过, {len(FAIL)} 挂 =====")
    if FAIL:
        print("失败项:", FAIL)
    c.close()


if __name__ == "__main__":
    main()
