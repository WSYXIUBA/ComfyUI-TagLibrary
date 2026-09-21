"""迁移 profiles.json 的 mount_sub: 旧大类路径 → S4 之后的轴路径。

## 为什么需要

S4 把库的第一级从「9 大类」换成了「13 条轴」, 但 `profiles.json` 的
`mount_sub` 一直是手写字符串, 没跟着迁移。实测 18 个档案全部还写着
`人物主体/武器装备` / `人物主体/日用道具` / `人物主体/乐器与运动` /
`人物主体/食物饮品` —— 而 `人物主体` 这个大类**在库里已经不存在了**。

影响: 该字段目前只被 `profiles.validate_profiles` 做"非空"校验, 以及前端当
标签显示 + 行内编辑, 所以不会当场炸; 但它是一条**指向不存在路径的悬空引用**,
任何以后按它解析挂载槽位的逻辑都会静默失败, 而且界面上摆着一条错路径。

## 做法

按 `大类/子类` 拆开, 用 `axes.axis_of(大类, 子类)` 推出轴 id, 再换回轴中文名。
`axis_of` 本身兼容新旧两种结构 (先查 SUB_TO_AXIS_V2 再查旧 SUB_TO_AXIS),
所以这个迁移对"新名字的 mount_sub"是幂等的 —— 已经正确的值不会被改。

    python tools/migrate_profile_mount.py            # 试运行, 只报告
    python tools/migrate_profile_mount.py --apply    # 真正写盘 (先 .bak)
"""

from __future__ import annotations

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import axes      # noqa: E402

# 直接算路径, 不 import profiles —— 免得被它的模块级依赖牵着走
PROFILES_PATH = os.path.join(ROOT, "data", "default", "taglib", "profiles.json")
_BACKUP = PROFILES_PATH + ".bak"


def new_path(old: str) -> str:
    """`大类/子类` → `轴中文名/子类`。推不出轴就原样返回 (不猜)。"""
    parts = str(old or "").split("/")
    if len(parts) != 2:
        return old
    cat, sub = parts[0].strip(), parts[1].strip()
    if cat in axes.AXIS_ZH_TO_ID:          # 已经是轴名 → 幂等
        return old
    axis_id = axes.axis_of(cat, sub)[0]
    if not axis_id or axis_id == "misc":
        return old
    return f"{axes.AXIS_NAME_ZH.get(axis_id, axis_id)}/{sub}"


def main() -> int:
    apply = "--apply" in sys.argv
    if not os.path.exists(PROFILES_PATH):
        print("找不到 profiles.json:", PROFILES_PATH)
        return 1
    data = json.load(open(PROFILES_PATH, encoding="utf-8"))
    changed = []
    for p in data.get("profiles") or []:
        old = str(p.get("mount_sub") or "")
        new = new_path(old)
        if new != old:
            changed.append((p.get("id"), old, new))
            if apply:
                p["mount_sub"] = new
    if not changed:
        print("无需迁移 (mount_sub 已全部指向轴名)")
        return 0
    for pid, old, new in changed:
        print(f"  {pid:<18} {old}  ->  {new}")
    if not apply:
        print(f"\n试运行: {len(changed)} 项待迁移。加 --apply 真正写盘。")
        return 0
    shutil.copy2(PROFILES_PATH, _BACKUP)
    tmp = PROFILES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PROFILES_PATH)
    print(f"\n已迁移 {len(changed)} 项并写盘 (备份: {os.path.basename(_BACKUP)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
