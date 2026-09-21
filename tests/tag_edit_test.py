"""标签就地编辑端点测试 (沙箱: 全程不碰真实用户库与 .md 镜像)。

覆盖:
  A. derive 推导 —— 只给 en/中文/轴/槽位 就能得到字段完整的标签
  B. /tag/derive  预览不落盘
  C. /tag/create  新增落盘 + 幂等去重
  D. /tag/update  就地改字段 + 白名单拦截 + 非法值被 schema 归一
  E. /taglib/api/axes-overview 六段分组与真实计数
  F. /tag/incomplete 三类缺口报告

⚠ 沙箱手法 (三层都得挡, 少一层就会写真实数据):
   1. `library.USER_PATH` / `library.DATA_DIR` → 临时目录 (库写入)
   2. `library._folder_hot_sync` → 空操作。**必须挡** —— `get_merged()` 内部会调它,
      它会往真实 `data/default/taglib/**/*.md` 重新镜像 (实测把
      `服装/腿袜与内衣/腿袜与内衣.md` 的 `thong(丁字裤)` 改成了 `thong(丁字裤)[nsfw]`)。
      不能靠改 `tagfiles.LIBRARY_DIR` 绕过: `sync_to_folder(lib, folder=LIBRARY_DIR)`
      的默认值是**定义时**求值的, 改模块属性无效。
   3. `library.mirror_folder_now` → 空操作 (端点自带的写后镜像)
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# api/ 包内部用的是 `from .. import library` 相对导入, 只能作为插件根包的子包加载。
# 与 tests/api_security_test.py 同一手法: 造一个合成父包 (__path__ 指向仓库根),
# 不执行根 __init__.py (那会拉起 ComfyUI 的 server 模块)。
_PARENT = "taglib_plugin"
if _PARENT not in sys.modules:
    _pkg = types.ModuleType(_PARENT)
    _pkg.__path__ = [ROOT]
    sys.modules[_PARENT] = _pkg

axes = importlib.import_module(_PARENT + ".axes")
derive = importlib.import_module(_PARENT + ".derive")
library = importlib.import_module(_PARENT + ".library")
ter = importlib.import_module(_PARENT + ".api.tag_edit_routes")

_FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"    ok   {label}")
    else:
        print(f"    FAIL {label}")
        _FAILURES.append(label)


class _Req:
    """只实现 handler 用到的 `await request.json()`。"""

    def __init__(self, payload: dict | None = None):
        self._payload = payload if payload is not None else {}

    async def json(self):
        return self._payload


def run(coro):
    return asyncio.run(coro)


def body(resp) -> dict:
    return json.loads(resp.body.decode("utf-8"))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="taglib_edit_")
    saved = (library.USER_PATH, library.DATA_DIR)
    real_mirror = library.mirror_folder_now
    real_hot_sync = library._folder_hot_sync
    try:
        library.USER_PATH = os.path.join(tmp, "tag_library.user.json")
        library.DATA_DIR = tmp
        library.mirror_folder_now = lambda: None   # 不落 .md 镜像
        library._folder_hot_sync = lambda: None    # 读库不再触发真实镜像重写
        library.invalidate_cache()

        lib = library.get_merged()
        slot_id = None
        for cat in lib["categories"]:
            for sub in cat["subcategories"]:
                if sub.get("name") == "武器装备" and cat.get("name") == "道具武器":
                    slot_id = sub["id"]
        check(bool(slot_id), f"定位到 道具武器/武器装备 槽位 ({slot_id})")
        base_total = sum(len(s.get("tags") or []) for c in lib["categories"]
                         for s in c["subcategories"])
        check(base_total > 4000, f"合并库规模正常 ({base_total} 标签)")

        print("\n  A. derive 推导")
        tag, hints = derive.derive_tag("throwing knives", "飞刀", "prop", "武器装备",
                                       sub_id=slot_id)
        check(tag["type"] == "content", "type 与同类存量一致 (content, 不是 other)")
        check(tag["axis"] == "prop", "axis 推到 prop")
        check(tag["priority"] == 50 and tag["rarity"] == "common", "priority/rarity 走默认")
        check(bool(tag.get("id")), f"自动生成 id ({tag.get('id')})")
        check((hints.get("profile") or {}).get("id") == "weapon.sword",
              "词形 knives→knife 命中 weapon.sword (单复数还原生效)")
        check(bool(hints.get("needs")), f"给出待登记提示 {hints.get('needs')}")

        print("\n  B. POST /tag/derive 预览")
        r = body(run(ter.preview_derive(_Req({"en": "zzz nothing", "zh": "无",
                                              "axis": "prop", "slot_name": "日用道具"}))))
        check(r["ok"] and r["hints"]["profile"] is None, "无档案归属时不猜 (profile=None)")
        r = body(run(ter.preview_derive(_Req({"en": "", "axis": "prop"}))))
        check(not r["ok"], "空 en 被拒")

        print("\n  C. POST /tag/create")
        # ⚠ 必须用一个库里确实没有的词: 用已有的词会被去重拦下 (那是正确行为)。
        #    frost cleaver 不在库里, 词形 cleaver 命中兜底表 → weapon.sword
        r = body(run(ter.create_tag(_Req({"en": "frost cleaver", "zh": "霜刃砍刀",
                                          "slot_id": slot_id}))))
        check(r["ok"], f"新增成功 (id={r.get('tag', {}).get('id')})")
        lib2 = library.get_merged()
        _, sub2 = ter._find_slot(lib2, slot_id)
        ens = [t.get("en") for t in sub2.get("tags") or []]
        check("frost cleaver" in ens, "新标签出现在槽位里")
        total2 = sum(len(s.get("tags") or []) for c in lib2["categories"]
                     for s in c["subcategories"])
        check(total2 == base_total + 1, f"总数 +1 ({base_total} -> {total2}), 其余未被墓碑误删")
        r = body(run(ter.create_tag(_Req({"en": "frost cleaver", "slot_id": slot_id}))))
        check((not r["ok"]) and "已有" in r.get("error", ""), "重复新增被拒 (幂等)")
        r = body(run(ter.create_tag(_Req({"en": "throwing knives", "slot_id": slot_id}))))
        check((not r["ok"]) and "已有" in r.get("error", ""),
              "库里已有的词也被去重拦下")

        print("\n  D. POST /tag/update")
        tid = body(run(ter.preview_derive(_Req({"en": "frost cleaver", "axis": "prop",
                                                "slot_name": "武器装备",
                                                "slot_id": slot_id}))))["tag"]["id"]
        r = body(run(ter.update_tag(_Req({"id": tid, "fields": {"weight": 1.4,
                                                                "rarity": "rare",
                                                                "zh": "霜刃砍刀组"}}))))
        check(r["ok"], "就地改 weight/rarity/zh 成功")
        _, _, t2 = ter._find_tag(library.get_merged(), tid)
        check(t2 and t2.get("weight") == 1.4, "weight 已生效")
        check(t2 and t2.get("zh") == "霜刃砍刀组", "zh 已生效")
        check(t2 and t2.get("en") == "frost cleaver", "未提交的字段原样保留")
        r = body(run(ter.update_tag(_Req({"id": tid, "fields": {"axis": "prop"}}))))
        check(not r["ok"] and "不可编辑" in r.get("error", ""), "axis 不在白名单, 被拒")
        r = body(run(ter.update_tag(_Req({"id": tid, "fields": {"rarity": "bogus"}}))))
        _, _, t3 = ter._find_tag(library.get_merged(), tid)
        check(r["ok"] is False and "非法" in str(r.get("error", "")),
              "非法 rarity 被入口明确拒绝 (而不是写进库)")
        check(t3.get("rarity") == "rare", "被拒后字段保持原值 (不静默改写)")
        r = body(run(ter.update_tag(_Req({"id": tid, "fields": {"weight": 99}}))))
        _, _, t4 = ter._find_tag(library.get_merged(), tid)
        check(r["ok"] and t4.get("weight") == 3.0,
              "weight 超上限被夹到 3.0 (与 library._validate_tags 的 (0,3] 对齐)")
        r = body(run(ter.update_tag(_Req({"id": tid, "fields": {"en": "   "}}))))
        check(r["ok"] is False, "空 en 被拒")
        r = body(run(ter.update_tag(_Req({"id": tid, "fields": {"type": "bogus"}}))))
        check(r["ok"] is False, "非法 type 被拒")
        r = body(run(ter.update_tag(_Req({"id": tid, "fields": {"priority": "abc"}}))))
        check(r["ok"] is False, "非整数 priority 被拒")
        r = body(run(ter.update_tag(_Req({"id": "no.such.tag", "fields": {"weight": 2}}))))
        check(not r["ok"], "改不存在的标签返回失败")

        print("\n  E. GET /taglib/api/axes-overview")
        ov = body(run(ter.get_axes_overview(_Req())))
        segs = {s["section"]: s for s in ov["segments"]}
        check(set(segs) == {1, 2, 3, 4, 5, 6, 9}, f"段位齐全 {sorted(segs)}")
        check(segs[1]["name"] == "质量·元信息·风格", "段名取自 SECTION_NAMES")
        check(len(segs[1]["axes"]) == 2 and len(segs[6]["axes"]) == 8,
              "段1 两轴 / 段6 八轴")
        check(segs[4]["placeholder"] is True, "段4 作品为占位 (库内暂无轴)")
        check(ov["total"] == total2, f"总数与库一致 ({ov['total']})")

        print("\n  F. GET /taglib/api/tag/incomplete")
        inc = body(run(ter.get_incomplete(_Req())))
        c = inc["counts"]
        check(inc["ok"] and inc["total"] == sum(c.values()), "三类缺口计数自洽")
        check(c["dangling_ref"] > 0, f"扫出陈旧引用 {c['dangling_ref']} 条 (互斥域/档案引用已不存在的词)")
        # 缺口数是**数据状态**, 不是接口契约: 3C 把那 11 个档案姿势词补进 pose_map 后
        # 归零, 原来写死 >0 等于把"缺口还在"当成了断言。这里锁计数合法, 数值看
        # GET /taglib/api/nl 的 uncovered (前端 NL 页直接显示)。
        check(isinstance(c["pose_no_family"], int) and c["pose_no_family"] >= 0,
              f"扫出缺句式族 {c['pose_no_family']} 条 (补完姿势词后应为 0)")
        check(c["weapon_unregistered"] > 0, f"扫出未建档武器 {c['weapon_unregistered']} 条")

    finally:
        library.USER_PATH, library.DATA_DIR = saved
        library.mirror_folder_now = real_mirror
        library._folder_hot_sync = real_hot_sync
        library.invalidate_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 64)
    if _FAILURES:
        print(f"tag_edit_test: {len(_FAILURES)} 项失败")
        for f in _FAILURES:
            print("   -", f)
        return 1
    print("tag_edit_test: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
