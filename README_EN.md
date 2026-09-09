# 🏷 ComfyUI-TagLibrary

[中文文档](README.md) | **English**

1.3.0 core refactor: assembly axes + entry profiles + resource-budget engine + natural-language tail.
9 categories / 65 subcategories / 4300+ tags / 18 weapon & object profiles / 34 NL sentence families.
Outputs `STRING` (tag body + optional English NL tail) — just Convert to Input on any workflow's `CLIPTextEncode.text`. 1-4ms per generation.

![license](https://img.shields.io/badge/license-MIT-green) ![comfyui](https://img.shields.io/badge/ComfyUI-custom--node-blue) ![tests](https://img.shields.io/badge/tests-passing-brightgreen)

## The 1.3.0 Architecture (four pillars)

- **Assembly axes**: the real skeleton of the library is no longer the 2-level tree — all 4356 tags are re-aggregated onto 12 axes (quality / headcount / identity / appearance / outfit / props & weapons / action / scene …). The tree becomes a browsing skin: the picker toggles between "🌲 Category tree" and "🎯 Assembly axes", and every chip shows both its axis and tree origin on hover.
- **Weapon & object profiles (⚔ bundles)**: weapon poses no longer live in a global pool. 7 weapon profiles (katana/sword/greatsword/gun/bow/staff/polearm) + 11 everyday-object profiles (phone/book/umbrella/guitar/cup/camera/mic/flower/binoculars/snack/pen) carry pose bundles: each pose = tag group + hands + gaze + state slot + exclusions. **A rolled weapon always births with a grip pose; a pose never appears without its weapon** — naked weapons, two-handed katanas and bow-pose-carrying-guns are structurally impossible (10k-seed stress: 100% bundle birth rate).
- **Resource-budget conflict model**: most of the old 81 hand-written anti-conflict rules are retired. Same-axis/same-group mutex + hands/gaze ledgers + state slots + 50 global mutex domains (🧬 inspectable & editable) derive conflicts structurally; `conflicts.json` keeps only cross-pool rules. Gender lock and mouth-domain double-occupation are enforced at pool level AND exit level.
- **Natural-language tail (✍ NL)**: after the tag body, 1-3 English sentences compiled from 34 table-driven families (pronoun anaphora / sentence rotation / narrative order — three anti-stitch laws). Zero LLM on the hot path, seed-deterministic, toggleable in ⚙ Settings.

## Features

- **In-node panel**: category-grouped chips, drag-to-reorder, 📌 pinning, bilingual EN/中文, NSFW toggle, 🗑 clear; 🎲 fill runs the real server-side engine — preview ≡ output
- **Two modes**
  - `Manual` — pick by hand, or 🎲 fill with per-subcategory count ranges
  - `Auto` — every generation rolls a fresh combination; the echo only replaces engine-rolled tags, manual picks are never wiped
- **➕ Add Tags picker (8 tabs)**: Pick (axis/tree views) / ⚔ Profiles / 🧬 Mutex domains / ✍ NL families / Exclusions / Library manager / Conflicts / Settings — the three new tabs render fully bilingual with a 文A toggle
- **Profile visualization**: per-card identity tags, full pose table (tags / hands / state slot / exclusions), mount diagnostics badge (unmounted weapon words flagged red), JSON editor with instant save
- **Standalone manager page**: `http://127.0.0.1:8188/taglib` or the 🏷 topbar button — full CRUD, custom icons, chip flow, batch paste import
- **NSFW tiers**: explicit tags shown in red, gated for display and output
- **Folder-based storage (hot sync)**: the library IS a folder tree, synced both ways in real time
- **AI collaboration loop**: export templates (basic/full/conflicts), extend with your AI, import back with auto-placement, dedupe and confirm preview
- **Backup**: 💾 Save as Default / ↺ Restore Backup / 🗑 Clear Library
- **Pin semantics**: 📌 pinned tags always survive rolls and echoes; pinned weapons birth with bundles too
- **Generation metadata**: PNG info carries a `TagLibrary` chunk (node / mode / seed / actual prompt), reproducible per seed
- **Translator immunity**: tag English is never rewritten by ComfyUI-DD-Translation or similar
- **Performance**: 1-4ms per execution; 10k-tag snapshot build p50 1.1ms; 3300 profile draws in 13.6s
- **Seed determinism**: same seed → same output; weight syntax `(tag:1.2)`, order-preserving dedupe, prefix/suffix concat

## UI Preview

| 1.3.0 axis view (⚔ bundle chips / axis+tree toggle) | 1.3.0 weapon & object profiles (pose tables / mount diagnostics) |
|---|---|
| ![Axis view](docs/screenshot_axis_view.png) | ![Profiles](docs/screenshot_profiles.png) |

| Node panel (pick / grouped fill / NSFW toggle) | Library manager (CRUD / import-export / backups) |
|---|---|
| ![Node panel](docs/screenshot_node_panel.png) | ![Library manager](docs/screenshot_manager.png) |

## Installation

### Option 1: ComfyUI Manager search (recommended)

1. Manager icon → **Custom Nodes Manager**
2. Search **`Tag Library`** (or `taglibrary`) → find "🏷 Tag Library 标签库" → **Install**
3. Restart ComfyUI when prompted

> If it doesn't show up, refresh the node database cache in Manager (or restart ComfyUI) and search again.

### Option 2: Install via Git URL

```
https://github.com/WSYXIUBA/ComfyUI-TagLibrary
```

### Option 3: Git clone

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/WSYXIUBA/ComfyUI-TagLibrary
```

Restart ComfyUI. No pip dependencies.

## Quick Start

1. Double-click the canvas, search "🏷 Tag Library"
2. Right-click `CLIPTextEncode.text` → **Convert to Input** → connect `positive`
3. Hit **➕ Add Tags**: pick tags / browse profiles / tune mutex & NL / settings
4. `Manual`: pick or 🎲 fill. `Auto`: just Queue — every run rolls anew
5. Wire `tags_preview` to a Preview Text node to inspect output

## Node Interface

| In/Out | Notes |
|---|---|
| `mode` | manual / auto |
| `seed` | same seed, same output |
| `selection_state` | panel state (auto-maintained, don't hand-edit) |
| `prefix` / `suffix` (optional inputs) | upstream text concatenated around the tags |
| `positive` output | tags + NL tail → CLIPTextEncode |
| `tags_preview` output | actual text preview → Preview Text |

## Data Files

| File | Notes |
|---|---|
| `data/default/tag_library.json` | factory default library (updated with the plugin) |
| `data/default/tag_library.user.json` | user snapshot (survives upgrades) |
| `data/default/taglib/` | folder-style library (hot sync) |
| `data/default/taglib/profiles.json` | **1.3.0 weapon & object profiles** (bundles / resources / state slots / NL) |
| `data/default/taglib/grouprules.json` | **1.3.0 global mutex domains** (50 groups) |
| `data/default/taglib/nl_flavors.json` | **1.3.0 NL families** (34 families + pose_map + object pools) |
| `data/default/taglib/conflicts.json` | legacy cross-pool rules (kept for compatibility) |
| `data/default/backups/` | backups |

## Conflict Model (1.3.0)

| Mechanism | Example | Source of truth |
|---|---|---|
| Same-axis / same-group mutex | `smile` blocks `grin` | `axis` / `groups` in library |
| Global mutex domains | mouth: `cigarette in mouth` ⊄ `food in mouth` | `grouprules.json` |
| Resource budget | hands ≤ 2, gaze ≤ 1 — umbrella + two-handed cup is structurally impossible | `profiles.json` |
| State slots | one weapon can't be `drawn` and `sheathed` at once | `profiles.json` |
| Cross-pool rules | photorealism ⊄ anime-style | `conflicts.json` |
| Gender lock | with `1boy`, `1girl/milf/witch` blocked at pool + exit | gender flags |

## Tests

```bash
python tests/m1_engine_test.py        # engine core (axes/groups/cross-pool/determinism)
python tests/m2_weapon_slice_test.py  # weapon bundles + repro-defect regression
python tests/m3_nl_test.py            # NL compiler + anti-stitch assertions
python tests/m4_objects_test.py       # object profiles + 10k-seed stress (--long)
python tests/quality_audit.py         # 30 full-prompt audit
python tests/smoke_test.py            # backend full-chain
python tests/perf_build_test.py       # perf gate (10k tags, p50 < 3ms)
python tests/real_http_test.py        # real ComfyUI HTTP queue acceptance
python tests/ui_v13_check.py          # CDP browser UI walkthrough (screenshots + asserts)
```

## Changelog

Full version history in [CHANGELOG.md](CHANGELOG.md) (Chinese). Current: **v1.3.0** — core refactor:
assembly axes, weapon & object profiles with pose bundles, resource-budget conflict model, NL tail compiler.

## License

MIT
