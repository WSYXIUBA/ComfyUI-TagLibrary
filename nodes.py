"""TagLibraryNode —— 标签库节点本体与随机引擎。"""

from __future__ import annotations

import json
import random
from typing import Any

try:  # ComfyUI 以包方式加载 -> 相对导入; 独立脚本/测试 -> 顶层导入
    from . import library
except ImportError:  # pragma: no cover
    import library


class TagLibraryNode:
    CATEGORY = "纸心/prompt"
    FUNCTION = "build"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("positive", "tags_preview")
    OUTPUT_NODE = False
    DESCRIPTION = (
        "结构化标签库: 多分类标签点选 + 按类随机 + 组合随机, "
        "输出 STRING 直连 CLIPTextEncode。⚙ 按钮打开标签库管理页。"
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
                "mode": (["manual", "random_by_category", "random_mix"],),
                "seed": ("INT", {"default": 0, "min": 0,
                                 "max": 0xffffffffffffffff}),
            },
            "optional": {
                "prefix": ("STRING", {"forceInput": True,
                                      "tooltip": "上游文本, 会拼在输出最前面"}),
                "suffix": ("STRING", {"forceInput": True,
                                      "tooltip": "上游文本, 会拼在输出最后面"}),
                "min_tags": ("INT", {"default": 3, "min": 0, "max": 60}),
                "max_tags": ("INT", {"default": 8, "min": 1, "max": 60}),
                "category_weights": ("STRING", {"default": "{}"}),
                "search_text": ("STRING", {"default": "",
                                           "tooltip": "random_mix 的过滤词 (中英/别名)"}),
                "separator": (["comma", "space"],),
                "use_weights_syntax": ("BOOLEAN", {"default": False}),
                "dedupe": ("BOOLEAN", {"default": True}),
                "pinned_required": ("BOOLEAN", {"default": True,
                                                "tooltip": "随机模式下钉选标签必含"}),
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

    def build(
        self,
        selection_state: str,
        mode: str,
        seed: int,
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
        lib = library.get_merged()
        try:
            state = json.loads(selection_state or "{}")
        except json.JSONDecodeError:
            state = {}

        selected_ids: list[str] = list(state.get("selected") or [])
        pinned_ids: set[str] = set(state.get("pinned") or [])

        tags: list[str] = []

        if mode == "manual":
            by_id = {t.get("id"): t for t, _ in self._flat(lib)}
            chosen = [by_id[i] for i in selected_ids if i in by_id]
            tags = [self._format_tag(t, use_weights_syntax) for t in chosen]

        elif mode == "random_by_category":
            rng = random.Random(seed)
            cat_conf = state.get("category_random") or {}
            weights_cfg = self._safe_json(category_weights)
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
                # 分类权重 -> 用加权随机决定实际抽取数在 [ceil(n*w*空抽), ...] 不搞复杂化:
                empty_p = float(conf.get("empty_chance", 0)) / 100.0
                if rng.random() < empty_p:
                    continue
                cat_weight = float(weights_cfg.get(cid, 1.0))
                effective = max(0, round(n * max(cat_weight, 0.0)))
                picks = rng.sample(pool, k=min(effective, len(pool)))
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
                # 钉选必含
                pool_dict = {t.get("id"): t for t, _ in pool_all}
                fixed = [pool_dict[i] for i in pinned_ids if i in pool_dict]
                rest_pool = [p for p in pool_all if p[0].get("id") not in pinned_ids]
                remain = max(0, n - len(fixed)) if pinned_required else n
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
