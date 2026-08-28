"""TagLibraryNode —— 标签库节点本体与随机引擎。"""

from __future__ import annotations

import json
import random
from typing import Any

try:  # ComfyUI 以包方式加载 -> 相对导入; 独立脚本/测试 -> 顶层导入
    from . import library
    from . import tagconflicts
except ImportError:  # pragma: no cover
    import library
    import tagconflicts


class TagLibraryNode:
    CATEGORY = "纸心/prompt"
    FUNCTION = "build"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("positive", "tags_preview")
    OUTPUT_NODE = False
    DESCRIPTION = (
        "🏷 标签库: 在节点面板上挑选/随机组合标签, 输出拼好的提示词。\n"
        "▸ 输出 positive → 连 CLIPTextEncode 的 text\n"
        "▸ 输出 tags_preview → 接 Preview Text 可查看实际输出\n"
        "▸ 输入 prefix/suffix (可选) → 上游文本拼接在标签前后\n"
        "▸ 面板 ➕ 添加标签 | 🎲 换随机种子 | NSFW 开关控制 🔞 标签"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "selection_state": ("STRING", {
                    "default": "{}",
                    "multiline": False,
                    "tooltip": "节点面板状态 (自动维护, 勿手改)",
                }),
                "mode": (["manual", "random_by_category", "random_mix"],
                         {"tooltip": "manual=手动点选的启用标签 / random_by_category=每分类抽N条 / random_mix=全库混合抽取"}),
                "seed": ("INT", {"default": 0, "min": 0,
                                 "max": 0xffffffffffffffff,
                                 "tooltip": "随机种子, 同 seed 同结果; 面板 🎲ROLL 换随机数"}),
                "nsfw_mode": (["off", "on", "only"],
                              {"tooltip": "off=排除 NSFW 标签 / on=普通+NSFW 混合 / only=只出 NSFW"}),
            },
            "optional": {
                "prefix": ("STRING", {"forceInput": True,
                                      "tooltip": "⬅️ 可选: 上游文本会拼在标签前面 (如质量词/LoRA触发词)"}),
                "suffix": ("STRING", {"forceInput": True,
                                      "tooltip": "⬅️ 可选: 上游文本拼在标签后面"}),
                "min_tags": ("INT", {"default": 3, "min": 0, "max": 60,
                                     "control_after_generate": False,
                                     "tooltip": "随机模式最少输出标签数"}),
                "max_tags": ("INT", {"default": 8, "min": 0, "max": 60,
                                     "control_after_generate": False,
                                     "tooltip": "随机模式最多输出标签数 (实际取 min~max 随机, 0=只用 min_tags)"}),
                "category_weights": ("STRING", {"default": "{}",
                                                "tooltip": "分类权重 (面板自动维护)"}),
                "search_text": ("STRING", {"default": "",
                                           "tooltip": "random_mix 的过滤词 (支持中文/英文/别名)"}),
                "separator": (["comma", "space"],
                              {"tooltip": "comma=逗号分隔(推荐) / space=空格分隔"}),
                "use_weights_syntax": ("BOOLEAN", {"default": False,
                                                   "tooltip": "开启后带权重的标签输出为 (tag:1.2) 语法"}),
                "dedupe": ("BOOLEAN", {"default": True,
                                       "tooltip": "相同标签只输出一次"}),
                "pinned_required": ("BOOLEAN", {"default": True,
                                                "tooltip": "📌 钉选标签在随机模式下必定包含"}),
            },
        }

    # ------------------------------------------------------------------ engine

    @staticmethod
    def _norm(text: str) -> str:
        return (text or "").strip().lower()

    @classmethod
    def _tag_matches(cls, tag: dict, query: str) -> bool:
        q = cls._norm(query)
        if not q:
            return True
        haystacks = [
            tag.get("en", ""), tag.get("zh", ""),
            " ".join(tag.get("aliases", []) or []),
        ]
        return any(q in cls._norm(h) for h in haystacks)

    @staticmethod
    def _flat(library_data: dict) -> list[tuple[dict, str]]:
        """[(tag, category_name), ...] 顺序遍历合并后的库。"""
        rows: list[tuple[dict, str]] = []
        for cat in library_data.get("categories", []):
            cname = cat.get("name", cat.get("id", "?"))
            for sub in cat.get("subcategories", []):
                for tag in sub.get("tags", []):
                    if tag.get("enabled", True):
                        rows.append((tag, cname))
        return rows

    @staticmethod
    def _format_tag(tag: dict, use_weights: bool) -> str:
        text = tag.get("en", "").strip()
        w = float(tag.get("weight", 1.0))
        if use_weights and abs(w - 1.0) > 1e-6:
            return f"({text}:{w:g})"
        return text

    @staticmethod
    def _apply_nsfw(lib: dict, nsfw_mode: str) -> dict:
        """off=剔除nsfw标签; on=全量; only=只要nsfw (分类含任一nsfw子分类即保留)。"""
        if nsfw_mode == "on":
            return lib
        want = None if nsfw_mode == "only" else False

        def keep_tag(t: dict) -> bool:
            is_nsfw = bool(t.get("nsfw", False))
            if want is None:
                return is_nsfw
            return is_nsfw == want

        out_cats = []
        for cat in lib.get("categories", []):
            cat = dict(cat)
            subs = []
            for sub in cat.get("subcategories", []):
                sub = dict(sub)
                sub["tags"] = [t for t in sub.get("tags", []) if keep_tag(t)]
                if sub["tags"] or not want:
                    subs.append(sub)
            cat["subcategories"] = subs
            if subs or not want:
                out_cats.append(cat)
        return {**lib, "categories": out_cats}

    def build(
        self,
        selection_state: str,
        mode: str,
        seed: int,
        nsfw_mode: str = "off",
        prefix: str | None = None,
        suffix: str | None = None,
        min_tags: int = 3,
        max_tags: int = 8,
        category_weights: str = "{}",
        search_text: str = "",
        separator: str = "comma",
        use_weights_syntax: bool = False,
        dedupe: bool = True,
        pinned_required: bool = True,
    ):
        # ---- 脏数据纠偏 (旧工作流 widget 错位产生的非法值, 就地兜底不炸) ----
        if mode not in ("manual", "random_by_category", "random_mix"):
            mode = "manual"
        if nsfw_mode not in ("off", "on", "only"):
            nsfw_mode = "off"
        if separator not in ("comma", "space"):
            separator = "comma"
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = 0
        try:
            min_tags = max(0, int(min_tags))
        except (TypeError, ValueError):
            min_tags = 3
        try:
            max_tags = max(0, int(max_tags))
        except (TypeError, ValueError):
            max_tags = 8
        # max_tags=0 视为 "只用 min_tags"; lo==hi 时随机退化成固定数量
        if max_tags == 0:
            max_tags = max(min_tags, 1)
        if min_tags > max_tags:
            min_tags, max_tags = max_tags, min_tags
        if not isinstance(use_weights_syntax, bool):
            use_weights_syntax = bool(use_weights_syntax)
        if not isinstance(dedupe, bool):
            dedupe = True
        if not isinstance(pinned_required, bool):
            pinned_required = True

        lib = library.get_merged()
        lib = self._apply_nsfw(lib, nsfw_mode)
        try:
            state = json.loads(selection_state or "{}")
        except json.JSONDecodeError:
            state = {}

        selected_ids: list[str] = list(state.get("selected") or [])
        pinned_ids: set[str] = set(state.get("pinned") or [])
        avoid_conflicts = bool(state.get("avoid_conflicts", True))
        # 排除类目: 支持 "大类名" / "大类名/子分类名" / "大类名/子分类名/孙分类名"
        exclude_keys: set[str] = {str(x) for x in (state.get("exclude_categories") or [])}

        def cat_excluded(cat: dict) -> bool:
            return cat.get("name") in exclude_keys

        def sub_excluded(cat: dict, sub: dict) -> bool:
            n = cat.get("name", "")
            return (f"{n}/{sub.get('name', '')}" in exclude_keys
                    or cat_excluded(cat))

        def group_excluded(cat: dict, sub: dict, g: dict) -> bool:
            n = cat.get("name", "")
            return (f"{n}/{sub.get('name', '')}/{g.get('name', '')}" in exclude_keys
                    or sub_excluded(cat, sub))

        def tag_excluded(cat_name: str, sub: dict, g, exclude_keys: set) -> bool:
            """前端同名逻辑: 标签级排除判断。"""
            if cat_name in exclude_keys:
                return True
            if g and f"{cat_name}/{sub.get('name', '')}/{g.get('name', '')}" in exclude_keys:
                return True
            if f"{cat_name}/{sub.get('name', '')}" in exclude_keys:
                return True
            return False

        if exclude_keys:
            def keep_sub(cat: dict, sub: dict) -> bool:
                if sub_excluded(cat, sub):
                    return False
                groups = sub.get("groups") or []
                if groups:
                    # 只要有未排除的孙分类就保留该子分类, 但清除被排除的孙
                    sub = dict(sub)
                    sub["groups"] = [g for g in groups if not group_excluded(cat, sub, g)]
                    if not sub["groups"]:
                        return False
                return True

            kept_cats = []
            for cat in lib.get("categories", []):
                if cat_excluded(cat):
                    continue
                cat = dict(cat)
                cat["subcategories"] = [s for s in cat.get("subcategories", [])
                                        if keep_sub(cat, s)]
                kept_cats.append(cat)
            lib = {"version": lib.get("version", 1), "categories": kept_cats}

        tags: list[str] = []

        if mode == "manual":
            # 手动模式: 标签需要按来源层级判断是否被排除
            # 建立 en -> (cat_name, sub, group) 的映射
            full_by_en = {str(t.get("en", "")).strip().lower(): t for t, _ in self._flat(library.get_merged())}
            en_path: dict[str, tuple] = {}
            for cat in library.get_merged().get("categories", []):
                for sub in cat.get("subcategories", []):
                    for t in sub.get("tags", []):
                        en_l = str(t.get("en", "")).strip().lower()
                        en_path[en_l] = (cat, sub, None)
                        # groups 已被 validate 摊平进 sub.tags; 单独记录 group 归属
                    for g in sub.get("groups", []) or []:
                        for t in g.get("tags", []):
                            en_l = str(t.get("en", "")).strip().lower()
                            en_path[en_l] = (cat, sub, g)

            by_en = {str(t.get("en", "")).strip().lower(): t for t, _ in self._flat(lib)}
            chosen: list[dict] = []
            if state.get("tags"):
                for st_tag in state["tags"]:
                    if not isinstance(st_tag, dict) or st_tag.get("enabled") is False:
                        continue
                    en_l = str(st_tag.get("en", "")).strip().lower()
                    # 排除检查 (三级路径)
                    path = en_path.get(en_l)
                    if path:
                        cat, sub, g = path
                        if tag_excluded(cat.get("name"), sub, g, exclude_keys):
                            continue
                    lib_t = by_en.get(en_l)
                    if lib_t is None:
                        lib_t = full_by_en.get(en_l)
                    if lib_t is None:
                        lib_t = {"en": st_tag.get("en", ""), "zh": st_tag.get("zh", ""),
                                 "weight": 1.0}
                    chosen.append(dict(lib_t))
            else:
                by_id = {t.get("id"): t for t, _ in self._flat(lib)}
                chosen = [by_id[i] for i in selected_ids if i in by_id]
            if nsfw_mode == "off":
                chosen = [t for t in chosen if not t.get("nsfw", False)]
            tags = [self._format_tag(t, use_weights_syntax) for t in chosen]

        elif mode == "random_by_category":
            rng = random.Random(seed)
            cat_conf = state.get("category_random") or {}
            weights_cfg = self._safe_json(category_weights)
            chosen_en: list[str] = []
            for cat in lib.get("categories", []):
                cid = cat.get("id")
                conf = cat_conf.get(cid) or {}
                if not conf.get("enabled"):
                    continue
                pool: list[dict] = []
                for sub in cat.get("subcategories", []):
                    for tag in sub.get("tags", []):
                        if tag.get("enabled", True) and self._tag_matches(tag, search_text):
                            pool.append(tag)
                if not pool:
                    continue
                n = int(conf.get("count", 1))
                empty_p = float(conf.get("empty_chance", 0)) / 100.0
                if rng.random() < empty_p:
                    continue
                cat_weight = float(weights_cfg.get(cid, 1.0))
                effective = max(0, round(n * max(cat_weight, 0.0)))
                # 冲突避让: 先剔除与已选中同组的候选, 再抽
                if avoid_conflicts:
                    pool, _blocked = tagconflicts.filter_conflicts(pool, chosen_en)
                effective = min(effective, len(pool))
                if effective <= 0:
                    continue
                picks = rng.sample(pool, k=effective)
                chosen_en.extend(str(p.get("en", "")).strip().lower() for p in picks)
                tags.extend(self._format_tag(t, use_weights_syntax) for t in picks)

        else:  # random_mix
            rng = random.Random(seed)
            pool_all = [(t, c) for t, c in self._flat(lib)
                        if self._tag_matches(t, search_text)]
            if not pool_all:
                tags = []
            else:
                weights_map = self._safe_json(category_weights)

                def _weight(pair):
                    return max(float(weights_map.get(pair[1], 1.0)), 0.001)

                lo, hi = min(min_tags, max_tags), max(min_tags, max_tags)
                n = rng.randint(lo, hi)
                pool_dict = {t.get("id"): t for t, _ in pool_all}
                fixed = [pool_dict[i] for i in pinned_ids if i in pool_dict]
                fixed_lower = [str(t.get("en", "")).strip().lower() for t in fixed]
                rest_pool = [(t, c) for t, c in pool_all
                             if t.get("id") not in pinned_ids
                             and str(t.get("en", "")).strip().lower() not in fixed_lower]
                remain = max(0, n - len(fixed)) if pinned_required else n
                if avoid_conflicts:
                    # 贪心抽取: 逐个抽、命中已占用互斥组的候选跳过补位
                    rest: list[dict] = []
                    banned: list[set] = []
                    lowers_used = set(fixed_lower)
                    attempts = 0
                    guard = remain * 12 + 200  # 防死循环上限
                    while len(rest) < remain and attempts < guard and rest_pool:
                        attempts += 1
                        pick_pair = weighted_sample(rest_pool, 1, _weight, rng)
                        if not pick_pair:
                            break
                        pick = pick_pair[0][0]  # rest_pool 元素是 (tag, category_name)
                        plo = str(pick.get("en", "")).strip().lower()
                        hit_ban = any(plo in b for b in banned)
                        if not hit_ban:
                            for g in tagconflicts.get_groups():
                                gs = set(g["tags"])
                                if plo in gs:
                                    if gs & lowers_used:
                                        hit_ban = True
                                    else:
                                        banned.append(gs)
                                    break
                        if hit_ban:
                            rest_pool = [(t, c) for t, c in rest_pool
                                         if t.get("id") != pick.get("id")]
                            continue
                        rest.append(pick)
                        lowers_used.add(plo)
                        rest_pool = [(t, c) for t, c in rest_pool
                                     if t.get("id") != pick.get("id")]
                else:
                    rest = [t for t, _ in weighted_sample(rest_pool, remain, _weight, rng)]
                all_tags = fixed + rest if pinned_required else rest + fixed[:n]
                tags = [self._format_tag(t, use_weights_syntax) for t in all_tags]

        # 去重保序
        if dedupe:
            seen: set[str] = set()
            uniq = []
            for t in tags:
                k = t.lower()
                if k not in seen:
                    seen.add(k)
                    uniq.append(t)
            tags = uniq

        sep = ", " if separator == "comma" else " "
        parts = [p.strip() for p in (prefix or "", sep.join(tags), suffix or "") if p and p.strip()]
        text = sep.join(parts) if parts else ""
        return (text, text)

    @staticmethod
    def _safe_json(raw: str | None) -> dict:
        try:
            data = json.loads(raw or "{}")
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def weighted_sample(pool: list[Any], k: int, weight_fn, rng: random.Random) -> list[Any]:
    """Efraimidis-Spirakis 加权不放回抽样: 按 -U^(1/w) 取最大 k 个, O(n log n)。"""
    if k <= 0 or not pool:
        return []
    keyed = []
    for item in pool:
        u = rng.random()
        while u <= 0.0:
            u = rng.random()
        keyed.append((-(u ** (1.0 / max(weight_fn(item), 1e-9))), item))
    keyed.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in keyed[:k]]


NODE_CLASS_MAPPINGS = {"TagLibraryNode": TagLibraryNode}
NODE_DISPLAY_NAME_MAPPINGS = {"TagLibraryNode": "🏷 标签库 Tag Library"}
