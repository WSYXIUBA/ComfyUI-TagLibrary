"""TagLibraryNode —— 标签库节点本体与随机引擎。"""

from __future__ import annotations

import json
import random
from typing import Any

import gc as _gc
import time as _tmod

_gc_t0 = 0.0


def _gc_cb(phase, info):
    global _gc_t0
    if phase == "start":
        _gc_t0 = _tmod.perf_counter()
    else:
        _d = (_tmod.perf_counter() - _gc_t0) * 1000
        if _d > 200:
            print(f"[TagLibrary] 🗑 GC gen{info['generation']} 暂停 {_d:.0f}ms (进程级, 与本插件计算量无关)")


try:
    _gc.callbacks.append(_gc_cb)
except Exception:
    pass

try:  # ComfyUI 以包方式加载 -> 相对导入; 独立脚本/测试 -> 顶层导入
    from . import library
    from . import tagconflicts
    from . import runtime_snapshot
    from . import random_engine
except ImportError:  # pragma: no cover
    import library
    import tagconflicts
    import runtime_snapshot
    import random_engine


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
        """v3 极简签名: 节点参数区只留 [模式/种子/NSFW] + selection_state。

        其余可调项 (数量/分隔符/权重语法/去重/过滤词/排除类目等) 全部收纳进
        selection_state JSON, 由节点内面板管理 —— 单一数据源, 无重复参数。
        """
        return {
            "required": {
                "selection_state": ("STRING", {
                    "default": "{}",
                    "multiline": False,
                    "tooltip": "节点面板状态 (自动维护, 勿手改)",
                }),
                "mode": (["manual", "auto"],
                         {"tooltip": "manual=手动选签+填充 / auto=自动按排除类目随机组合"}),
                "seed": ("INT", {"default": 0, "min": 0,
                                 "max": 0xffffffffffffffff,
                                 "tooltip": "随机种子, 同 seed 同结果; 面板 🎲ROLL 换随机数"}),
            },
            "optional": {
                "prefix": ("STRING", {"forceInput": True,
                                      "tooltip": "⬅️ 可选: 上游文本会拼在标签前面 (如质量词/LoRA触发词)"}),
                "suffix": ("STRING", {"forceInput": True,
                                      "tooltip": "⬅️ 可选: 上游文本拼在标签后面"}),
            },
        }

    # 旧版参数 → 新 selection_state 字段的映射 (兼容旧工作流, 值并入 state 不丢)
    LEGACY_OPT_KEYS = (
        "min_tags", "max_tags", "category_weights", "search_text",
        "separator", "use_weights_syntax", "dedupe", "pinned_required",
    )

    # ------------------------------------------------------ v2 auto (引擎)

    def _build_auto(self, lib, state: dict, seed: int, mode: str, *, nsfw_on: bool,
                    avoid_conflicts: bool, search_text: str, category_weights,
                    pinned_required: bool, use_weights_syntax: bool, dedupe: bool,
                    separator: str, prefix: str | None, suffix: str | None,
                    exclude_keys: set):
        """v2 自动模式: RandomEngine 在 RuntimeSnapshot 上出词 (Fast/Smart)。

        NSFW / 排除类目 / 互斥让位 / 配额全部在引擎池层面处理;
        本方法只做: 引擎调用 → 顺序组装 → 权重语法/去重/prefix/suffix → 回显。
        """
        snap = runtime_snapshot.get_snapshot(lib)
        cfg = random_engine.resolve_config(state, lib.get("settings") or {})
        weights_map = self._safe_json(category_weights)
        recent = getattr(self, "_recent_sets", None)
        if recent is None:
            recent = self._recent_sets = []

        # diversity 组合撞车时有限重抽
        res = None
        for attempt in range(random_engine.MAX_REROLL):
            res = random_engine.run_auto(snap, state, seed + attempt,
                nsfw_on=nsfw_on, avoid_conflicts=avoid_conflicts,
                search_text=search_text, cat_weights=weights_map,
                config=cfg, recent_sets=recent)
            if cfg.get("engine") != "smart":
                break
            if not random_engine.combo_is_recent(recent,
                                                 res.fixed_ids + res.rest_ids):
                break
        random_engine.note_combination(recent, res.fixed_ids + res.rest_ids, cfg)

        ordered = (res.fixed_ids + res.rest_ids if pinned_required
                   else res.rest_ids + res.fixed_ids[:len(res.fixed_ids)])

        echo_items = []
        tags = []
        seen_cat = snap.cat_names
        cat_of_sub, sub_of = snap.cat_of_sub, snap.sub_of
        for i in ordered:
            d = {"en": snap.tag_text[i], "weight": snap.base_weights[i],
                 "zh": snap.tag_zh[i], "nsfw": bool(snap.nsfw_flag[i]),
                 "gender": ("female" if snap.gender_flag[i] == 1 else
                            "male" if snap.gender_flag[i] == 2 else "")}
            d["_cat"] = seen_cat[cat_of_sub[sub_of[i]]]
            echo_items.append({"en": d["en"], "zh": d["zh"], "cat": d["_cat"],
                               "nsfw": d["nsfw"], "gender": d["gender"], "enabled": True})
            tags.append(self._format_tag(d, use_weights_syntax))

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
        # 被 mutex 让位的标签 (少量, 前端灰显+删除线)
        dropped_en = [snap.tag_text[i] for i in res.mutex_dropped_ids]
        return {
            "ui": {"taglib_echo": json.dumps(echo_items, ensure_ascii=False),
                   "taglib_echo_dropped": json.dumps(dropped_en, ensure_ascii=False)},
            "result": (text, text),
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
    def _apply_nsfw(lib: dict, nsfw_on: bool, gender: str = "off") -> dict:
        """nsfw_on=False 剔除 nsfw 标签; True 全量。
        gender: "off" 全量 / "female" 剔除男性专属 / "male" 剔除女性专属。"""
        g = str(gender or "off").strip().lower()
        if nsfw_on and g == "off":
            return lib

        def keep_tag(t: dict) -> bool:
            if not nsfw_on and bool(t.get("nsfw", False)):
                return False
            tg = str(t.get("gender") or "").strip().lower()
            if g == "female" and tg == "male":
                return False
            if g == "male" and tg == "female":
                return False
            return True

        out_cats = []
        for cat in lib.get("categories", []):
            cat = dict(cat)
            subs = []
            for sub in cat.get("subcategories", []):
                sub = dict(sub)
                sub["tags"] = [t for t in sub.get("tags", []) if keep_tag(t)]
                subs.append(sub)
            cat["subcategories"] = subs
            out_cats.append(cat)
        return {**lib, "categories": out_cats}

    def build(self, *args, **kwargs):
        import time as _t
        _t0 = _t.perf_counter()
        result = self._build_impl(*args, **kwargs)
        _ms = (_t.perf_counter() - _t0) * 1000
        if _ms > 50:  # 正常应在个位数 ms; 超标才打日志便于排查
            mode = kwargs.get("mode") or (args[1] if len(args) > 1 else "?")
            print(f"[TagLibrary] ⏱ build 耗时 {_ms:.0f}ms (mode={mode})")
        return result

    def _build_impl(self, selection_state: str, mode: str, seed: int,
              prefix: str | None = None,
              suffix: str | None = None, **legacy):
        # ---- 脏数据纠偏 (旧工作流 widget 错位产生的非法值, 就地兜底不炸) ----
        if mode not in ("manual", "auto"):
            mode = "auto" if mode == "random_mix" else "manual"  # 旧值迁移
        _auto_chosen = None  # auto 模式抽取的原始标签 (回传前端面板用)
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = 0

        # ---- 解析面板状态 ----
        try:
            state = json.loads(selection_state or "{}")
        except json.JSONDecodeError:
            state = {}
        if not isinstance(state, dict):
            state = {}

        # ---- v2 旧工作流兼容: 老参数若以 kwargs 传入, 并入 state (不丢用户设置) ----
        for key in self.LEGACY_OPT_KEYS:
            if key in legacy and legacy[key] is not None:
                state.setdefault(key, legacy[key])

        separator = state.get("separator", "comma")
        if separator not in ("comma", "space"):
            separator = "comma"
        try:
            min_tags = max(0, int(state.get("min_tags", 3)))
        except (TypeError, ValueError):
            min_tags = 3
        try:
            max_tags = max(0, int(state.get("max_tags", 8)))
        except (TypeError, ValueError):
            max_tags = 8
        if max_tags == 0:
            max_tags = max(min_tags, 1)
        if min_tags > max_tags:
            min_tags, max_tags = max_tags, min_tags
        use_weights_syntax = bool(state.get("use_weights_syntax", False))
        dedupe = bool(state.get("dedupe", True))
        pinned_required = bool(state.get("pinned_required", True))
        category_weights = state.get("category_weights", "{}")
        if not isinstance(category_weights, str):
            category_weights = "{}"
        search_text = str(state.get("search_text", "") or "")
        exclude_keys_state = state.get("exclude_categories") or []
        if not isinstance(use_weights_syntax, bool):
            use_weights_syntax = bool(use_weights_syntax)
        if not isinstance(dedupe, bool):
            dedupe = True
        if not isinstance(pinned_required, bool):
            pinned_required = True

        lib = library.get_merged()
        # NSFW 二态开关: 面板 nsfw=true → 显示/输出 NSFW 标签; false(默认) → 剔除
        nsfw_on = bool(state.get("nsfw", False))
        # 性别三态: "off"(全量) / "female"(剔除男性专属) / "male"(剔除女性专属)
        gender = str(state.get("gender") or "off").strip().lower()
        if gender not in ("off", "female", "male"):
            gender = "off"
        lib = self._apply_nsfw(lib, nsfw_on, gender)

        selected_ids: list[str] = list(state.get("selected") or [])
        pinned_ids: set[str] = set(state.get("pinned") or [])
        avoid_conflicts = bool(state.get("avoid_conflicts", True))
        # 排除类目: 支持 "大类名" / "大类名/子分类名" / "大类名/子分类名/孙分类名"
        exclude_keys: set[str] = {str(x) for x in (state.get("exclude_categories") or [])}

        if mode != "manual":
            # v2 自动模式 (auto / 旧 random_mix 兼容): RandomEngine 在 RuntimeSnapshot
            # 上出词, NSFW/排除类目/互斥都在池层面处理, 不再全库复制过滤
            return self._build_auto(lib, state, seed, mode,
                                    nsfw_on=nsfw_on,
                                    avoid_conflicts=avoid_conflicts,
                                    search_text=str(state.get("search_text", "") or ""),
                                    category_weights=category_weights,
                                    pinned_required=pinned_required,
                                    use_weights_syntax=use_weights_syntax,
                                    dedupe=dedupe,
                                    separator=separator,
                                    prefix=prefix,
                                    suffix=suffix,
                                    exclude_keys=exclude_keys)

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
            if not nsfw_on:
                chosen = [t for t in chosen if not t.get("nsfw", False)]
            # 手动输出也受性别过滤 (lib 已被 _apply_nsfw 过滤, 但 en 查不到时走 full_by_en 补底 → 再拦一道)
            if gender == "female":
                chosen = [t for t in chosen if str(t.get("gender") or "").lower() != "male"]
            elif gender == "male":
                chosen = [t for t in chosen if str(t.get("gender") or "").lower() != "female"]
            tags = [self._format_tag(t, use_weights_syntax) for t in chosen]

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
        # auto 模式: 把实际抽到的标签回传给前端面板 (executed 事件 → 面板自动刷新显示)
        if mode == "auto":
            if _auto_chosen:
                echo_items = [{"en": str(t.get("en", "")),
                               "zh": t.get("zh") or "",
                               "cat": t.get("_cat", ""),
                               "nsfw": bool(t.get("nsfw")),
                               "gender": str(t.get("gender") or ""),
                               "enabled": True} for t in _auto_chosen]
            else:
                echo_items = [{"en": p.strip(), "zh": "", "cat": "", "nsfw": False,
                               "enabled": True}
                              for p in tags]
            return {
                "ui": {"taglib_echo": json.dumps(echo_items, ensure_ascii=False)},
                "result": (text, text),
            }
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
