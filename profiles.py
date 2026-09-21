"""词条档案 (1.3.0) —— 武器/物体档案: 姿势挂在档案下, 带资源消耗/状态/NL 句式。

数据文件: data/default/profiles.json
  { "version": 1, "profiles": [ {...}, ... ] }

档案 schema:
  id            "weapon.katana"
  name/zh       显示名
  mount_sub     挂载的库内子类路径 ("人物主体/武器装备") — 档案身份词与池
  tags          身份标签 (抽出该武器时输出, 若在库中则复用库内 id)
  max_slots     可同时出现几把 (默认 1; 双持=2)
  dual_policy   "forbidden" | "same_only" | "allowed" (M2 用)
  poses[]       姿势条目:
      id        唯一
      tags      标签序列 (输出相邻, 束内不拆)
      hands     占用手数 (默认 1); gaze 1=占视线 (默认 0)
      legs      默认 0
      state_slot  {slot: value} — 同槽位不同值互斥 (weapon_state: drawn/sheathed/on_back)
      weight    抽取权重 (默认 1.0)
      nl        自然语言句式变体 (M3 编译用, M1 允许为空)
  extras[]      配件条目 (不占 prop 轴; 同 state_slot 机制)

冷路径加载/校验, 结果编进 RuntimeSnapshot。热路径只读编译产物。
"""

from __future__ import annotations

import json
import os

try:  # ComfyUI 包加载 -> 相对导入; 独立脚本 -> 顶层导入
    from . import jsonio
    from . import datapaths
except ImportError:  # pragma: no cover
    import jsonio
    import datapaths

PROFILES_PATH = os.path.join(datapaths.LIBRARY_DIR, "profiles.json")

# 全身资源预算 (方案 §十一: hands=2 arms=2 legs=2 gaze=1)
BODY_RESOURCES = {"hands": 2, "arms": 2, "legs": 2, "gaze": 1}


class ProfileError(Exception):
    pass


def _mtime() -> float:
    try:
        return os.stat(PROFILES_PATH).st_mtime
    except OSError:
        return 0.0


def load_profiles() -> dict:
    """读 profiles.json; 文件缺失 = 空档案 (不炸)。"""
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "profiles": []}
    if not isinstance(data, dict):
        return {"version": 1, "profiles": []}
    data.setdefault("version", 1)
    data.setdefault("profiles", [])
    return data


def save_profiles(data: dict) -> None:
    jsonio.atomic_write_json(PROFILES_PATH, data)


def validate_profiles(data: dict) -> tuple[list[dict], list[dict]]:
    """返回 (合法档案列表, 错误清单)。错误档案整体跳过, 不影响其它。"""
    out: list[dict] = []
    errs: list[dict] = []
    seen_pid: set[str] = set()
    for p in data.get("profiles") or []:
        try:
            _v_one(p, seen_pid, errs)
        except ProfileError as e:
            errs.append({"id": str(p.get("id") if isinstance(p, dict) else "?"),
                         "reason": str(e)})
            continue
        out.append(p)
    return out, errs


def _bad(p, cond, msg):
    if cond:
        raise ProfileError(msg)


def _v_one(p, seen_pid: set, errs: list) -> None:
    _bad(p, not isinstance(p, dict), "档案必须是对象")
    pid = str(p.get("id") or "").strip()
    _bad(p, not pid, "缺少 id")
    _bad(p, pid in seen_pid, f"id 重复: {pid}")
    _bad(p, not str(p.get("mount_sub") or "").strip(), "缺少 mount_sub")
    tags = p.get("tags") or []
    _bad(p, not isinstance(tags, list) or not tags, "缺少身份 tags")
    seen_pose: set[str] = set()
    for pose in (p.get("poses") or []):
        _bad(p, not isinstance(pose, dict), "pose 必须是对象")
        _bad(p, not str(pose.get("id") or "").strip(), "pose 缺少 id")
        _bad(p, pose.get("id") in seen_pose, f"pose id 重复: {pose.get('id')}")
        seen_pose.add(pose["id"])
        _bad(p, not (pose.get("tags") or []), "pose 缺少 tags")
        h = pose.get("hands", 1)
        _bad(p, not isinstance(h, (int, float)) or h < 0 or h > BODY_RESOURCES["hands"],
             f"pose {pose['id']} hands 越界: {h}")
        g = pose.get("gaze", 0)
        _bad(p, not isinstance(g, (int, float)) or g < 0 or g > BODY_RESOURCES["gaze"],
             f"pose {pose['id']} gaze 越界: {g}")
        for entry in (p.get("poses") or []) + (p.get("extras") or []):
            ss = entry.get("state_slot") or {}
            _bad(p, not isinstance(ss, dict), "state_slot 必须是对象")
    seen_pid.add(pid)


# ---------------------------------------------------------------- 编译产物

class PoseEntry:
    """编译后的单条姿势/配件 (档案与 tags_ext 共用)。"""

    __slots__ = ("pid", "pose_id", "tags", "hands", "gaze", "weight",
                 "state_slot", "nl", "is_extra", "zh", "implies", "conflicts_with",
                 "state_slot_keys", "axis", "comp_groups")

    def __init__(self, pid: str, pose: dict, is_extra: bool = False):
        self.pid = pid
        self.pose_id = str(pose.get("id") or "")
        self.tags = [str(t).strip() for t in (pose.get("tags") or []) if str(t).strip()]
        self.hands = int(pose.get("hands", 1 if not is_extra else 0) or 0)
        self.gaze = int(pose.get("gaze", 0) or 0)
        self.weight = float(pose.get("weight", 1.0) or 0.0)
        self.state_slot = dict(pose.get("state_slot") or {})
        self.nl = list(pose.get("nl") or [])
        self.is_extra = is_extra
        self.zh = str(pose.get("zh") or "")
        # implies: 束内自带的库内标签 (如 standing) — 编译时并入输出与账本
        self.implies = [str(x).strip() for x in (pose.get("implies") or [])
                        if str(x).strip()]
        # conflicts_with: 束级黑名单 (如 姿势 ↔ hair over eyes) → 派生组名
        self.conflicts_with = [str(x).strip().lower()
                               for x in (pose.get("conflicts_with") or [])]
        self.state_slot_keys = frozenset(
            f"{pid}:{k}={v}" for k, v in self.state_slot.items())
        self.axis = "appearance" if is_extra else "action"
        self.comp_groups = self.extra_groups  # 快照编译期会被扩成全集

    @property
    def extra_groups(self) -> frozenset:
        """束级互斥派生组: m:{pid}:{pose_id} —— 所有成员 tag 共享,
        被黑名单词也挂上同名组 → 组交集机制自然拦下。"""
        return frozenset({f"m:{self.pid}:{self.pose_id}"})

    def group_membership(self) -> dict[str, frozenset]:
        """{tag_lower: 该词在本束语境下应有的组名集合} (编译期补挂索引用)。"""
        g = self.extra_groups
        out = {t: g for t in (self.tags + self.implies)}
        for w in self.conflicts_with:
            out.setdefault(w, g)
        return out


class WeaponProfile:
    __slots__ = ("id", "zh", "mount_sub", "tags", "poses", "extras",
                 "max_slots", "dual_policy")

    def __init__(self, pid: str, p: dict):
        self.id = pid
        self.zh = str(p.get("zh") or p.get("name") or pid)
        self.mount_sub = str(p.get("mount_sub") or "")
        self.tags = [str(t).strip() for t in (p.get("tags") or []) if str(t).strip()]
        self.poses = [PoseEntry(pid, x, False) for x in (p.get("poses") or [])]
        self.extras = [PoseEntry(pid, x, True) for x in (p.get("extras") or [])]
        self.max_slots = int(p.get("max_slots", 1) or 1)
        self.dual_policy = str(p.get("dual_policy") or "allowed")


def compile_profiles(data: dict) -> tuple[list[WeaponProfile], list[dict]]:
    valid, errs = validate_profiles(data)
    out: list[WeaponProfile] = []
    for p in valid:
        try:
            out.append(WeaponProfile(str(p["id"]), p))
        except ProfileError as e:
            errs.append({"id": str(p.get("id")), "reason": str(e)})
    return out, errs
