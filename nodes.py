"""TagLibraryNode —— 标签库节点本体与随机引擎。"""

from __future__ import annotations

import json

try:  # ComfyUI 以包方式加载 -> 相对导入; 独立脚本/测试 -> 顶层导入
    from . import library
    from . import runtime_snapshot
    from . import engine
    from . import nl
    from . import slotpolicy
except ImportError:  # pragma: no cover
    import library
    import runtime_snapshot
    import engine
    import nl
    import slotpolicy




# 手动模式查表索引缓存: (库 mtime 键, 库 dict 身份, en→标签, en→路径, id→标签)
# 库没变 (mtime 同 + get_merged 返回同一个 dict) 时手动模式零全库扫描;
# 任一变化即重建。表内容只读, 调用方不得修改 (chosen 里取的是浅拷贝)。
_index_cache: tuple | None = None


def _manual_index(merged: dict) -> tuple[dict, dict, dict]:
    """合并库 → (en_lower→标签, en_lower→(cat,sub,group), id→标签)。

    by_en/by_id 只收 enabled≠False 的标签 (与旧 _flat 口径一致, 停用标签
    落到 state 自带字段的合成兜底); en_path 收全部标签 (排除判断要看路径,
    与标签是否停用无关)。同名 en 多处出现时后写者覆盖 (与旧 dict 推导一致)。
    """
    global _index_cache
    key = (library._mtime(library.DEFAULT_PATH), library._mtime(library.EXT_PATH),
           library._mtime(library.USER_PATH))
    if _index_cache is not None and _index_cache[0] == key and _index_cache[1] is merged:
        return _index_cache[2], _index_cache[3], _index_cache[4]
    by_en: dict[str, dict] = {}
    en_path: dict[str, tuple] = {}
    by_id: dict[str, dict] = {}
    for cat in merged.get("categories", []):
        for sub in cat.get("subcategories", []):
            for t in sub.get("tags", []):
                en_l = str(t.get("en", "")).strip().lower()
                if not en_l:
                    continue
                # groups 已被 validate 摊平进 sub.tags; 先记直属路径, 组归属由下方覆盖
                en_path[en_l] = (cat, sub, None)
                if t.get("enabled", True):
                    by_en[en_l] = t
                    if t.get("id"):
                        by_id[t["id"]] = t
            for g in sub.get("groups", []) or []:
                for t in g.get("tags", []):
                    en_l = str(t.get("en", "")).strip().lower()
                    if en_l:
                        en_path[en_l] = (cat, sub, g)
    _index_cache = (key, merged, by_en, en_path, by_id)
    return by_en, en_path, by_id


def _gender_negative(neg: str, state) -> str:
    """性别锁的负向补强。

    正向槽位配额上限=1 (人数轴 / 角色身份轴都只有 1 个名额), 已经抽到词时就塞不进
    第二个主体名词 —— 实测"仅女性"配置里仍有约四分之一到三分之一的提示词没有任何
    女性主体名词, 画面性别只能靠角色 LoRA 撑。负向不受槽位配额约束, 改从这里压制异性。
    """
    if not neg:
        return neg
    g = str(state.get("gender") or "").lower()
    if g == "female":
        extra = "1boy, 2boys, multiple boys, male focus"
    elif g == "male":
        extra = "1girl, 2girls, multiple girls, female focus"
    else:
        return neg
    if extra.split(",")[0].strip() in neg:
        return neg
    return (neg.rstrip(", ") + ", " + extra)


class TagLibraryNode:
    CATEGORY = "TagLibrary"
    FUNCTION = "build"
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("positive", "tags_preview", "negative")
    OUTPUT_NODE = False
    # Anima 官方推荐负向块 (memory 口径) + 常用缺陷词 —— tag group:image composition
    # 的 Flaws/Quality 词源。1.8.0 起作为第三输出直接可连 negative CLIPTextEncode。
    NEGATIVE_PRESET = (
        "worst quality, low quality, score_1, score_2, score_3, artist name, "
        "blurry, jpeg artifacts, chromatic aberration, bad anatomy, bad hands, "
        "extra digits, fewer digits, missing fingers, watermarks, signature, username"
    )
    DESCRIPTION = (
        "🏷 标签库: 在节点面板上挑选/随机组合标签, 输出拼好的提示词。\n"
        "▸ 输出 positive → 连 CLIPTextEncode 的 text\n"
        "▸ 输出 tags_preview → 接 Preview Text 可查看实际输出\n"
        "▸ 输出 negative → Anima 官方推荐负向块, 连负向 CLIPTextEncode\n"
        "▸ 输入 prefix/suffix (可选) → 上游文本拼接在标签前后\n"
        "▸ 面板 ➕ 添加标签 | 🎲 换随机种子 | NSFW 开关控制 🔞 标签\n"
        "▸ 出图元数据: PNG 信息自动写入 TagLibrary 键 (实际出词/模式/种子), 读取工具可见"
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
            # 执行期把实际出词写进 extra_pnginfo (字典引用直写) → SaveImage 落图时随
            # 元数据一起嵌入 PNG, 解决"prompt 元数据里 text 只存链接引用、看不到最终提示词"
            "hidden": {"extra_pnginfo": "EXTRA_PNGINFO", "unique_id": "UNIQUE_ID"},
        }

    # 旧版参数 → 新 selection_state 字段的映射 (兼容旧工作流, 值并入 state 不丢)
    # (pinned_required 已移除: 钉选必含现在常开, 旧工作流残留值直接忽略;
    #  min_tags/max_tags 已随 v3 签名退役, 旧工作流残留值并入 state 后无人读取)
    LEGACY_OPT_KEYS = (
        "category_weights", "search_text",
        "separator", "use_weights_syntax", "dedupe",
    )

    # ------------------------------------------------------ v2 auto (引擎)

    def _build_auto(self, lib, state: dict, seed: int, *, nsfw_on: bool,
                    avoid_conflicts: bool, search_text: str, category_weights,
                    use_weights_syntax: bool, dedupe: bool,
                    separator: str, prefix: str | None, suffix: str | None,
                    exclude_keys: set):
        """1.3.0 自动模式: 原子档案束引擎 (engine.run_auto)。

        组互斥(R1)/跨池规则(R2)/资源预算(R3)/状态槽(R4) 全部在抽取时算账,
        武器姿势由档案束原子带出; 本方法只做格式化与回显。
        """
        snap = runtime_snapshot.get_snapshot(lib)
        cfg = engine.resolve_config(state, lib.get("settings") or {})
        weights_map = self._safe_json(category_weights)

        res = engine.run_auto(snap, state, seed,
                              nsfw_on=nsfw_on, avoid_conflicts=avoid_conflicts,
                              search_text=search_text, cat_weights=weights_map,
                              config=cfg)

        echo_items = []
        tags = []
        for p in res.picks:
            echo_items.append({"en": p.en, "zh": p.zh, "cat": p.cat,
                               "nsfw": p.nsfw, "gender": p.gender,
                               "enabled": True,
                               **({"bundle": p.bundle, "src": p.source}
                                  if p.kind == "ext" else {})})
            tags.append(self._format_tag(
                {"en": p.en, "weight": p.weight}, use_weights_syntax))

        text = self._join_output(tags, dedupe=dedupe, separator=separator,
                                 prefix=prefix, suffix=suffix)
        # ---- NL 自然语言 (1.3.0 起是输出的一等层) ----
        # state.nl_mode: off=纯标签 / tail=末尾整段(旧行为) / auto=自动(默认, 有料就按段散句)
        # 兼容旧工作流: 没有 nl_mode 时按旧的 nl_tail 布尔值推。
        nl_mode = str(state.get("nl_mode") or "").strip().lower()
        if not nl_mode:
            nl_mode = "tail" if state.get("nl_tail", True) else "off"
        sep = separator if separator else ", "
        if nl_mode in ("auto", "inline"):
            # 1A: 散句只跟随「主体 / 动作 / 场景光影」三段, 其余保持纯标签。
            # 好处: 高质量提示词本来就不是纯标签, 也不可能全堆末尾; 且语序自然 (主语只出现一次)。
            clauses = nl.compile_clauses(snap, res.picks, seed)
            if any(clauses.values()):
                anchors = (("subject", ("count", "character")),
                           ("action", ("action",)), ("scene", ("environment", "lighting")))
                ins = {}
                for i, p in enumerate(res.picks):
                    for name, axs in anchors:
                        if not clauses.get(name) or p.axis not in axs:
                            continue
                        nxt = res.picks[i + 1].axis if i + 1 < len(res.picks) else None
                        if nxt not in axs:          # 该轴最后一个词之后插 (轴按输出次序, 不回头)
                            ins.setdefault(name, i)
                for name, i in sorted(ins.items(), key=lambda kv: -kv[1]):
                    tags.insert(i + 1, clauses[name])
                # 兜底: 桶有句但锚点轴零词 (极少数) → 拼末尾, 防生成句静默丢失
                stragglers = [clauses[n] for n, _axs in anchors
                              if clauses.get(n) and n not in ins]
                if stragglers:
                    tags.append(" ".join(stragglers))
                text = self._join_output(tags, dedupe=dedupe, separator=sep,
                                         prefix=prefix, suffix=suffix)
            elif nl_mode == "auto":
                tail = nl.compile_tail(snap, res.picks, seed)   # 散句没料 → 回落到尾段
                if tail:
                    text = (text + ". " + tail) if text and not text.endswith((".", "!", "?")) \
                        else ((text + " " + tail) if text else tail)
        elif nl_mode == "tail":
            tail = nl.compile_tail(snap, res.picks, seed)
            if tail:
                text = (text + ". " + tail) if text and not text.endswith((".", "!", "?")) \
                    else ((text + " " + tail) if text else tail)
        dropped_en = [snap.tag_text[i] for i in res.dropped_ids]
        neg = self.NEGATIVE_PRESET if state.get("negative_out", True) else ""
        neg = _gender_negative(neg, state)
        return {
            "ui": {"taglib_echo": json.dumps(echo_items, ensure_ascii=False),
                   "taglib_echo_dropped": json.dumps(dropped_en, ensure_ascii=False)},
            "result": (text, text, neg),
        }

    # ---------------------------------------------- 库遍历 / 格式化 / 过滤

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
        # Anima 官方: artist 必须带 `@` 前缀, 否则效果很弱。
        # 库内存裸名 (方便你编辑), 输出时补前缀。_cat 是库里第一级 = 轴中文名。
        if tag.get("_cat") == "画师" and text and not text.startswith("@"):
            text = "@" + text
        w = float(tag.get("weight", 1.0))
        if use_weights and abs(w - 1.0) > 1e-6:
            return f"({text}:{w:g})"
        return text

    def _record_pnginfo(self, extra_pnginfo, unique_id, text: str, mode: str, seed,
                        selection_state=None, echo_json=None) -> None:
        """本节点实际输出的提示词 → PNG 元数据 (extra_pnginfo["TagLibrary"])。

        ComfyUI 存图的 prompt 元数据里 CLIPTextEncode.text 只存 ["节点ID",0] 链接引用,
        且 auto 模式出词是执行期才确定; EXTRA_PNGINFO 是 extra_data 里那个 dict 的原
        引用 (execution.py 不拷贝), SaveImage 落图时 metadata_dict.update(整体写入),
        因此执行期在这里塞键即可随图落盘。同一 prompt 内多节点按 unique_id 去重。
        兼容两种派发形态: v2 路径给 [dict] 列表 (pyssyss ShowText 同款下标取法), 取出 dict。
        """
        if isinstance(extra_pnginfo, list):
            extra_pnginfo = next((x for x in extra_pnginfo if isinstance(x, dict)), None)
        if not isinstance(extra_pnginfo, dict) or not text:
            return
        try:
            lst = extra_pnginfo.setdefault("TagLibrary", [])
            entry = {"node": str(unique_id), "mode": mode, "seed": seed, "prompt": text}
            ens = self._echo_en_list(echo_json)
            if ens:
                entry["tags"] = ens
            lst[:] = [e for e in lst if e.get("node") != entry["node"]]
            lst.append(entry)
        except Exception:  # noqa: BLE001 — 元数据写入失败绝不影响出图
            pass
        try:
            self._rewrite_workflow_meta(extra_pnginfo, unique_id, selection_state, echo_json)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _echo_en_list(echo_json) -> list[str]:
        """echo 条目 JSON → 英文词列表 (元数据用)。坏的输入返回空表, 绝不抛。"""
        try:
            items = json.loads(echo_json) if isinstance(echo_json, str) else echo_json
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(items, list):
            return []
        return [str(it.get("en", "")).strip() for it in items
                if isinstance(it, dict) and str(it.get("en", "")).strip()]

    def _rewrite_workflow_meta(self, extra_pnginfo, unique_id, selection_state, echo_json) -> None:
        """把 workflow 段里本节点的 selection_state 改写为"本张图实际用的词"。

        拖图回 ComfyUI 的重建数据源是 PNG 里 workflow 段 (队列时 graphToPrompt 序列化),
        auto 模式的实际出词在队列之后才生成 —— 不改写的话拖图看到的是上次队列的旧状态
        (慢一拍, 参数像"没保存")。合并语义与前端 executed 回显一致, 改一处要改两处。
        """
        if not isinstance(extra_pnginfo, dict) or not echo_json or not selection_state:
            return
        wf = extra_pnginfo.get("workflow")
        if not isinstance(wf, dict):
            return
        nodes = wf.get("nodes")
        if not isinstance(nodes, list):
            return
        try:
            nid = int(str(unique_id).strip())
        except (TypeError, ValueError):
            return
        target = None
        for n in nodes:
            if (isinstance(n, dict) and n.get("type") == "TagLibraryNode"
                    and n.get("id") == nid):
                target = n
                break
        if target is None:
            return
        wv = target.get("widgets_values")
        if not isinstance(wv, list) or not wv:
            return
        try:
            state = json.loads(selection_state)
            echo = json.loads(echo_json)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(state, dict) or not isinstance(echo, list) or not echo:
            return
        merged = self._echo_merged_state(state, library.get_merged(), echo)
        if merged is None:
            return
        wv[0] = json.dumps(merged, ensure_ascii=False)

    @staticmethod
    def _echo_merged_state(state: dict, lib: dict, echo_items: list) -> dict | None:
        """复刻前端 executed 回显: 保留(钉选/手选/排除类目) + 新抽词 _auto, 按类目序排。

        与 web/taglibrary.js 的 executed 监听器同语义 (kept 过滤 → fresh 去重 → 类目序
        排序), 两边必须同步修改。返回新 state dict (不原地改), 无抽词返回 None。
        """
        if not isinstance(echo_items, list) or not echo_items:
            return None
        _by_en, en_path, _by_id = _manual_index(lib)
        cat_names = [c.get("name") or c.get("id") or ""
                     for c in lib.get("categories", [])]
        cat_idx = {name: i for i, name in enumerate(cat_names) if name}
        excluded = {str(x) for x in (state.get("exclude_categories") or [])}

        def _cat_of(en) -> str:
            p = en_path.get(str(en or "").strip().lower())
            if not p:
                return ""
            c = p[0]
            if isinstance(c, dict):
                return c.get("name") or c.get("id") or ""
            return str(c or "")

        kept: list[dict] = []
        for t in state.get("tags") or []:
            if not isinstance(t, dict):
                continue
            if t.get("pinned") or not t.get("_auto"):
                kept.append(dict(t))
                continue
            if _cat_of(t.get("en")) in excluded:
                kept.append(dict(t))
        for t in kept:
            if not t.get("_cat"):
                t["_cat"] = _cat_of(t.get("en"))

        have = {str(t.get("en") or "").strip().lower() for t in kept}
        fresh: list[dict] = []
        for it in echo_items:
            if not isinstance(it, dict):
                continue
            en = str(it.get("en") or "").strip()
            en_l = en.lower()
            if not en or en_l in have:
                continue
            have.add(en_l)
            fresh.append({
                "en": en, "zh": it.get("zh") or "",
                "nsfw": bool(it.get("nsfw")),
                "gender": it.get("gender") or "",
                "enabled": True,
                "_cat": it.get("cat") or _cat_of(en),
                "_auto": True,  # 引擎抽取, 下轮可被替换 (与前端一致)
            })

        def _sort_key(item):
            t, i = item
            c = t.get("_cat") or ""
            return (cat_idx.get(c, 999) if c else -1, i)

        merged = [t for t, _i in sorted(
            ((t, i) for i, t in enumerate(kept + fresh)), key=_sort_key)]
        return {**state, "tags": merged}

    @staticmethod
    def _join_output(tags: list[str], *, dedupe: bool, separator: str,
                     prefix: str | None, suffix: str | None) -> str:
        """标签列表 → 最终文本 (去重 + 分隔符 + 前后缀拼接)。

        manual / auto 两路共用同一口径, 避免两处各写一遍导致行为漂移。
        """
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
        parts = [p.strip() for p in (prefix or "", sep.join(tags), suffix or "")
                 if p and p.strip()]
        return sep.join(parts) if parts else ""

    def build(self, *args, **kwargs):
        result = self._build_impl(*args, **kwargs)
        # ---- PNG 元数据: manual/auto 两路在此汇合, 从返回值取最终文本单点写入 ----
        try:
            text = (result.get("result", (None,))[0]
                    if isinstance(result, dict) else
                    result[0] if isinstance(result, tuple) else None)
            mode = kwargs.get("mode")
            if mode == "random_mix":
                mode = "auto"  # 旧值归一, 与 _build_impl 同规则
            elif mode == "random_by_category":
                mode = "manual"
            try:
                seed = int(kwargs.get("seed", 0))
            except (TypeError, ValueError):
                seed = 0
            echo_json = None
            if isinstance(result, dict):
                ui = result.get("ui")
                if isinstance(ui, dict):
                    echo_json = ui.get("taglib_echo")
            self._record_pnginfo(kwargs.get("extra_pnginfo"), kwargs.get("unique_id"),
                                 text or "", str(mode), seed,
                                 selection_state=kwargs.get("selection_state"),
                                 echo_json=echo_json)
        except Exception:  # noqa: BLE001
            pass
        return result

    def _build_impl(self, selection_state: str, mode: str, seed: int,
              prefix: str | None = None,
              suffix: str | None = None, **legacy):
        # ---- 脏数据纠偏 (旧工作流 widget 错位产生的非法值, 就地兜底不炸) ----
        if mode not in ("manual", "auto"):
            mode = "auto" if mode == "random_mix" else "manual"  # 旧值迁移
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
        use_weights_syntax = bool(state.get("use_weights_syntax", False))
        dedupe = bool(state.get("dedupe", True))
        category_weights = state.get("category_weights", "{}")
        if not isinstance(category_weights, str):
            category_weights = "{}"
        search_text = str(state.get("search_text", "") or "")
        if not isinstance(use_weights_syntax, bool):
            use_weights_syntax = bool(use_weights_syntax)
        if not isinstance(dedupe, bool):
            dedupe = True

        lib = library.get_merged()
        # NSFW 二态开关: 面板 nsfw=true → 显示/输出 NSFW 标签; false(默认) → 剔除
        nsfw_on = bool(state.get("nsfw", False))
        # 性别三态: "off"(全量) / "female"(剔除男性专属) / "male"(剔除女性专属)
        gender = str(state.get("gender") or "off").strip().lower()
        if gender not in ("off", "female", "male"):
            gender = "off"
        # ⚠ 这里**不做**全库 NSFW/性别过滤拷贝: auto 路径的引擎在快照池层面处理
        # (pools_nonsfw / pools_nofemale / pools_nomale), 快照缓存键只有文件 mtime,
        # 若把过滤树喂给 get_snapshot, 编译出的快照会缺 NSFW 词, 且之后打开 NSFW
        # 开关也拿不回 (同一键命中旧快照)。manual 路径则在 chosen 层复核, 同样不需要。
        selected_ids: list[str] = list(state.get("selected") or [])
        avoid_conflicts = bool(state.get("avoid_conflicts", True))
        # 排除类目: 支持 "大类名" / "大类名/子分类名" / "大类名/子分类名/孙分类名"
        exclude_keys: set[str] = {str(x) for x in (state.get("exclude_categories") or [])}

        if mode != "manual":
            # v2 自动模式 (auto / 旧 random_mix 兼容): RandomEngine 在 RuntimeSnapshot
            # 上出词, NSFW/排除类目/互斥都在池层面处理, 不再全库复制过滤
            return self._build_auto(lib, state, seed,
                                    nsfw_on=nsfw_on,
                                    avoid_conflicts=avoid_conflicts,
                                    search_text=search_text,
                                    category_weights=category_weights,
                                    use_weights_syntax=use_weights_syntax,
                                    dedupe=dedupe,
                                    separator=separator,
                                    prefix=prefix,
                                    suffix=suffix,
                                    exclude_keys=exclude_keys)

        # ---- 手动模式: 只查已选标签, 不做全库过滤拷贝 ----
        # 规则分层 (2026-09-20 用户决策 + 合规底线):
        #   · 排除类目 → **豁免**。用户手选的词以手选为准 —— 旧行为在这里静默丢弃,
        #     用户看不出"为什么少了一个词"。语义与引擎 pin_ignore_exclude 对齐。
        #   · 性别 / NSFW 开关 → 保留 (面板分别有 .tl-gdrop / .tl-ndrop 标记, 是可见的)。
        #   · 未成年锁 → **新增拦截**。⚠ 旧手动路径完全不查这一条, 是真漏洞:
        #     手动钉选未成年年龄词 + 露骨词时引擎拦、手动不拦。
        full_by_en, _en_path, by_id = _manual_index(lib)
        chosen: list[dict] = []
        if state.get("tags"):
            for st_tag in state["tags"]:
                if not isinstance(st_tag, dict) or st_tag.get("enabled") is False:
                    continue
                en_l = str(st_tag.get("en", "")).strip().lower()
                lib_t = full_by_en.get(en_l)
                if lib_t is None:
                    lib_t = {"en": st_tag.get("en", ""), "zh": st_tag.get("zh", ""),
                             "weight": 1.0}
                else:
                    lib_t = dict(lib_t)
                # 手动输出补 @ 前缀依赖 _cat (与回显/前端同口径); 库外词查不到路径则保持原样。
                if not lib_t.get("_cat"):
                    _p = _en_path.get(en_l)
                    if _p:
                        _c0 = _p[0]
                        lib_t["_cat"] = (_c0.get("name") if isinstance(_c0, dict) else str(_c0)) or ""
                # 面板里给某个词单独调过权重 -> 以手调的为准 (手选即为准, 与
                # "豁免排除类目"同一语义)。没调过就不写这个键, 保持库默认。
                if isinstance(st_tag.get("weight"), (int, float)):
                    lib_t["weight"] = float(st_tag["weight"])
                chosen.append(lib_t)
        else:
            # v2 旧工作流 selected ids 结构仍兼容
            for i in selected_ids:
                t = by_id.get(i)
                if t is not None:
                    chosen.append(dict(t))

        # 未成年锁 (与 engine.tag_ok 同规则): 出现未成年年龄词 → 整场封禁屏蔽词。
        # 词表取快照 (出厂表 ∪ 扩展包 minor_block 词), 与自动路径同一个真源。
        _ens = {str(t.get("en", "")).strip().lower() for t in chosen}
        if _ens & set(slotpolicy.MINOR_AGE_WORDS):
            try:
                _snap = runtime_snapshot.get_snapshot(lib)
                _block = set(getattr(_snap, "minor_block_words", None)
                             or slotpolicy.MINOR_BLOCK_WORDS)
            except Exception:  # noqa: BLE001 — 快照不可用时不阻断输出, 退回出厂表
                _block = set(slotpolicy.MINOR_BLOCK_WORDS)
            chosen = [t for t in chosen
                      if str(t.get("en", "")).strip().lower() not in _block]

        if not nsfw_on:
            chosen = [t for t in chosen if not t.get("nsfw", False)]
        # 手动输出也受性别过滤 (出口级复核, 与引擎 tag_ok 同规则)
        if gender == "female":
            chosen = [t for t in chosen if str(t.get("gender") or "").lower() != "male"]
        elif gender == "male":
            chosen = [t for t in chosen if str(t.get("gender") or "").lower() != "female"]
        tags = [self._format_tag(t, use_weights_syntax) for t in chosen]

        text = self._join_output(tags, dedupe=dedupe, separator=separator,
                                 prefix=prefix, suffix=suffix)
        neg = self.NEGATIVE_PRESET if state.get("negative_out", True) else ""
        neg = _gender_negative(neg, state)
        return (text, text, neg)

    @staticmethod
    def _safe_json(raw: str | None) -> dict:
        try:
            data = json.loads(raw or "{}")
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}



NODE_CLASS_MAPPINGS = {"TagLibraryNode": TagLibraryNode}
NODE_DISPLAY_NAME_MAPPINGS = {"TagLibraryNode": "🏷 标签库 Tag Library"}
