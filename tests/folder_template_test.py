"""文件夹两级结构 + AI模板 + 按名称合并导入 的后端测试 (纯内存/临时目录, 不碰真实库)。

用法: "D:/aiv4/python_embeded/python.exe" tests/folder_template_test.py
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tagfiles
from tagfiles import (apply_implied_headings, export_to_folder, merge_tree_by_name,
                      parse_tagfile, scan_folder)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{extra}]" if extra else ""))


def make_lib():
    return {
        "version": 1,
        "categories": [
            {"id": "quality", "name": "质量与技术", "icon": "🏆", "color": "#f39c12",
             "subcategories": [
                 {"id": "quality.s1", "name": "画质强化", "tags": [
                     {"id": "quality.s1.m", "en": "masterpiece", "zh": "杰作", "weight": 1.2, "aliases": [], "enabled": True},
                     {"id": "quality.s1.b", "en": "best quality", "zh": "最佳质量", "weight": 1.2, "aliases": [], "enabled": True},
                     {"id": "quality.s1.n", "en": "nsfw_test", "zh": "测试", "weight": 1.0, "aliases": [], "nsfw": True, "enabled": True},
                 ]},
                 {"id": "quality.s2", "name": "真实感", "tags": []},
             ]},
            {"id": "subject", "name": "人物主体", "icon": "🧑", "color": "#54a0ff",
             "subcategories": [
                 {"id": "subject.s1", "name": "发型发色", "tags": [
                     {"id": "subject.s1.h", "en": "long hair", "zh": "长发", "weight": 1.0, "aliases": [], "enabled": True},
                 ]},
             ]},
        ],
    }


def test_export_and_scan():
    print("== 导出库到两级文件夹 + 树形扫描 ==")
    tmp = tempfile.mkdtemp(prefix="taglib_test_")
    try:
        lib = make_lib()
        stats = export_to_folder(lib, tmp)
        check("统计: 2分类/3子分类/4标签", (stats["categories"], stats["subcategories"], stats["tags"]) == (2, 3, 4), str(stats))
        p1 = os.path.join(tmp, "质量与技术", "画质强化", "画质强化.md")
        p2 = os.path.join(tmp, "质量与技术", "真实感", "真实感.md")
        check("画质强化/画质强化.md 存在 (二级=文件夹)", os.path.isfile(p1))
        check("空子分类 真实感/ 照样生成", os.path.isfile(p2))
        content = open(p1, encoding="utf-8").read()
        check("文件自带两级标题", "# 质量与技术" in content and "## 画质强化" in content)
        check("权重语法 {1.2}", "masterpiece(杰作){1.2}" in content, content.splitlines()[3][:60] if len(content.splitlines()) > 3 else content)
        check("nsfw 语法 [nsfw]", "nsfw_test(测试)[nsfw]" in content)
        check("_说明.md 生成", os.path.isfile(os.path.join(tmp, "_说明.md")))

        files = scan_folder(tmp)
        by_name = {f["file_name"]: f for f in files}
        check("扫描跳过 _说明.md", "_说明.md" not in by_name)
        f1 = by_name.get("画质强化.md", {})
        check("扫描归属: cat=质量与技术 sub=画质强化",
              f1.get("cat_dir") == "质量与技术" and f1.get("sub_dir") == "画质强化", str(f1))

        # 重导出 (同名覆盖, 幂等)
        stats2 = export_to_folder(lib, tmp)
        check("重复导出幂等", stats2["files"] == 3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_implied_headings():
    print("== 无标题文件按文件夹名补隐含分类 ==")
    text = "smile(微笑), laugh(大笑)\n"
    out = apply_implied_headings(text, "人物主体", "表情情绪")
    tree = parse_tagfile(out)
    cats = tree["categories"]
    check("归类到 人物主体/表情情绪",
          cats and cats[0]["name"] == "人物主体" and cats[0]["subcategories"][0]["name"] == "表情情绪"
          and cats[0]["subcategories"][0]["tags"][0]["en"] == "smile")
    # 有标题的文件不被注入
    with_head = "# 自有分类\n## 自有子类\nfoo(福)\n"
    out2 = apply_implied_headings(with_head, "人物主体", "表情情绪")
    check("自带标题的文件保持原样", out2 == with_head)


def test_merge_by_name():
    print("== 按名称合并: 中文分类不产生 imported.cat 重复 ==")
    base = make_lib()
    # 模拟 AI 补充后的模板文件: 现有分类名 + 新标签 (含新子分类)
    md = """<!--
说明注释 (应被忽略)
-->
# 质量与技术
## 画质强化
ultra detailed(超精细), crisp details(细节清晰)
## 负面质量
bad anatomy(结构错误)
# 全新分类
## 新子分类
new_tag(新标签)
"""
    new_tree = parse_tagfile(md)
    merged = merge_tree_by_name(base, new_tree)
    cats = {c["name"]: c for c in merged["categories"]}
    check("并入现有 质量与技术", "质量与技术" in cats and len([c for c in merged["categories"] if c["name"] == "质量与技术"]) == 1)
    subs = {s["name"]: s for s in cats["质量与技术"]["subcategories"]}
    check("并入现有子分类 画质强化", "ultra detailed" in [t["en"] for t in subs["画质强化"]["tags"]])
    check("新增子分类 负面质量", "bad anatomy" in [t["en"] for t in subs["负面质量"]["tags"]])
    check("新分类『全新分类』创建", "全新分类" in cats)
    newsubs = cats["全新分类"]["subcategories"]
    check("新分类的子分类/标签落位", newsubs and newsubs[0]["name"] == "新子分类" and newsubs[0]["tags"][0]["en"] == "new_tag")
    # id 唯一性 + 无 imported.cat 退化
    all_ids = []
    for c in merged["categories"]:
        all_ids.append(c["id"])
        for s in c["subcategories"]:
            all_ids.append(s["id"])
            for t in s["tags"]:
                all_ids.append(t["id"])
    check("全部 id 唯一", len(all_ids) == len(set(all_ids)))
    check("无 'imported.cat' 退化 id", "imported.cat" not in all_ids)
    check("现有标签未被动 (masterpiece 权重还在)", 
          any(t["en"] == "masterpiece" and t.get("weight") == 1.2 for s in cats["质量与技术"]["subcategories"] for t in s["tags"]))


def test_template_roundtrip():
    print("== 模板闭环: 模板格式文件 parse 后注释被忽略、无幽灵分类 ==")
    tpl = """<!--
🏷 模板说明 (使用方法...) --> 
# 质量与技术
## 画质强化
masterpiece(杰作){1.2}, best quality(最佳质量){1.2}
<!-- (另有一个已有标签未展示) -->
ultra detailed(超精细)
"""
    tree = parse_tagfile(tpl)
    names = [c["name"] for c in tree["categories"]]
    check("注释不产生幽灵分类", names == ["质量与技术"], str(names))
    subs = tree["categories"][0]["subcategories"]
    ens = [t["en"] for t in subs[0]["tags"]]
    check("标签解析含新增", set(ens) == {"masterpiece", "best quality", "ultra detailed"}, str(ens))
    # 去重: 已存在的被剔掉, 只剩新词
    base = make_lib()
    merged_flat = json.loads(json.dumps(base))
    filtered, stats = tagfiles.dedupe_against(tree, merged_flat)
    kept = [t["en"] for c in filtered["categories"] for s in c["subcategories"] for t in s["tags"]]
    check("去重后只剩新标签", kept == ["ultra detailed"], str(kept))


if __name__ == "__main__":
    test_export_and_scan()
    test_implied_headings()
    test_merge_by_name()
    test_template_roundtrip()
    print(f"\n===== 结果: {len(PASS)} 过, {len(FAIL)} 挂 =====")
    if FAIL:
        print("失败项:", FAIL)
        sys.exit(1)
