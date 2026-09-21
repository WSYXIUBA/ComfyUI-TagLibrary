"""编辑层字段 sidecar 往返门禁 —— _tagmeta.json 写出/还原。

python tests/tagmeta_roundtrip_test.py

背景 (1.7.0): .md 镜像只承载输出层字段 (en/zh/weight/nsfw/gender),
aliases/priority/rarity/enabled 这些编辑层字段此前在"文件夹重建库"
(热同步 pull / 清空重导) 时会静默丢失。sidecar `_tagmeta.json`
(按 en_lower 查表, 只存非默认值) 让字段完整往返。
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tagfiles
import tagparse  # noqa: E402


def main() -> int:
    errs: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            errs.append(f"{name}" + (f" -- {detail}" if detail else ""))

    old_lib_dir = tagfiles.LIBRARY_DIR
    tmp = tempfile.mkdtemp(prefix="taglib_meta_")
    tagfiles.LIBRARY_DIR = tmp
    # 路径常量的真源在 tagparse (1.8.3 四拆后各模块不再共享同一个全局)
    tagparse.LIBRARY_DIR = tmp
    try:
        lib = {"version": 1, "categories": [{
            "id": "c1", "name": "测试", "subcategories": [{
                "id": "c1.s1", "name": "槽位", "tags": [
                    {"id": "t1", "en": "fancy tag", "zh": "花哨", "weight": 1.0,
                     "aliases": ["fancy", "fancy2"], "priority": 80, "rarity": "rare"},
                    {"id": "t2", "en": "hidden tag", "zh": "隐藏", "weight": 1.0,
                     "enabled": False},
                    {"id": "t3", "en": "plain tag", "zh": "普通", "weight": 1.0},
                ]}]}]}

        tagfiles.sync_to_folder(lib, tmp)

        # 1) sidecar 写出: 非默认字段在, 默认值不在 (控体积)
        meta = tagfiles.load_tag_meta(tmp)
        check("sidecar 文件已写出",
              os.path.isfile(os.path.join(tmp, tagfiles.TAG_META_NAME)))
        check("rarity 入 sidecar", meta.get("fancy tag", {}).get("rarity") == "rare",
              str(meta.get("fancy tag")))
        check("priority 入 sidecar", meta.get("fancy tag", {}).get("priority") == 80)
        check("aliases 入 sidecar",
              meta.get("fancy tag", {}).get("aliases") == ["fancy", "fancy2"])
        check("enabled=false 入 sidecar",
              meta.get("hidden tag", {}).get("enabled") is False)
        check("默认值标签不进 sidecar", "plain tag" not in meta, str(sorted(meta)))

        # 2) 解析树无编辑层字段 → apply_tag_meta 还原
        md_path = os.path.join(tmp, "测试", "槽位", "槽位.md")
        with open(md_path, encoding="utf-8") as f:
            tree = tagfiles.parse_tagfile(f.read())
        tags = tree["categories"][0]["subcategories"][0]["tags"]
        t1 = next(t for t in tags if t["en"] == "fancy tag")
        t2 = next(t for t in tags if t["en"] == "hidden tag")
        check("解析树 aliases 为空默认", t1.get("aliases") == [], str(t1))
        tagfiles.apply_tag_meta(tree, tmp)
        check("aliases 还原", t1.get("aliases") == ["fancy", "fancy2"], str(t1))
        check("priority 还原", t1.get("priority") == 80)
        check("rarity 还原", t1.get("rarity") == "rare")
        check("enabled=false 还原 (覆盖 parse 物化的 True)",
              t2.get("enabled") is False, str(t2))

        # 3) 全链路: import_files_into 吸入空库 (热同步 pull 的同一路径)
        base = {"version": 1, "categories": []}
        tagfiles.import_files_into(base, [{"path": md_path}])
        got = base["categories"][0]["subcategories"][0]["tags"]
        g1 = next(t for t in got if t["en"] == "fancy tag")
        g2 = next(t for t in got if t["en"] == "hidden tag")
        check("吸入后 aliases 完整", g1.get("aliases") == ["fancy", "fancy2"], str(g1))
        check("吸入后 priority/rarity 完整",
              g1.get("priority") == 80 and g1.get("rarity") == "rare")
        check("吸入后 enabled=false 完整", g2.get("enabled") is False)

        # 4) sidecar 不参与指纹/导入扫描 (不会形成同步循环)
        fp = tagfiles._scan_fingerprint(tmp)
        check("指纹扫描跳过 sidecar",
              all(not k.startswith("_") for k in fp), str(sorted(fp)[:5]))
    finally:
        tagfiles.LIBRARY_DIR = old_lib_dir
        # 路径常量的真源在 tagparse (1.8.3 四拆后各模块不再共享同一个全局)
        tagparse.LIBRARY_DIR = old_lib_dir
        # 逐文件清理 (避免 rmtree 触发宿主批量删除保护)
        for root, _dirs, files in os.walk(tmp, topdown=False):
            for fn in files:
                try:
                    os.remove(os.path.join(root, fn))
                except OSError:
                    pass
            try:
                os.rmdir(root)
            except OSError:
                pass

    if errs:
        print(f"❌ sidecar 往返门禁失败 ({len(errs)} 项):")
        for e in errs:
            print("   -", e)
        return 1
    print("✅ 编辑层字段 sidecar 往返门禁通过 (写出/还原/全链路吸入/不进指纹)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
