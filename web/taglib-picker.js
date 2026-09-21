/**
 * taglib-picker —— 全库挑选器 (1.7.0 自 taglibrary.js 拆出)。
 *
 * 五页签: 挑标签 (段位序单一视图) / ⚔ 武器档案 / 🧬 互斥域 (含跨池规则) /
 * ✍ NL 句式 / ⚙ 设置。行内编辑三视图共用原语 fillChips/bindEditable/postJson。
 * 挂载方 (面板) 通过 {getExisting, getExcluded, setExcluded, onNodeState,
 * onGlobalChange, node} 注入节点状态, 本模块不直接依赖面板 DOM。
 */
import {
  escapeHtml, toast, getSetting, setSetting, getState, setState,
  getNsfwEffective, getGender, SET_DEFAULT_MODE, SET_DEFAULT_NSFW,
  SET_SCALE, SET_LANG, SETTING_PREFIX,
  LIB_CACHE, LIB_PATH, fetchLibrary, fetchPanelIndex, invalidateLibraryCache,
} from "./taglib-common.js";
import { renderPipeline, disposePipeline } from "./taglib-pipeline.js";

/* --------------------------------------------- tag picker (全库挑选器) */

function mountTagPicker(rootEl, { onCancel, onConfirm, onNodeState, onGlobalChange, getExisting, getExcluded, setExcluded, node }) {
  const ui = { activeCat: null, filter: "", picked: [], tab: "pick", libTouched: false };  // pick | exclude | settings

  rootEl.innerHTML = `
    <style>
      /* 颜色全部走 .tl-scope 主题变量 (tagpanel-css.js) —— 深浅主题同一份样式 */
      .tp-wrap { display:flex; flex-direction:column; height:100%; color:var(--tl-text);
                 font:12.5px/1.5 "Segoe UI","Microsoft YaHei",sans-serif; }
      .tp-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; row-gap:7px;
                 padding:12px 16px; border-bottom:1px solid var(--tl-border); }
      .tp-head h2 { margin:0; font-size:15px; white-space:nowrap; }
      .tp-search { flex:1; min-width:150px; max-width:420px; background:var(--tl-input-bg);
                   border:1px solid var(--tl-border-2); border-radius:8px; color:var(--tl-text);
                   padding:6px 12px; outline:none; font-size:12.5px; }
      .tp-search:focus { border-color:color-mix(in srgb, var(--tl-accent) 60%, transparent); }
      .tp-cols { flex:1; display:flex; min-height:0; }
      /* ⚠ 视图必须 flex:1 吃满弹窗 —— 不给的话它按内容宽收缩, 首页那条流水线
         只占一半宽度, 右边一大片空白 (用户报的"利用率不高, 都是空白")。 */
      .tp-cats ~ section, .tp-homeview { flex:1 1 auto; min-width:0; }
      /* ⚠ 必须 flex:0 0 200px —— 只写 width 的话, 兄弟视图 flex:1 会把它压成
         38px (左侧栏被挤扁, 用户报过)。 */
      .tp-cats { flex:0 0 200px; width:200px; border-right:1px solid var(--tl-border); overflow-y:auto;
                 padding:10px; display:flex; flex-direction:column; gap:4px; }
      .tp-cat { display:flex; align-items:center; gap:7px; padding:7px 10px; border-radius:9px;
                cursor:pointer; border:1px solid transparent; transition:.12s; color:var(--tl-text-2); }
      .tp-cat.tp-cat-l0 { color:var(--tl-text); }
      .tp-cat:focus-visible { outline:2px solid color-mix(in srgb, var(--tl-accent) 70%, transparent); outline-offset:1px; }
      .tp-cat:hover { background:var(--tl-hover); }
      .tp-cat.active { background:color-mix(in srgb, currentColor 14%, transparent); border-color:currentColor; }
      .tp-cat .nm { flex:1; }
      .tp-cat .ct { font-size:11px; color:var(--tl-muted); }
      .tp-chev { cursor:pointer; opacity:.7; }
      .tp-chev:hover { opacity:1; }
      .tp-chips { flex:1; overflow-y:auto; padding:14px 16px; }
      /* ---------- 右栏: 道具姿势 + 已挑选 ----------
         手动用户的主路径: 中栏点一个道具 → 右栏列出它的全部姿势 → 点姿势入选。
         ⚠ 不要靠搜索。搜 holding gun 才看得到姿势 = 非人类交互 (用户原话)。 */
      .tp-side { flex:0 0 238px; width:238px; border-left:1px solid var(--tl-border);
                 overflow-y:auto; padding:10px 11px; display:flex; flex-direction:column; gap:9px;
                 background:var(--tl-card-2); }
      .tp-side[hidden] { display:none; }
      .tp-side-h { font-size:11px; color:var(--tl-muted); letter-spacing:.03em; }
      .tp-side-h b { color:var(--tl-text); font-size:12px; }
      /* 右栏里的「编辑档案」入口 —— 档案编辑此前藏在「设置」里, 用户找不到
         (原话: "武器档案其他编辑功能怎么没了")。放到他正在看道具的地方。 */
      .tp-side-edit { border:1px solid var(--tl-border-2); background:var(--tl-input-bg);
                      color:var(--tl-text-2); font:inherit; font-size:10.5px; padding:2px 7px;
                      border-radius:6px; cursor:pointer; white-space:nowrap; }
      .tp-side-edit:hover { color:var(--tl-text); background:var(--tl-hover); }
      .tp-side-empty { font-size:11.5px; color:var(--tl-dim); line-height:1.7;
                       border:1px dashed var(--tl-border-2); border-radius:9px; padding:9px 10px; }
      .tp-picked-item { display:flex; align-items:center; gap:6px; font-size:11.5px;
                        padding:3px 6px; border-radius:6px; color:var(--tl-text-2); }
      .tp-picked-item:hover { background:var(--tl-hover); }
      .tp-picked-item .en { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .tp-picked-item .rm { cursor:pointer; opacity:.5; padding:0 3px; }
      .tp-picked-item .rm:hover { opacity:1; color:var(--tl-danger); }
      /* ---------- 已挑选区 (1.9.0): 段位分组 + 权重入口 + 批量操作 + 手数预算 ----------
         手动用户挑完 30 个词后, 旧界面只给一串平铺词 + 逐个 ✕ —— 看不出落在哪一段、
         调不了权重、清不掉一批。这一块是那三条缺口的落点。 */
      .tp-pick-tools { display:flex; gap:5px; margin:0 0 4px; }
      .tp-pick-tool { flex:1; border:1px solid var(--tl-border-2); background:var(--tl-input-bg);
                      color:var(--tl-text-2); border-radius:6px; font:inherit; font-size:10.5px;
                      padding:2px 0; cursor:pointer; }
      .tp-pick-tool:hover { color:var(--tl-text); background:var(--tl-hover); }
      .tp-pick-sec { display:flex; align-items:center; gap:5px; font-size:10px; font-weight:700;
                     letter-spacing:.05em; color:var(--tl-accent-text); opacity:.9;
                     padding:6px 2px 2px; margin-top:3px; border-top:1px solid var(--tl-border); }
      .tp-pick-sec .clr { margin-left:auto; cursor:pointer; opacity:.6; font-weight:400; font-size:10px; }
      .tp-pick-sec .clr:hover { opacity:1; color:var(--tl-danger); }
      .tp-w { width:44px; background:var(--tl-input-bg); border:1px solid var(--tl-border-2);
              border-radius:5px; color:var(--tl-text); font-size:10.5px; padding:1px 3px;
              text-align:center; }
      .tp-w:focus { border-color:color-mix(in srgb, var(--tl-accent) 60%, transparent); outline:none; }
      .tp-budget { font-size:10.5px; color:var(--tl-muted); white-space:nowrap; }
      .tp-budget.over { color:var(--tl-danger); font-weight:600; }
      .tp-kbd-hint { font-size:10px; color:var(--tl-dim); line-height:1.6; margin-top:4px; }
      .tp-warnbox { font-size:10.5px; color:var(--tl-warn); line-height:1.6; border-radius:7px;
                    border:1px solid color-mix(in srgb, var(--tl-warn) 40%, transparent);
                    background:color-mix(in srgb, var(--tl-warn) 10%, transparent); padding:6px 8px; }
      .tp-warnbox button { margin-top:5px; }
      /* ---------- 窄屏 (1.9.0): 右栏下沉 + 左栏收窄 ----------
         旧样式右栏固定 238px 且不换行, 弹窗窄到 min(92vw,1440px) 时中栏被挤没。 */
      @media (max-width:1180px) {
        .tp-cats { flex:0 0 168px; width:168px; }
        .tp-side { flex:0 0 204px; width:204px; }
      }
      @media (max-width:980px) {
        .tp-cols { flex-wrap:wrap; }
        .tp-cats { flex:0 0 150px; width:150px; }
        .tp-side { flex:1 0 100%; width:auto; max-height:38%; border-left:0;
                   border-top:1px solid var(--tl-border); }
      }
      .tp-sub { font-size:11px; color:var(--tl-muted); margin:10px 0 6px; letter-spacing:.03em; }
      .tp-grid { display:flex; flex-wrap:wrap; gap:5px; }
      .tp-tag { --c:var(--tl-accent);
        border:1px solid color-mix(in srgb, var(--c) 30%, var(--tl-border-2));
        background:color-mix(in srgb, var(--c) 8%, var(--tl-card));
        border-radius:8px; padding:3px 10px; cursor:pointer; font-size:12px;
        transition:.12s; color:var(--tl-text); }
      .tp-tag:hover { background:color-mix(in srgb, var(--c) 20%, transparent); transform:translateY(-1px); }
      .tp-tag:focus-visible { outline:2px solid color-mix(in srgb, var(--c) 70%, transparent); outline-offset:1px; }
      .tp-tag.picked { background:var(--c); color:#fff; box-shadow:0 0 8px -2px var(--c); }
      .tp-tag.picked::before { content:"✓ "; }
      .tp-tag.dim { opacity:.38; }
      .tp-tag.nsfw { --c:#e5484d; }
      .tp-tag.gender { border-style:dashed; }
      .tp-tag .tl-gsym { font-weight:700; margin-right:2px; }
      .tp-tag .tl-gsym.g-f { color:#ff6b9d; }
      .tp-tag .tl-gsym.g-m { color:var(--tl-accent); }
      .tp-foot { display:flex; align-items:center; gap:10px; padding:11px 16px; border-top:1px solid var(--tl-border); }
      .tp-count { font-size:13px; font-weight:600; color:var(--tl-accent); }
      .tp-btn { border:1px solid var(--tl-border-2); background:var(--tl-card); color:inherit;
                border-radius:8px; padding:7px 18px; cursor:pointer; font-size:13px; }
      .tp-btn:hover { background:var(--tl-hover); }
      .tp-btn:focus-visible { outline:2px solid color-mix(in srgb, var(--tl-accent) 70%, transparent); outline-offset:1px; }
      .tp-btn.primary { background:color-mix(in srgb, var(--tl-accent) 22%, transparent);
                        border-color:color-mix(in srgb, var(--tl-accent) 55%, transparent); font-weight:600; }
      .tp-btn.primary:hover { background:color-mix(in srgb, var(--tl-accent) 32%, transparent); }
      .tp-tabbtn { border:1px solid var(--tl-border-2); background:transparent; color:var(--tl-text-2);
                   border-radius:8px; padding:5px 12px; cursor:pointer; font-size:12.5px; white-space:nowrap; }
      .tp-tabbtn:hover { background:var(--tl-hover); }
      .tp-tabbtn.active { background:color-mix(in srgb, var(--tl-accent) 18%, transparent);
                          border-color:color-mix(in srgb, var(--tl-accent) 50%, transparent);
                          color:var(--tl-accent-text); }
      .tp-exc-card { display:flex; align-items:center; gap:10px; padding:9px 13px; margin-bottom:6px;
                     border:1px solid var(--tl-border); border-radius:10px; background:var(--tl-card-2); }
      .tp-exc-card.excluded { border-color:rgba(255,107,107,.55); background:rgba(255,71,87,.10); }
      .tp-exc-card .nm { flex:1; font-size:13px; }
      .tp-exc-card .why { font-size:11px; color:var(--tl-danger-soft); }
      .tp-exc-hint { font-size:12px; color:var(--tl-muted); margin-bottom:12px; line-height:1.6; }
      .tp-master { border:1px solid color-mix(in srgb, var(--tl-accent) 35%, transparent);
                   background:color-mix(in srgb, var(--tl-accent) 8%, transparent);
                   border-radius:10px; padding:10px; margin-bottom:8px; }
      .tp-range { display:inline-flex; align-items:center; gap:4px; }
      .tp-range input { width:44px; background:var(--tl-input-bg); border:1px solid var(--tl-border-2);
                        border-radius:6px; color:var(--tl-text); padding:3px 5px; font-size:11.5px; text-align:center; }
      .tp-range-hint { font-size:10.5px; color:var(--tl-dim); margin-top:5px; }
      .tp-empty { color:var(--tl-muted); }
      /* ---------- 档案卡: 槽位下可直接手选的武器/道具姿势 (1.9.0) ---------- */
      .tp-arch { border:1px solid var(--tl-border); border-radius:10px; background:var(--tl-card-2);
                 padding:9px 11px; margin:0 0 7px; }
      .tp-arch-h { display:flex; align-items:baseline; gap:8px; margin-bottom:7px; }
      .tp-arch-h b { font-size:13px; }
      .tp-arch-mount { font-size:10.5px; color:var(--tl-dim); }
      .tp-arch-poses { display:flex; flex-wrap:wrap; gap:5px; margin-bottom:5px; }
      .tp-arch-poses:last-child { margin-bottom:0; }
      .tp-pose { display:inline-flex; align-items:center; gap:6px;
                 border:1px solid var(--tl-border-2); background:var(--tl-input-bg);
                 color:var(--tl-text-2); border-radius:7px; padding:4px 9px;
                 font:inherit; font-size:12px; cursor:pointer;
                 transition:background .13s, color .13s, border-color .13s; }
      .tp-pose:hover { color:var(--tl-text); }
      .tp-pose.on { background:color-mix(in srgb, var(--tl-accent) 26%, transparent);
                    border-color:color-mix(in srgb, var(--tl-accent) 58%, transparent);
                    color:var(--tl-accent-text); font-weight:500; }
      .tp-pose.tp-extra { border-style:dashed; }
      .tp-pose-cost { font-size:10px; opacity:.7; }
      /* ---------- 行内编辑控件 (档案 / 互斥域 / NL 三视图共用) ---------- */
      .tp-ecell { background:var(--tl-input-bg); border:1px solid var(--tl-border-2); border-radius:6px;
                  color:var(--tl-text); font-size:11.5px; padding:3px 6px; outline:none; min-width:0; }
      .tp-ecell:focus { border-color:color-mix(in srgb, var(--tl-accent) 60%, transparent); }
      .tp-ecell.wide { flex:1 1 160px; min-width:160px; }
      .tp-ecell.num { width:44px; text-align:center; }
      .tp-echip { display:inline-flex; align-items:center; gap:5px; }
      .tp-echip-x { cursor:pointer; opacity:.5; font-style:normal; font-size:10px; }
      .tp-echip-x:hover { opacity:1; color:var(--tl-danger); }
      .tp-echip-add { background:transparent; border:1px dashed var(--tl-border-2); border-radius:7px;
                      color:var(--tl-text-2); font-size:11px; padding:3px 8px; outline:none; min-width:96px; }
      .tp-echip-add:focus { border-color:var(--tl-accent); }
      .tp-edel { background:transparent; border:1px solid var(--tl-border-2); color:var(--tl-muted);
                 border-radius:6px; cursor:pointer; font-size:11px; padding:1px 7px; }
      .tp-edel:hover { color:var(--tl-danger); border-color:var(--tl-danger); }
      .tp-eadd { background:color-mix(in srgb, var(--tl-accent) 12%, transparent); cursor:pointer;
                 border:1px solid color-mix(in srgb, var(--tl-accent) 45%, transparent);
                 color:var(--tl-accent-text); border-radius:7px; padding:3px 11px; font-size:11.5px; }
      .tp-eadd:hover { background:color-mix(in srgb, var(--tl-accent) 24%, transparent); }
      .tp-erow { display:flex; gap:8px; margin-top:8px; }
      .tp-savebox { margin:16px 0 4px; }
      .tp-save { background:var(--tl-accent); border:0; color:#fff; border-radius:8px;
                 padding:6px 20px; cursor:pointer; font-weight:600; font-size:12.5px; }
      .tp-save:hover { filter:brightness(1.12); }
      .tp-smsg { margin-left:10px; font-size:11.5px; }
      .tp-gitem2 { border:1px solid var(--tl-border); border-radius:10px; padding:8px 12px; margin-bottom:6px;
                   background:var(--tl-card-2); }
      .tp-gitem2-h { display:flex; align-items:center; gap:8px; }
      .tp-gitem2-h .tp-ecell { flex:0 0 auto; }
      .tp-gitem2-h .tp-gn { margin-left:auto; color:var(--tl-muted); font-size:11px; }
      .tp-fam-edit { display:flex; align-items:center; gap:6px; margin-bottom:3px; }
      .tp-fam-edit .tp-ecell { flex:1; }
      /* ---------- 排除抽屉 (侧栏内, 窄容器 -> 覆盖全宽视图的尺寸) ---------- */
      .tp-exc { margin-top:10px; border-top:1px solid var(--tl-border); padding-top:6px; flex:0 0 auto; }
      .tp-exc > summary { cursor:pointer; font-size:11.5px; font-weight:600; color:var(--tl-text-2); padding:3px 2px; }
      .tp-exc-body { padding:4px 0; max-height:44vh; overflow-y:auto; }
      .tp-exc-body .tp-exc-hint { font-size:10.5px; line-height:1.55; margin-bottom:6px; }
      .tp-exc-body .tp-exc-card { gap:6px; padding:4px 6px; margin-bottom:0; font-size:11.5px; border-radius:6px; }
      .tp-exc-body .tp-exc-card .nm { font-size:11.5px; }
      .tp-exc-body .tp-exc-card .why { font-size:10px; }
      .tp-exc-body .tp-exc-card .tp-chev { cursor:pointer; }
      /* 轴/槽位行首的启用开关 (关掉 = 加入排除列表, 抽取时整条跳过) */
      .tp-row-tog { width:13px; height:13px; flex:0 0 auto; cursor:pointer;
                    accent-color: var(--tl-accent); margin:0 1px 0 0; }
      /* 段位分隔标题 (Anima tag order 的六段) */
      .tp-sec-head { font-size:10px; font-weight:700; letter-spacing:.06em; color:var(--tl-accent-text);
                     opacity:.85; padding:9px 4px 3px; margin-top:2px;
                     border-top:1px solid var(--tl-border); }
      .tp-sec-head:first-of-type { border-top:0; margin-top:0; padding-top:2px; }
      /* ---- 设置页 (可折叠分区) ---- */
      .tp-set-sec { margin:0 0 10px; }
      .tp-set-sec > summary { cursor:pointer; font-size:12px; font-weight:700; color:var(--tl-accent-text);
                              letter-spacing:.05em; padding:6px 0; list-style:none; user-select:none; }
      .tp-set-sec > summary::-webkit-details-marker { display:none; }
      .tp-set-sec > summary::before { content:"▸ "; color:var(--tl-muted); font-weight:400; }
      .tp-set-sec[open] > summary::before { content:"▾ "; }
      .tp-set-sec > summary:hover { filter:brightness(1.15); }
      .tp-set-sec .sub { color:var(--tl-dim); font-weight:400; font-size:11px; }
      .tp-set-card { max-width:560px; border:1px solid var(--tl-border); border-radius:12px;
                     background:var(--tl-card-2); padding:14px 16px; margin-bottom:6px; }
      .tp-set-row { margin-bottom:13px; }
      .tp-set-row:last-child { margin-bottom:0; }
      .tp-set-lab { font-size:12px; color:var(--tl-text-2); margin-bottom:4px; }
      .tp-set-hint { font-size:11px; color:var(--tl-dim); margin-top:3px; line-height:1.5; }
      .tp-set-row select, .tp-set-row input[type="text"], .tp-set-row input[type="number"] {
        background:var(--tl-input-bg); border:1px solid var(--tl-border-2); border-radius:8px;
        color:var(--tl-text); padding:6px 9px; font-size:12.5px; outline:none;
      }
      .tp-set-row select:focus, .tp-set-row input:focus { border-color:color-mix(in srgb, var(--tl-accent) 55%, transparent); }
      .tp-set-row input[type="checkbox"] { width:15px; height:15px; accent-color:var(--tl-accent); }
      .tp-sync-note { font-size:11px; color:var(--tl-dim); margin-top:14px; line-height:1.6; max-width:560px; }
      /* ---- 防冲突关系页 ---- */
      .tp-cf-stats { font-size:12px; color:var(--tl-text-2); margin-bottom:12px; }
      .tp-cf-list { display:flex; flex-direction:column; gap:6px; margin-bottom:20px; }
      .tp-cf-rule { display:flex; align-items:center; gap:8px; flex-wrap:wrap;
        border:1px solid var(--tl-border); border-radius:10px;
        background:var(--tl-card-2); padding:8px 12px; font-size:12.5px; }
      .tp-cf-rule .cf-l { font-weight:600; color:var(--tl-accent-text); }
      .tp-cf-rule .cf-vs { color:var(--tl-muted); }
      .tp-cf-rule .cf-rt { border:1px solid var(--tl-border-2); border-radius:6px;
        padding:1px 7px; font-size:11.5px; color:var(--tl-text-2); }
      .tp-cf-rule .cf-note { color:var(--tl-dim); font-size:11px; }
      .tp-cf-rule .cf-warn { color:var(--tl-danger); font-size:11px; }
      .tp-cf-rule .cf-del { margin-left:auto; background:transparent; cursor:pointer;
        border:1px solid rgba(255,107,107,.4); color:var(--tl-danger-soft); border-radius:6px;
        padding:2px 8px; font-size:11px; }
      .tp-cf-rule .cf-del:hover { background:rgba(255,71,87,.15); }
      .tp-cf-h { font-size:12px; font-weight:700; color:var(--tl-accent-text); margin:16px 0 10px; }
      .tp-cf-form { border:1px solid var(--tl-border); border-radius:12px;
        background:var(--tl-card-2); padding:14px 16px; max-width:640px; }
      .tp-cf-frow { display:flex; align-items:center; gap:8px; margin-bottom:10px; flex-wrap:wrap; }
      .tp-cf-frow .cf-klab { font-size:11.5px; color:var(--tl-muted); width:52px; }
      .tp-cf-frow select, .tp-cf-frow input {
        background:var(--tl-input-bg); border:1px solid var(--tl-border-2); border-radius:8px;
        color:var(--tl-text); padding:5px 9px; font-size:12px; outline:none; }
      .tp-cf-frow input:focus { border-color:color-mix(in srgb, var(--tl-accent) 55%, transparent); }
      .tp-cf-add { border:1px solid color-mix(in srgb, var(--tl-accent) 50%, transparent);
        background:color-mix(in srgb, var(--tl-accent) 12%, transparent);
        color:var(--tl-accent-text); border-radius:7px; padding:4px 12px; cursor:pointer; font-size:12px; }
      .tp-cf-add:hover { background:color-mix(in srgb, var(--tl-accent) 22%, transparent); }
      .tp-cf-rights { display:flex; flex-wrap:wrap; gap:5px; margin:4px 0 10px 60px; min-height:24px; }
      .tp-cf-rights .cf-rt-chip { display:inline-flex; align-items:center; gap:5px;
        border:1px solid rgba(46,204,113,.45); background:rgba(46,204,113,.08);
        border-radius:6px; padding:1px 7px; font-size:11.5px; }
      .tp-cf-rights .cf-rt-chip .x { cursor:pointer; opacity:.6; }
      .tp-cf-rights .cf-rt-chip .x:hover { opacity:1; color:var(--tl-danger); }
      .tp-cf-save { background:var(--tl-accent); border:0; color:#fff; border-radius:8px;
        padding:6px 18px; cursor:pointer; font-weight:600; font-size:12.5px; }
      .tp-cf-save:hover { filter:brightness(1.12); }
      .tp-glist { margin-bottom:6px; }
      .tp-vm { flex:1; padding:5px 0; font-size:11.5px; border-radius:7px; cursor:pointer;
               border:1px solid var(--tl-border); background:var(--tl-card); color:var(--tl-text-2); }
      .tp-vm:hover { background:var(--tl-hover); }
      .tp-vm.active { background:color-mix(in srgb, var(--tl-accent) 18%, transparent);
                      border-color:color-mix(in srgb, var(--tl-accent) 50%, transparent); color:var(--tl-accent-text); }
      .tp-axis-head { font-size:12.5px; color:var(--tl-accent-text); font-weight:600; }
      .tp-axis-n { opacity:.55; font-weight:400; }
      .tp-axis-hint { font-size:10px; color:var(--tl-warn); font-weight:400; margin-left:8px; }
      .tp-tag.bundled { border-style:dashed; border-color:color-mix(in srgb, var(--tl-warn) 55%, transparent); }
      .tp-h1 { font-size:15px; font-weight:700; color:var(--tl-text); margin-bottom:6px; }
      .tp-h1-sub { font-size:11px; color:var(--tl-muted); font-weight:400; margin-left:8px; }
      .tp-note { font-size:11.5px; color:var(--tl-text-3); line-height:1.65; margin-bottom:12px;
                 background:var(--tl-card-2); border:1px solid var(--tl-border);
                 border-radius:8px; padding:8px 12px; }
      .tp-pcard { background:var(--tl-card); border:1px solid var(--tl-border);
                  border-radius:10px; padding:12px 14px; margin-bottom:12px; }
      .tp-pcard.err { border-color:rgba(255,107,107,.5); }
      .tp-pcard-h { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:6px; }
      .tp-pcard-h code { color:var(--tl-accent-text); font-size:11px; }
      .tp-pbadges { margin-left:auto; display:flex; gap:5px; }
      .tp-b { font-size:10px; padding:2px 7px; border-radius:99px; background:var(--tl-card); color:var(--tl-text-2); }
      .tp-b.ok { background:rgba(125,212,125,.14); color:var(--tl-ok); }
      .tp-b.warn { background:rgba(240,163,94,.16); color:var(--tl-warn); }
      .tp-prow { display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin:4px 0; }
      .tp-pl { font-size:10.5px; color:var(--tl-muted); min-width:44px; }
      .tp-chip { font-size:10.5px; padding:2px 8px; border-radius:6px;
                 background:color-mix(in srgb, var(--tl-accent) 12%, transparent); color:var(--tl-accent-text); }
      .tp-ptab { width:100%; border-collapse:collapse; margin-top:8px; font-size:11px; }
      .tp-ptab th { text-align:left; color:var(--tl-muted); font-weight:500; padding:4px 8px;
                    border-bottom:1px solid var(--tl-border); }
      .tp-ptab td { padding:4px 8px; border-bottom:1px solid var(--tl-border); color:var(--tl-text-2); }
      .tp-ptab code { color:var(--tl-accent-text); }
      .tp-ptab tr.extra td { background:color-mix(in srgb, var(--tl-warn) 5%, transparent); }
      .tp-ptab .dim { color:var(--tl-muted); font-size:10px; }
      .tp-gitem { border:1px solid var(--tl-border); border-radius:8px; margin-bottom:6px; background:var(--tl-card-2); }
      .tp-gitem summary { cursor:pointer; padding:7px 12px; font-size:11.5px; color:var(--tl-text-2); }
      .tp-gitem summary code { color:var(--tl-accent-text); }
      .tp-gn { color:var(--tl-muted); font-size:10.5px; margin-left:8px; }
      .tp-gmem { padding:6px 14px 10px; display:flex; flex-wrap:wrap; gap:5px; }
      .tp-gmem .tp-chip { background:var(--tl-card); color:var(--tl-text-2); }
      .tp-gsearch { background:var(--tl-input-bg); border:1px solid var(--tl-border-2); border-radius:8px;
                    color:var(--tl-text); padding:6px 10px; font-size:12px; outline:none; }
      .tp-fam { margin-bottom:10px; }
      .tp-fam-h { font-size:12px; color:var(--tl-accent-text); margin-bottom:3px; }
      .tp-fam-s { font-size:11.5px; color:var(--tl-text-2); padding:2px 0 2px 16px; }
      .tp-jsonbox { margin-top:14px; border:1px solid var(--tl-border); border-radius:8px; }
      .tp-jsonbox summary { padding:8px 12px; font-size:12px; color:var(--tl-text-2); cursor:pointer; }
      .tp-jsonbox textarea { width:calc(100% - 24px); margin:0 12px; background:var(--tl-code-bg);
                             color:var(--tl-text-2); border:1px solid var(--tl-border); border-radius:6px;
                             font-family:Consolas,monospace; font-size:11px; padding:8px; box-sizing:border-box; }
      .tp-jrow { padding:8px 12px 12px; display:flex; align-items:center; gap:10px; }
      .tp-jsave { background:var(--tl-accent); border:0; color:#fff; border-radius:8px;
                  padding:6px 16px; cursor:pointer; font-weight:600; font-size:12px; }
      .tp-jsave:hover { filter:brightness(1.12); }
      .tp-jmsg { font-size:11.5px; }
      .tp-zh { opacity:.55; font-size:10px; margin-left:3px; }
      .tp-chip .tp-zh { margin-left:2px; }
      .tp-langbtn { border:1px solid var(--tl-border-2); background:var(--tl-card); color:var(--tl-text-2);
                    border-radius:6px; font-size:10.5px; padding:1px 7px; cursor:pointer;
                    margin-left:8px; vertical-align:2px; }
      .tp-langbtn.en { color:var(--tl-warn); border-color:color-mix(in srgb, var(--tl-warn) 50%, transparent); }
      .tp-arrow { color:var(--tl-accent); margin:0 4px; }
    </style>
    <div class="tp-wrap">
      <div class="tp-head">
        <h2>🏷 从标签库添加</h2>
        <button class="tp-tabbtn tp-hometab active">🏠 首页</button>
        <button class="tp-tabbtn tp-picktab">挑标签</button>
        <button class="tp-tabbtn tp-grptab">🧬 互斥域</button>
        <button class="tp-tabbtn tp-nltab">✍ NL 句式</button>
        <button class="tp-tabbtn tp-prtab">📦 预设</button>
        <button class="tp-tabbtn tp-settab">⚙ 设置</button>
        <input class="tp-search" placeholder="🔍 搜中文 / 英文 / 别名…" />
        <span style="flex:1"></span>
      </div>
      <div class="tp-cols">
        <aside class="tp-cats"></aside>
        <section class="tp-homeview"></section>
        <section class="tp-chips"><div class="tp-empty" style="padding:40px;text-align:center;color:#8b93a5">加载中…</div></section>
        <aside class="tp-side"></aside>
        <section class="tp-profview" style="display:none;flex:1;overflow-y:auto;padding:16px 22px;"></section>
        <section class="tp-grpview" style="display:none;flex:1;overflow-y:auto;padding:16px 22px;"></section>
        <section class="tp-nlview" style="display:none;flex:1;overflow-y:auto;padding:16px 22px;"></section>
        <section class="tp-prview" style="display:none;flex:1;overflow-y:auto;padding:16px 22px;"></section>
        <section class="tp-setview" style="display:none;flex:1;overflow-y:auto;padding:16px 22px;"></section>
      </div>
      <div class="tp-foot">
        <span class="tp-footinfo">已挑选 <b class="tp-count">0</b> 个</span>
        <span style="flex:1"></span>
        <button class="tp-btn tp-cancel">取消</button>
        <button class="tp-btn primary tp-ok">✔ 确定并保存</button>
        <button class="tp-btn tp-close2" style="display:none">✕ 关闭</button>
      </div>
    </div>
  `;

  const $ = (s) => rootEl.querySelector(s);
  const catsBox = $(".tp-cats");
  const chipsBox = $(".tp-chips");
  const sideBox = $(".tp-side");
  const searchEl = $(".tp-search");
  /* ⚠ 已挑选计数必须「每次现查 DOM」, 不能缓存引用。
     历史 bug: 这里原本是 `const countEl = $(".tp-count")` —— 只在构建时抓一次,
     而 switchTab 每次都会重建页脚 HTML, 旧引用随即脱离文档。后果是
     勾了标签底部仍显示"已挑选 0 个"(切页签才刷新), 用户以为没点上。 */
  function setPickedCount() {
    const el = $(".tp-count");
    if (el) el.textContent = String(ui.picked.length);
  }

  function libCats() { return (LIB_CACHE && LIB_CACHE.categories) || []; }

  /* ---------- 三级侧栏树: 大类(可折叠) > 子分类 > 孙分类 + 抽取范围设置 ----------
     1.3.0: 顶栏可切 视图模式 — 分类树(浏览皮肤) / 拼装轴(引擎本体)。轴模式下
     标签按 axis 字段聚合 (一词可跨面), 武器姿势词带 ⚔ 标记。 */
  const AXES_ZH = {
    meta: "💎 画质规格", count: "👥 人数", character: "🧿 角色身份",
    artist: "🎨 画师",
    appearance: "🎨 外貌特征", clothing: "👗 服装", prop: "🧰 道具武器",
    action: "🤸 动作姿态", environment: "🏞 场景环境", lighting: "💡 光影",
    camera: "🎬 镜头构图", style: "🖌 风格媒介", material: "✨ 材质特效",
    misc: "📦 未归类",
  };
  // 段位 (与 py 侧 axes.AXIS_SECTION 一一对应) —— Anima 官方 tag order 的六段。
  // 轴列表按**段位序**展示, 让用户直接看到"输出时各轴落在哪一段"。
  const AXIS_SECTION = {
    meta: 1, style: 1, count: 2, character: 3, artist: 5,
    appearance: 6, clothing: 6, prop: 6, action: 6,
    environment: 6, lighting: 6, camera: 6, material: 6, misc: 9,
  };
  const SECTION_ZH = {
    1: "① 质量 · 元信息 · 风格", 2: "② 人数", 3: "③ 角色",
    4: "④ 作品", 5: "⑤ 画师", 6: "⑥ 通用", 9: "⑨ 未归类",
  };
  // 轴的中文名 → 轴 id (与 py 侧 axes.AXIS_NAME_ZH 对应)
  const AXIS_ZH_TO_ID = {
    "画质规格": "meta", "人数": "count", "角色身份": "character", "画师": "artist",
    "外貌特征": "appearance", "服装": "clothing", "道具武器": "prop",
    "动作姿态": "action", "场景环境": "environment", "光影氛围": "lighting",
    "构图镜头": "camera", "风格媒介": "style", "材质特效": "material",
  };
  const AXIS_ORDER = ["meta", "style", "count", "character", "artist", "appearance",
                      "clothing", "prop", "action", "environment", "lighting",
                      "camera", "material", "misc"];
  /* 段位序下的轴序列 (右栏「已挑选」按它分段) —— 先按段位号, 同段内保持 AXIS_ORDER 的次序。 */
  const AXIS_BY_SECTION = [...AXIS_ORDER].sort((a, b) =>
    ((AXIS_SECTION[a] || 9) - (AXIS_SECTION[b] || 9)) || (AXIS_ORDER.indexOf(a) - AXIS_ORDER.indexOf(b)));

  /* 词 → 轴 索引 (段位提示用)。库对象变了才重建, 别每次渲染遍历 4700 词。 */
  let _enAxis = null, _enAxisSrc = null;
  function enAxisOf(en) {
    const lib = LIB_CACHE;
    if (!_enAxis || _enAxisSrc !== lib) {
      _enAxis = new Map();
      eachTag(lib || { categories: [] }, (t) => {
        const k = String(t.en || "").trim().toLowerCase();
        if (k && !_enAxis.has(k)) _enAxis.set(k, t.axis || "misc");
      });
      _enAxisSrc = lib;
    }
    return _enAxis.get(String(en || "").trim().toLowerCase()) || "";
  }
  /* 该词会落在哪一段 (手动输出保持挑选次序, 段位只用于"告诉你它属于哪一段") */
  const axisOfPicked = (p) => p._axis || enAxisOf(p.en) || "misc";
  const getUseWeights = () => !!getState(node)?.use_weights_syntax;
  /* AXES_ZH 带 emoji 前缀 ("💎 画质规格") —— 分段标题里要纯名字 */
  const axZh = (ax) => String(AXES_ZH[ax] || ax).replace(/^[^A-Za-z\u4e00-\u9fa5]+/, "");

  function eachTag(lib, fn) {
    for (const c of lib.categories || [])
      for (const s of c.subcategories || [])
        for (const t of s.tags || []) fn(t, c, s);
  }
  function renderCatsInner() {
    catsBox.innerHTML = "";
    if (!ui.openAxes) ui.openAxes = new Set();
    const st = getState(node);
    const master = st.fill_master ?? true;
    const tmin = st.total_min ?? 40;
    const tmax = st.total_max ?? 60;
    const excludedSet = new Set(getExcluded() || []);
    const isEx = (k) => excludedSet.has(k);
    // 开关 = 写 exclude_categories。轴/槽位/孙类三级同一套路径, 与引擎的 _migrate_excludes 对齐。
    const toggleEx = (key, on, parentKey) => {
      const cur = new Set(getExcluded() || []);
      if (on) { cur.delete(key); }
      else {
        cur.add(key);
        if (!parentKey) for (const k of [...cur]) if (k.startsWith(key + "/")) cur.delete(k);
        else cur.delete(parentKey);        // 关子级时清掉父级整条排除
      }
      setExcluded([...cur]);
      renderCats();
    };

    const allCount = libCats().reduce((n2, c) => n2 + countTags(c), 0);

    // ---- 总预算 ----
    const masterBox = document.createElement("div");
    masterBox.className = "tp-master";
    masterBox.innerHTML = `
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none">
        <input type="checkbox" class="tp-master-sw" ${master ? "checked" : ""}
          style="width:14px;height:14px;accent-color:#54a0ff"/>
        <b style="font-size:12px">自动配额</b>
      </label>
      <div class="tp-range" style="${master ? "" : "opacity:.35"}">
        <input type="number" class="tp-total-min" min="0" max="200" value="${tmin}"/>
        <span>~</span>
        <input type="number" class="tp-total-max" min="0" max="300" value="${tmax}"/>
      </div>
      <div class="tp-range-hint">全库共出 ${tmin}~${tmax} 个词 · 各槽位配额已内置<br>
        关掉此开关则改为逐槽位自定义</div>`;
    catsBox.appendChild(masterBox);
    masterBox.querySelector(".tp-master-sw").onchange = (e) => {
      setState(node, { fill_master: e.target.checked });
      renderCats();
    };
    const saveMaster = () => {
      const mn = parseInt(masterBox.querySelector(".tp-total-min").value) || 0;
      const mx = parseInt(masterBox.querySelector(".tp-total-max").value) || 0;
      const lo = Math.min(200, Math.max(0, Math.min(mn, mx)));
      const hi = Math.min(300, Math.max(0, Math.max(mn, mx)));
      setState(node, { total_min: lo, total_max: hi });
      masterBox.querySelector(".tp-range-hint").innerHTML =
        `全库共出 ${lo}~${hi} 个词 · 各槽位配额已内置<br>关掉此开关则改为逐槽位自定义`;
    };
    masterBox.querySelector(".tp-total-min").onchange = saveMaster;
    masterBox.querySelector(".tp-total-max").onchange = saveMaster;

    // ---- 全部 ----
    mkRow(catsBox, {
      id: "__all__", icon: "🎯", name: "全部", count: allCount, depth: 0,
      active: !ui.activeAxis && !ui.activeSlot,
      onclick: () => { ui.activeAxis = null; ui.activeSlot = null; renderCats(); renderChips(); },
    });

    // ---- 段位 → 轴 → 槽位 → 孙类 (单一视图) ----
    // 库里的轴顺序是编辑顺序, 未必等于输出段位序 (例如 style 是第 1 段却排在库里最后),
    // 不排序会让段位标题重复出现 (①…⑥…①…)。这里按 (段位, AXIS_ORDER) 排。
    const axCats = libCats().slice().sort((x, y) => {
      const sx = AXIS_SECTION[AXIS_ZH_TO_ID[x.name]] || 6;
      const sy = AXIS_SECTION[AXIS_ZH_TO_ID[y.name]] || 6;
      if (sx !== sy) return sx - sy;
      return AXIS_ORDER.indexOf(AXIS_ZH_TO_ID[x.name]) - AXIS_ORDER.indexOf(AXIS_ZH_TO_ID[y.name]);
    });
    let curSec = 0;
    for (const c of axCats) {
      const aId = AXIS_ZH_TO_ID[c.name] || "";
      const sec = AXIS_SECTION[aId] || 6;
      if (sec !== curSec) {
        const h = document.createElement("div");
        h.className = "tp-sec-head";
        h.textContent = SECTION_ZH[sec] || `第 ${sec} 段`;
        catsBox.appendChild(h);
        curSec = sec;
      }
      const cEx = isEx(c.name);
      const open = ui.openAxes.has(c.name);
      const axTotal = (c.subcategories || []).reduce((n2, s2) => n2 + (s2.tags || []).length, 0);
      mkRow(catsBox, {
        id: c.id, icon: c.icon || "📁",
        name: c.name + (cEx ? " · 已关" : ""), count: axTotal,
        depth: 0, color: c.color, chevron: true, open,
        active: ui.activeAxis === aId && !ui.activeSlot,
        toggle: { on: !cEx, title: cEx ? "整条轴已关闭 (抽取时跳过)" : "点击关闭整条轴",
                  onToggle: (on) => toggleEx(c.name, on, null) },
        onclick: () => { ui.activeAxis = aId; ui.activeSlot = null; renderCats(); renderChips(); },
        onchevron: () => { open ? ui.openAxes.delete(c.name) : ui.openAxes.add(c.name); renderCats(); },
      });
      if (!open) continue;
      for (const sub of c.subcategories || []) {
        const key = `${c.name}/${sub.name}`;
        const sEx = cEx || isEx(key);
        const subRange = (st.fill_sub_ranges || {})[sub.id] || { min: 1, max: 1 };
        mkRow(catsBox, {
          id: sub.id, name: sub.name + (sEx ? " · 已关" : ""), count: (sub.tags || []).length,
          depth: 1, active: ui.activeSlot === sub.name,
          toggle: { on: !sEx, title: cEx ? "所属轴已关闭" : (isEx(key) ? "该槽位已关闭" : "点击关闭该槽位"),
                    onToggle: (on) => toggleEx(key, on, c.name) },
          range: cEx ? { min: 0, max: 0, locked: true } : subRange,
          onRange: (mn, mx) => {
            const all = { ...(getState(node).fill_sub_ranges || {}) };
            all[sub.id] = { min: mn, max: mx };
            setState(node, { fill_sub_ranges: all });
          },
          onclick: () => { ui.activeAxis = aId; ui.activeSlot = sub.name; renderCats(); renderChips(); },
        });
        for (const g of sub.groups || []) {
          const gkey = `${c.name}/${sub.name}/${g.name}`;
          const gEx = sEx || isEx(gkey);
          mkRow(catsBox, {
            id: g.id, name: g.name + (gEx ? " · 已关" : ""), count: (g.tags || []).length,
            depth: 2, active: false,
            toggle: { on: !gEx, title: sEx ? "所属槽位已关闭" : "点击关闭该孙分类",
                      onToggle: (on) => toggleEx(gkey, on, null) },
            onclick: () => { ui.activeAxis = aId; ui.activeSlot = sub.name; renderCats(); renderChips(); },
          });
        }
      }
    }
  }


  function mkRow(box, { id, icon = "", name, count, depth, color, chevron, open, active, onclick, onchevron, range, onRange, toggle, leaf }) {
    const el = document.createElement("div");
    el.className = "tp-cat tp-cat-l" + depth + (active ? " active" : "");
    // 可定位标识: 前端此前零门禁覆盖, 而这些行没有任何 data 属性 → 选择器无从下手。
    // 补上之后, 门禁/走查能用 [data-cat="reorg.s10"] 精确点到某一行。
    if (id) el.dataset.cat = String(id);
    if (depth !== undefined) el.dataset.depth = String(depth);
    // 分类自带色 (用户自定义) 才内联; 未配置时交给 CSS 变量 → 深浅主题自动适配
    if (color) el.style.color = color;
    if (depth === 1) el.style.paddingLeft = "22px";
    if (depth === 2) el.style.paddingLeft = "38px";
    const rangeHtml = range ? `
      <span class="tp-range" style="${range.locked ? "opacity:.35" : ""}">
        <input type="number" min="0" max="20" value="${range.min}" data-r="min" ${range.locked ? "disabled" : ""}/>
        <span>~</span>
        <input type="number" min="0" max="20" value="${range.max}" data-r="max" ${range.locked ? "disabled" : ""}/>
      </span>` : "";
    el.innerHTML =
      (toggle ? `<input type="checkbox" class="tp-row-tog" ${toggle.on ? "checked" : ""}`
                + ` aria-label="${esc(String(name))}"`
                + ` title="${toggle.title || "启用/关闭"}" style="margin-right:2px"/>` : "") +
      `${chevron ? `<span class="tp-chev">${open ? "▾" : "▸"}</span>` : (depth > 0 ? '<span class="tp-chev">·</span>' : "")}` +
      `<span>${esc(String(icon))}</span><span class="nm">${esc(String(name))}</span><span class="ct">${count}</span>` +
      rangeHtml;
    const togEl = el.querySelector(".tp-row-tog");
    if (togEl) {
      togEl.onclick = (e) => { e.stopPropagation(); };
      togEl.onchange = (e) => { e.stopPropagation(); toggle.onToggle(!toggle.on); };
    }
    el.onclick = onclick;
    if (onchevron) {
      el.querySelector(".tp-chev").onclick = (e) => { e.stopPropagation(); onchevron(); };
    }
    if (range && onRange) {
      el.querySelectorAll(".tp-range input").forEach((inp) => {
        inp.onclick = (e) => e.stopPropagation();
        inp.onchange = () => {
          const mn = parseInt(el.querySelector('[data-r="min"]').value) || 0;
          const mx = parseInt(el.querySelector('[data-r="max"]').value) || 0;
          onRange(Math.min(20, Math.max(0, mn)), Math.min(20, Math.max(0, mx)));
        };
      });
    }
    box.appendChild(el);
  }

  function findColor(id) {
    return (libCats().find((c) => c.id === id) || {}).color;
  }

  function countTags(cat) {
    let n = 0;
    for (const s of cat.subcategories || []) n += (s.tags || []).length;
    return n;
  }

  function matches(t) {
    // NSFW 关 = 挑选器直接隐藏 nsfw 标签 (与填充/输出同规则)
    if (t.nsfw && !getNsfwEffective(node)) return false;
    // 性别过滤同规则: 女性=隐藏男性专属, 男性=隐藏女性专属
    const g = getGender(node);
    if (g === "female" && t.gender === "male") return false;
    if (g === "male" && t.gender === "female") return false;
    const q = ui.filter.trim().toLowerCase();
    if (!q) return true;
    return t.en.toLowerCase().includes(q) ||
           (t.zh || "").toLowerCase().includes(q) ||
           (t.aliases || []).some((a) => a.toLowerCase().includes(q));
  }

  let WEAPON_POSES = null;   // 武器档案束成员词集 (⚔ 标记用), 懒加载一次
  let PROFILES = null;       // 档案原文 (含 mount_sub / poses / extras)
  let POSE_INDEX = null;     // 束成员词(lower) -> [{arch, kind, pose}] — 搜索时可点
  let ARCHIVES_BY_MOUNT = null;  // "道具武器/武器装备" -> [档案]
  let TAG_TO_PROP = null;    // 道具身份词(lower) -> [档案] — 中栏点中道具即可列姿势

  async function fetchWeaponPoses() {
    if (WEAPON_POSES) return;
    try {
      const r = await fetch("/taglib/api/profiles");
      const d = await r.json();
      WEAPON_POSES = new Set((d.weapon_poses || []).map((x) => x.toLowerCase()));
      PROFILES = (d.data && d.data.profiles) || [];
      buildArchiveIndex();
    } catch { WEAPON_POSES = new Set(); PROFILES = []; buildArchiveIndex(); }
  }

  /* 档案索引 —— 把「档案世界」接进「挑标签」的右栏 (1.9.0)。
     ⚠ 修一个实测出来的断裂: 以前 archives 只在「武器档案」页编辑, 手动用户
     在挑标签里搜都搜不到 (实测 29 个姿势词全库零命中, 而它们的出词就写在档案里)。 */
  function buildArchiveIndex() {
    POSE_INDEX = new Map();
    ARCHIVES_BY_MOUNT = new Map();
    TAG_TO_PROP = new Map();
    for (const p of PROFILES || []) {
      const mount = String(p.mount_sub || "").trim();
      if (mount) {
        if (!ARCHIVES_BY_MOUNT.has(mount)) ARCHIVES_BY_MOUNT.set(mount, []);
        ARCHIVES_BY_MOUNT.get(mount).push(p);
      }
      for (const t of p.tags || []) {
        const k = String(t).trim().toLowerCase();
        if (!k) continue;
        if (!TAG_TO_PROP.has(k)) TAG_TO_PROP.set(k, []);
        TAG_TO_PROP.get(k).push(p);
      }
      for (const [kind, arr] of [["pose", p.poses || []], ["extra", p.extras || []]]) {
        for (const x of arr) {
          for (const t of (x.tags || [])) {
            const k = String(t).trim().toLowerCase();
            if (!k) continue;
            if (!POSE_INDEX.has(k)) POSE_INDEX.set(k, []);
            POSE_INDEX.get(k).push({ arch: p, kind, pose: x });
          }
        }
      }
    }
  }

  /* 档案改动后必须整份失效重取 —— 否则右栏还按旧档案列姿势。 */
  function invalidateArchiveIndex() {
    WEAPON_POSES = null; PROFILES = null; POSE_INDEX = null;
    ARCHIVES_BY_MOUNT = null; TAG_TO_PROP = null;
  }

  /* 当前左栏选中的槽位, 挂着哪些档案 (mount_sub 的末段 = 槽位名)。 */
  function archivesForActiveSlot() {
    if (!ARCHIVES_BY_MOUNT || !ui.activeSlot) return [];
    const hit = [];
    for (const [mount, arr] of ARCHIVES_BY_MOUNT) {
      if (mount.split("/").pop() === ui.activeSlot) hit.push(...arr);
    }
    return hit;
  }

  /* 按轴分桶 —— 全库遍历一次后缓存 (库对象变了才重建)。
     旧实现每次渲染轴视图都重新遍历 4300+ 词。 */
  let _axisBuckets = null;
  let _axisBucketSrc = null;
  function axisBucketsOf(lib) {
    if (_axisBuckets && _axisBucketSrc === lib) return _axisBuckets;
    const byAxis = {};
    eachTag(lib, (t, c, s) => {
      const a = t.axis || "misc";
      (byAxis[a] = byAxis[a] || []).push({ t, c, s });
    });
    _axisBuckets = byAxis;
    _axisBucketSrc = lib;
    return byAxis;
  }

  function renderAxisChips() {
    chipsBox.innerHTML = "";
    const existing = getExisting();
    const lib = LIB_CACHE || { categories: [] };
    const byAxis = axisBucketsOf(lib);
    const q = ui.filter.trim().toLowerCase();
    fetchWeaponPoses().finally(() => {
      let shown = 0;
      for (const a of AXIS_ORDER) {
        if (ui.activeAxis && ui.activeAxis !== a) continue;
        const rows = (byAxis[a] || []).filter((r) =>
          matches(r.t) && (!ui.activeSlot || (r.s && r.s.name === ui.activeSlot)));
        if (!rows.length) continue;
        shown += rows.length;
        const head = document.createElement("div");
        head.className = "tp-sub tp-axis-head";
        head.innerHTML = `${AXES_ZH[a] || a} <span class="tp-axis-n">${rows.length}</span>`
          + (a === "prop" || a === "action"
            ? ` <span class="tp-axis-hint">⚔=道具档案的身份词; 点中它, 右栏会列出该道具的全部姿势</span>` : "");
        chipsBox.appendChild(head);
        const grid = document.createElement("div");
        grid.className = "tp-grid";
        for (const { t, c, s } of rows) {
          grid.appendChild(chipEl(t, c, s, existing));
        }
        chipsBox.appendChild(grid);
      }
      renderSideLane();   // 右栏与中栏同步 (姿势 / 已挑选)
      setRoving(chipsInGrid()[0] || null);
      if (!shown) {
        chipsBox.innerHTML = `<div class="tp-empty" style="padding:40px;text-align:center;color:#8b93a5">`
          + `没找到匹配的标签`
          + (q ? `<div style="margin-top:10px;font-size:11.5px;opacity:.85;line-height:1.75">`
              + `武器 / 道具的<b>持握姿势</b>（如 holding gun、two-handed sword）不在标签库里。<br>`
              + `点左栏「道具武器 ▸ 武器装备」选中一把武器，<b>右栏就会列出它的全部姿势</b>。</div>` : "")
          + `</div>`;
      }
    });
  }

  function chipEl(t, c, s, existing) {
    const isPicked = ui.picked.some((p) => p.en.toLowerCase() === t.en.toLowerCase());
    const isExisting = existing.has(t.en.toLowerCase());
    const isBundled = WEAPON_POSES && WEAPON_POSES.has(t.en.toLowerCase());
    const el = document.createElement("span");
    el.dataset.en = String(t.en);   // 可定位: 门禁/走查用 [data-en="katana"] 精确点某个标签
    el.className = "tp-tag" + (t.nsfw ? " nsfw" : "") + (t.gender ? " gender" : "")
      + (isPicked ? " picked" : "") + (isExisting ? " dim" : "")
      + (isBundled ? " bundled" : "");
    if (isExisting) { el.title = "已在节点上"; el.style.opacity = ".38"; }
    else {
      // 键盘可达 (1.9.0): roving tabindex —— 整片标签云只占 1 个 Tab 位, 进去后方向键走。
      // 之前 98 个 chip 全是不可聚焦的 span, 键盘用户一个也点不到 (Tab 也不该走 98 次)。
      el.tabIndex = -1;
      el.dataset.kbd = "1";              // 参与 roving 的标记 (已在节点上的灰 chip 不参与)
      el.setAttribute("role", "button");
      el.setAttribute("aria-pressed", isPicked ? "true" : "false");
      el.setAttribute("aria-label", `${t.en}${t.zh ? " " + t.zh : ""}`);
      el.title = (isBundled ? "⚔ 档案姿势/配件成员 (自动模式下随武器带出; 手动可在「道具武器 ▸ 武器装备」下方直接点选)\n" : "")
        + (t.nsfw ? "🔞 NSFW 标签"
          : t.gender === "female" ? "♀ 女性专属标签"
          : t.gender === "male" ? "♂ 男性专属标签" : "")
        + `\n轴: ${AXES_ZH[t.axis || "misc"] || t.axis} · 槽位: ${s.name}`;
      el.onclick = () => {
        const i = ui.picked.findIndex((p) => p.en.toLowerCase() === t.en.toLowerCase());
        if (i >= 0) ui.picked.splice(i, 1);
        else ui.picked.push({ en: t.en, zh: t.zh, nsfw: !!t.nsfw, gender: t.gender || "" });
        setPickedCount();
        el.classList.toggle("picked", i < 0);
        el.setAttribute("aria-pressed", i < 0 ? "true" : "false");
        // 点中的若是道具/武器身份词 → 右栏立刻列出它的持握姿势 (手动主路径)
        renderSideLane();
      };
    }
    el.innerHTML = (isBundled ? '<span class="tl-bsym">⚔</span>' : "")
      + (t.gender === "female" ? '<span class="tl-gsym g-f">♀</span>'
        : t.gender === "male" ? '<span class="tl-gsym g-m">♂</span>' : "")
      + `${esc(t.en)}${t.zh ? `<span style="opacity:.55"> ${esc(t.zh)}</span>` : ""}`;
    return el;
  }

  /* ---------- 档案束: 手动可选 (1.9.0) ----------
     一个「姿势」= 一整束词 + 手数/视线/状态槽, 整束进出 (不再"抽中武器才带出")。 */
  const poseTags = (pose) =>
    (pose.tags || []).map((t) => String(t).trim()).filter(Boolean);

  function poseIsPicked(pose) {
    const ts = poseTags(pose).map((t) => t.toLowerCase());
    return ts.length > 0 && ts.every((en) => ui.picked.some((p) => p.en.toLowerCase() === en));
  }

  function dropPicked(en) {
    const i = ui.picked.findIndex((p) => p.en.toLowerCase() === String(en).toLowerCase());
    if (i >= 0) ui.picked.splice(i, 1);
  }

  /* 点一个束 = 整束进出。同一档案的其它束一律让位 ——
     一把武器同时只有一个持握姿势 (这条约束在档案里是隐式的, 界面要显式化)。
     ⚠ 让位时必须避开两类词, 否则会误删别人:
       ① 本次要选的束自己用到的词;
       ② **别的档案束已占用的共享词** —— 姿势词跨档案共享 (holding weapon two-handed
          同属 武士刀·双手持刀 与 枪械·双手端枪), 实机验出过: 点枪械的单手持枪
          → 把武士刀那束的 holding weapon two-handed 一起删了 (束从 2 个词变 1 个)。
     另外: 某个词若是用户先前手点进来的散词, 选束时归入本束, 不留双份。 */
  function togglePose(arch, pose) {
    const wasOn = poseIsPicked(pose);
    const keep = new Set(poseTags(pose).map((t) => t.toLowerCase()));
    const myPrefix = `${arch.zh || arch.id} · `;
    const foreign = new Set();
    for (const p of ui.picked) {
      if (p._bundle && !String(p._bundle).startsWith(myPrefix)) {
        foreign.add(p.en.toLowerCase());
      }
    }
    for (const other of (arch.poses || []).concat(arch.extras || [])) {
      if (other === pose) continue;
      for (const t of poseTags(other)) {
        const k = t.toLowerCase();
        if (keep.has(k) || foreign.has(k)) continue;
        dropPicked(t);
      }
    }
    if (wasOn) {
      for (const t of poseTags(pose)) dropPicked(t);
    } else {
      const label = `${arch.zh || arch.id} · ${pose.zh || pose.id}`;
      // 手数/视线/状态槽随身带上 —— 右栏的手数预算与段位分组都靠它们,
      // 否则用户挑了 3 个姿势也不知道已经用掉 5 只手。
      const axis = AXIS_ZH_TO_ID[String(arch.mount_sub || "").split("/")[0]] || "prop";
      for (const t of poseTags(pose)) {
        const k = t.toLowerCase();
        const got = ui.picked.find((p) => p.en.toLowerCase() === k);
        if (got) {
          // 散词归入本束 (不然一个姿势会显示成"只有 1 个词")
          if (!got._bundle) {
            got._bundle = label;
            got._axis = axis;
            got._hands = Number(pose.hands) || 0;
            got._gaze = Number(pose.gaze) || 0;
          }
          continue;
        }
        ui.picked.push({ en: t, zh: pose.zh || "", _bundle: label, _axis: axis,
                         _hands: Number(pose.hands) || 0, _gaze: Number(pose.gaze) || 0 });
      }
    }
    setPickedCount();
  }

  const poseCost = (pose) => {
    const c = [];
    if (pose.hands) c.push(`手${pose.hands}`);
    if (pose.gaze) c.push("视线");
    return c;
  };
  const poseState = (pose) => pose.state_slot
    ? Object.entries(pose.state_slot).map(([k, v]) => `${k}=${v}`).join(" ") : "";

  function poseTitle(pose) {
    const cost = poseCost(pose), st = poseState(pose);
    return `出词: ${poseTags(pose).join(", ")}`
      + (cost.length ? `\n占用: ${cost.join(" · ")}` : "")
      + (st ? `\n状态: ${st}` : "")
      + ((pose.conflicts_with || []).length ? `\n互斥: ${pose.conflicts_with.join(", ")}` : "");
  }

  /* 右栏 = 手动用户的主路径。
     ⚠ 上一版把档案摊在中栏标签云下面, 而且只能靠"搜 holding gun"才看得到 ——
     用户原话: 「靠搜索实现的? 你这什么逆天逻辑, 完全是非人类交互」。
     现在改成: 中栏点一个道具 → 右栏立即列出它的全部姿势。不需要搜索。 */
  function pickedProps() {
    if (!TAG_TO_PROP || !ui.picked.length) return [];
    const out = [], seen = new Set();
    for (const p of ui.picked) {
      for (const a of TAG_TO_PROP.get(String(p.en).toLowerCase()) || []) {
        if (seen.has(a.id)) continue;
        seen.add(a.id);
        out.push(a);
      }
    }
    return out;
  }

  /* 当前槽位里「还没有档案」的道具词 —— 用户报"很多道具分错了/没分类",
     这些词点了不会出姿势, 必须直接暴露出来而不是让他自己一个个试。 */
  function uncoveredInSlot() {
    if (!ui.activeSlot) return [];
    const covered = new Set();
    for (const a of archivesForActiveSlot()) {
      for (const t of a.tags || []) covered.add(String(t).trim().toLowerCase());
    }
    const out = [];
    for (const c of (LIB_CACHE && LIB_CACHE.categories) || []) {
      for (const s of c.subcategories || []) {
        if (s.name !== ui.activeSlot) continue;
        for (const t of s.tags || []) {
          const en = String(t.en || "").trim();
          if (en && !covered.has(en.toLowerCase())) out.push(en);
        }
      }
    }
    return out;
  }

  function renderSideLane() {
    if (!sideBox) return;
    const props = pickedProps();
    let html = `<div class="tp-side-h" style="display:flex;align-items:center;gap:6px">`
      + `<span style="flex:1">⚔ 道具姿势</span>`
      + `<button type="button" class="tp-side-edit"`
      + ` title="编辑全部道具档案: 归类身份词 / 增删姿势 / 手数·视线·状态槽">⚙ 编辑档案</button>`
      + `</div>`;
    if (!props.length) {
      const slotArchs = archivesForActiveSlot();
      html += `<div class="tp-side-empty">`
        + `先在中栏点一个<b>道具 / 武器</b>（如 katana · 武士刀、枪械），`
        + `这里就会列出它的全部持握姿势。`;
      if (slotArchs.length) {
        html += `<br><br>当前槽位「${esc(ui.activeSlot || "")}」下有 <b>${slotArchs.length}</b> 个道具带姿势：<br>`
          + slotArchs.slice(0, 10).map((a) => esc(a.zh || a.id)).join(" · ")
          + (slotArchs.length > 10 ? " …" : "");
      } else {
        html += `<br>左栏选「道具武器 ▸ 武器装备」能看到全部武器。`;
      }
      html += `</div>`;
    } else {
      for (const arch of props) {
        html += `<div class="tp-arch">`
          + `<div class="tp-arch-h"><b>${esc(arch.zh || arch.id)}</b>`
          + `<span class="tp-arch-mount">${esc(arch.mount_sub || "")}</span></div>`;
        for (const [kind, arr] of [["pose", arch.poses || []], ["extra", arch.extras || []]]) {
          if (!arr.length) continue;
          html += `<div class="tp-arch-poses">`;
          arr.forEach((pose, i) => {
            const cost = poseCost(pose);
            html += `<button type="button" class="tp-pose${kind === "extra" ? " tp-extra" : ""}`
              + `${poseIsPicked(pose) ? " on" : ""}" data-arch="${esc(arch.id)}"`
              + ` data-kind="${kind}" data-i="${i}" title="${esc(poseTitle(pose))}">`
              + `${esc(pose.zh || pose.id)}`
              + (kind === "extra" ? `<span class="tp-pose-cost">配件</span>`
                : (cost.length ? `<span class="tp-pose-cost">${esc(cost.join(" "))}</span>` : ""))
              + `</button>`;
          });
          html += `</div>`;
        }
        html += `</div>`;
      }
    }

    // 本槽位「没有档案」的道具: 暴露漏归类清单 (用户报"很多道具分错了")
    const unc = uncoveredInSlot();
    if (unc.length) {
      html += `<div class="tp-side-h" style="margin-top:3px">⚠ 本槽位未归类 <b>${unc.length}</b> 个</div>`
        + `<div class="tp-side-empty">这些词还没有档案, <b>点它们不会出姿势</b>：<br>`
        + unc.slice(0, 16).map(esc).join(" · ") + (unc.length > 16 ? " …" : "")
        + `<br><br>点上方「⚙ 编辑档案」把它们归到某个档案。</div>`;
    }

    // ---- 已挑选: 段位分组 + 权重入口 + 批量操作 + 手数预算 ----
    const bySec = new Map();
    ui.picked.forEach((p, i) => {
      const ax = axisOfPicked(p);
      if (!bySec.has(ax)) bySec.set(ax, []);
      bySec.get(ax).push({ p, i });
    });
    // 手数/视线按「姿势束」计一次 —— 一个姿势常出 2 个词 (如 two-handed sword +
    // holding weapon two-handed), 按词累加会翻倍 (实机验算出过"手 4/2", 真实占用是 2)。
    const handOf = new Map();
    for (const p of ui.picked) {
      if (!p._bundle) continue;
      if (!handOf.has(p._bundle)) {
        handOf.set(p._bundle, { h: Number(p._hands) || 0, g: Number(p._gaze) || 0 });
      }
    }
    const hands = [...handOf.values()].reduce((n, x) => n + x.h, 0);
    const gazes = [...handOf.values()].filter((x) => x.g).length;
    const over = hands > 2 || gazes > 1;
    html += `<div class="tp-side-h" style="margin-top:3px;display:flex;align-items:center;gap:6px">`
      + `<span style="flex:1">已挑选 <b>${ui.picked.length}</b> 个</span>`
      + `<span class="tp-budget${over ? " over" : ""}" title="档案姿势占用的手数/视线预算 (引擎按 2 手 / 1 视线分配)">`
      + `手 ${hands}/2 · 视线 ${gazes}/1</span></div>`;
    if (!ui.picked.length) {
      html += `<div class="tp-side-empty">还没挑任何标签。点中栏的标签、或上面的姿势即可加入。</div>`;
    } else {
      html += `<div class="tp-pick-tools">`
        + `<button type="button" class="tp-pick-tool" data-bulk="all">🗑 全部清空</button>`
        + `<button type="button" class="tp-pick-tool" data-bulk="loose" title="清掉逐个点的散词, 只留档案姿势词 (⚔)">只留姿势</button>`
        + `</div>`;
      if (over) {
        html += `<div class="tp-warnbox">⚠ 手数/视线已超预算：引擎在自动模式下会拦这类组合，`
          + `手动模式会照你选的出。多个道具姿势同时选中时记得取舍。</div>`;
      }
      for (const ax of AXIS_BY_SECTION) {
        const list = bySec.get(ax);
        if (!list || !list.length) continue;
        const sec = AXIS_SECTION[ax] || 9;
        html += `<div class="tp-pick-sec">${esc(SECTION_ZH[sec] || "")} · ${esc(axZh(ax))}`
          + `<span class="clr" data-bulk-axis="${esc(ax)}" title="清掉这一段 (${list.length} 个)">✕ 本段</span></div>`;
        for (const { p, i } of list) {
          const w = Number(p.weight) || 1;
          html += `<div class="tp-picked-item"><span class="en" title="${esc(p.en)}">${esc(p.en)}`
            + (p._bundle ? `<span class="tl-bsym" title="${esc(String(p._bundle))}">⚔</span>` : "")
            + `</span>`
            + `<input class="tp-w" type="number" step="0.05" min="0" max="3" value="${w}"`
            + ` data-w="${i}" title="权重: 输出成 (词:权重)。需要在节点上开启「权重语法」">`
            + `<span class="rm" data-rm="${i}" title="移除">✕</span></div>`;
        }
      }
      // 权重语法没开 → 权重不会进输出。直接给开关, 不做"改完看不到变化"。
      if (!getUseWeights() && ui.picked.some((p) => Math.abs((Number(p.weight) || 1) - 1) > 1e-6)) {
        html += `<div class="tp-warnbox">⚠ 节点当前<b>没开权重语法</b>，设了权重也不会写进输出。`
          + `<button type="button" class="tp-pick-tool" data-w-enable="1">开启权重语法</button></div>`;
      }
      html += `<div class="tp-kbd-hint">⌨ <b>/</b> 聚焦搜索 · <b>←→↑↓</b> 在标签间移动 · <b>Enter</b> 选中 / 取消</div>`;
    }
    sideBox.innerHTML = html;

    for (const btn of sideBox.querySelectorAll(".tp-pose")) {
      btn.onclick = () => {
        const arch = (PROFILES || []).find((x) => x.id === btn.dataset.arch);
        if (!arch) return;
        const arr = btn.dataset.kind === "extra" ? (arch.extras || []) : (arch.poses || []);
        const pose = arr[Number(btn.dataset.i)];
        if (!pose) return;
        togglePose(arch, pose);
        renderChips();
        renderSideLane();
      };
    }
    for (const x of sideBox.querySelectorAll(".rm")) {
      x.onclick = () => {
        ui.picked.splice(Number(x.dataset.rm), 1);
        setPickedCount();
        renderChips();
        renderSideLane();
      };
    }
    // 权重入口: 每个已挑选词一个数字框 (change 而非 input —— 输入中途重渲染会抢焦点)
    for (const wEl of sideBox.querySelectorAll(".tp-w")) {
      wEl.onchange = () => {
        const i = Number(wEl.dataset.w);
        const v = Math.max(0, Math.min(3, Number(wEl.value) || 1));
        const p = ui.picked[i];
        if (!p) return;
        if (Math.abs(v - 1) < 1e-6) delete p.weight; else p.weight = v;
        renderSideLane();
      };
      wEl.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); wEl.blur(); } };
    }
    // 批量操作: 全清 / 只留姿势 / 清掉某一段
    for (const b of sideBox.querySelectorAll("[data-bulk]")) {
      b.onclick = () => {
        const kind = b.dataset.bulk;
        if (kind === "all") ui.picked.length = 0;
        else if (kind === "loose") ui.picked = ui.picked.filter((p) => p._bundle);
        setPickedCount();
        renderChips();
        renderSideLane();
      };
    }
    for (const b of sideBox.querySelectorAll("[data-bulk-axis]")) {
      b.onclick = () => {
        const ax = b.dataset.bulkAxis;
        ui.picked = ui.picked.filter((p) => axisOfPicked(p) !== ax);
        setPickedCount();
        renderChips();
        renderSideLane();
      };
    }
    const we = sideBox.querySelector("[data-w-enable]");
    if (we) we.onclick = () => { setState(node, { use_weights_syntax: true }); onNodeState?.(); renderSideLane(); };
    const eb = sideBox.querySelector(".tp-side-edit");
    if (eb) eb.onclick = () => switchTab("prof");
  }

  function renderChips() {
    // v1.6.2: 树视图已删除 —— 只有"段位序"一种显示方式 (轴=引擎真实结构)。
    renderAxisChips();
  }


  function appendGrid(hits, clr, existing) {
    const grid = document.createElement("div");
    grid.className = "tp-grid";
    for (const t of hits) {
      grid.appendChild(chipEl(t, { name: "", icon: "" }, { name: "" }, existing));
    }
    chipsBox.appendChild(grid);
  }

  /* ---------- 排除类目视图 ---------- */
  const pickCols = [".tp-cats", ".tp-chips"].map((s) => rootEl.querySelector(s));
  const homeView = $(".tp-homeview");

  function upstreamText() {
    // 收集上游 prefix 文本 (已连线的输入 widget / 上游节点预览)
    let text = "";
    try {
      for (const inp of node?.inputs || []) {
        if (inp.name !== "prefix" || !inp.link) continue;
        const link = window.app?.graph?.links?.get?.(inp.link) || window.app?.graph?.links?.[inp.link];
        const srcNode = link ? window.app.graph._nodes.find((x) => x.id === link.origin_id) : null;
        const srcW = srcNode?.widgets?.find((w) => w.name === "text" || w.name === "prompt");
        if (srcW?.value) text += " " + srcW.value;
      }
    } catch {}
    return text.toLowerCase();
  }

  function suggestExcludes() {
    const up = upstreamText();
    if (!up) return {};
    const hints = {};
    const RULE = [
      ["发型发色", ["hair", "bangs", "ponytail", "twintails", "braid", "bob cut", "short hair", "long hair"]],
      ["五官", ["eyes", "blue eyes", "green eyes", "red eyes", "pointed ears", "heterochromia"]],
      ["表情情绪", ["smile", "smirk", "crying", "blush", "open mouth", "closed mouth", "angry", "sad"]],
      ["服装", ["dress", "uniform", "hoodie", "kimono", "skirt", "bikini", "swimsuit", "jacket", "shirt"]],
      ["动作姿态", ["sitting", "standing", "lying", "kneeling", "arms", "walking", "running"]],
      ["配饰", ["glasses", "hat", "necklace", "earrings", "gloves", "ribbon"]],
      ["构图镜头", ["close-up", "from above", "from below", "portrait", "wide shot", "cowboy shot"]],
      ["光影氛围", ["backlighting", "rim light", "dappled", "sunlight", "moonlight", "neon"]],
      ["场景环境", ["bedroom", "classroom", "outdoors", "forest", "beach", "city", "street"]],
      ["风格媒介", ["anime style", "photorealistic", "oil painting", "watercolor"]],
    ];
    for (const [catName, keys] of RULE) {
      const hit = keys.filter((k) => up.includes(k));
      if (hit.length) hints[catName] = hit.slice(0, 3);
    }
    return hints;
  }

  /* v1.6.0: 排除抽屉接在侧栏末尾 —— renderCats 的两个分支都有 return, 故外层包一层 */
  function renderCats() {
    renderCatsInner();
    renderExclude();
  }

  /* ---------- 排除: 三级粒度 ----------
     exclude_categories 里可放:
       "大类名"          -> 整类排除
       "大类名/子分类名"  -> 排除某个子分类
       "大类名/子分类名/孙分类名" -> 排除某个孙分类
  */
  function excKeys() { return new Set(getExcluded ? getExcluded() : []); }

  function catFullyExcluded(cat, ex) {
    return ex.has(cat.name);
  }

  function subExcluded(cat, sub, ex) {
    if (ex.has(cat.name)) return true;
    return ex.has(`${cat.name}/${sub.name}`);
  }

  function groupExcluded(cat, sub, g, ex) {
    if (subExcluded(cat, sub, ex)) return true;
    return ex.has(`${cat.name}/${sub.name}/${g.name}`);
  }

  function tagExcluded(catName, sub, g, en_l, ex) {
    if (ex.has(catName)) return true;
    if (g && ex.has(`${catName}/${sub.name}/${g.name}`)) return true;
    if (ex.has(`${catName}/${sub.name}`)) return true;
    return false;
  }

  function renderExclude() {
    const ex = excKeys();
    const hints = suggestExcludes();
    // 目标改为侧栏底部的可折叠抽屉 (原「🚫 排除类目」页签已删)
    let host = catsBox.querySelector(".tp-exc");
    if (!host) {
      host = document.createElement("details");
      host.className = "tp-exc";
      catsBox.appendChild(host);
    }
    const excN = (getExcluded ? getExcluded().length : 0);
    host.innerHTML = `<summary>🚫 排除类目 <span class="tp-gn">${excN ? excN + " 项" : "无"}</span></summary>
      <div class="tp-exc-body"></div>`;
    const body = host.querySelector(".tp-exc-body");
    // 排除过多 → 自动模式的可用池变小, 输出可能凑不满「总词数」下界。
    // 实测: 排除整条「道具武器」轴 (293 词 / 60 槽位) 后 seed11 只出 28 词 (下界 30),
    // 引擎不提示 —— 用户只会觉得"这次怎么这么短"。这里补上量化提示。
    let totalWords = 0, excWords = 0;
    for (const c of libCats()) {
      if (c.id === "nsfwcat") continue;
      const catN = countTags(c);
      totalWords += catN;
      if (catFullyExcluded(c, ex)) { excWords += catN; continue; }
      for (const s of c.subcategories || []) {
        if (subExcluded(c, s, ex)) { excWords += (s.tags || []).length; continue; }
        for (const g of s.groups || []) {
          if (groupExcluded(c, s, g, ex)) excWords += (g.tags || []).length;
        }
      }
    }
    const excPct = totalWords ? Math.round((excWords / totalWords) * 100) : 0;
    body.innerHTML = `
      <div class="tp-exc-hint">
        勾选要<b>排除</b>的层级: 可排除<b>整类</b>, 也可展开后只排除<b>子分类</b>或<b>孙分类</b>。<br/>
        排除后随机抽取与输出都会跳过对应标签。上游已有发色/眼睛等描述时 (如 <code>blue hair, blue eyes</code>),
        排除对应层级避免冲突。
        ${Object.keys(hints).length ? '<br/>💡 检测到上游提示词可能已包含以下内容 (粉色标记): ' + Object.entries(hints).map(([k, v]) => `<b>${esc(k)}</b>(${esc(v.join(","))})`).join(" ") : ""}
      </div>
      ${excWords ? `<div class="tp-warnbox" style="margin-bottom:8px">🚫 已排除 <b>${excWords}</b> 词 / 全库 ${totalWords} 词 (${excPct}%)`
        + (excPct >= 25 ? `<br>⚠ 排除比例偏高：自动模式的可用池会明显变小，输出可能凑不满「总词数」下界（实测：排除整条「道具武器」轴后曾只出 28 词）。` : "")
        + `</div>` : ""}
    `;
    for (const cat of libCats()) {
      if (cat.id === "nsfwcat") continue;
      const isEx = catFullyExcluded(cat, ex);
      const why = hints[cat.name] ? `上游已有: ${hints[cat.name].join(", ")}` : "";
      const card = document.createElement("div");
      card.className = "tp-exc-card" + (isEx ? " excluded" : "");
      card.innerHTML = `
        <input type="checkbox" ${isEx ? "checked" : ""} style="width:16px;height:16px;accent-color:#ff4757"/>
        <span>${esc(String(cat.icon || ""))}</span>
        <span class="nm">${esc(cat.name)}<span style="color:#8b93a5;font-size:11px"> · ${countTags(cat)} 条</span></span>
        <span class="why">${esc(why)}</span>
        <span class="tp-chev tp-exc-toggle">${ui.excOpen?.has(cat.id) ? "▾" : "▸"}</span>
      `;
      card.querySelector("input").onchange = (e2) => {
        const cur = excKeys();
        if (e2.target.checked) {
          cur.add(cat.name);
          // 清掉该类下更细的排除项 (整类排除已覆盖)
          for (const k of [...cur]) if (k.startsWith(cat.name + "/")) cur.delete(k);
        } else {
          cur.delete(cat.name);
        }
        setExcluded([...cur]);
        renderExclude();
      };
      card.querySelector(".tp-exc-toggle").onclick = () => {
        if (!ui.excOpen) ui.excOpen = new Set();
        ui.excOpen.has(cat.id) ? ui.excOpen.delete(cat.id) : ui.excOpen.add(cat.id);
        renderExclude();
      };
      body.appendChild(card);

      // 子分类层 (展开时)
      if (ui.excOpen?.has(cat.id) && !isEx) {
        for (const sub of cat.subcategories || []) {
          const subEx = subExcluded(cat, sub, ex);
          const subCard = document.createElement("div");
          subCard.className = "tp-exc-card" + (subEx ? " excluded" : "");
          subCard.style.cssText = "margin-left:26px;padding:6px 12px;";
          subCard.innerHTML = `
            <input type="checkbox" ${subEx ? "checked" : ""} style="width:14px;height:14px;accent-color:#ff4757"/>
            <span class="nm">${esc(sub.name)}<span style="color:#8b93a5;font-size:11px"> · ${(sub.tags || []).length}</span></span>
            ${(sub.groups || []).length ? `<span class="tp-chev tp-exc-toggle2">${ui.excOpenSub?.has(sub.id) ? "▾" : "▸"}</span>` : ""}
          `;
          subCard.querySelector("input").onchange = (e2) => {
            const cur = excKeys();
            const key = `${cat.name}/${sub.name}`;
            if (e2.target.checked) {
              cur.add(key);
              for (const k of [...cur]) if (k.startsWith(key + "/")) cur.delete(k);
              // 整类勾会被此子项替代 -> 若全部子类都被排除提示用户可直接排除整类
              cur.delete(cat.name);
            } else {
              cur.delete(key);
            }
            setExcluded([...cur]);
            renderExclude();
          };
          body.appendChild(subCard);
          const t2 = subCard.querySelector(".tp-exc-toggle2");
          if (t2) t2.onclick = () => {
            if (!ui.excOpenSub) ui.excOpenSub = new Set();
            ui.excOpenSub.has(sub.id) ? ui.excOpenSub.delete(sub.id) : ui.excOpenSub.add(sub.id);
            renderExclude();
          };
          // 孙分类层
          if (ui.excOpenSub?.has(sub.id) && !subEx) {
            for (const g of sub.groups || []) {
              const gEx = groupExcluded(cat, sub, g, ex);
              const gCard = document.createElement("div");
              gCard.className = "tp-exc-card" + (gEx ? " excluded" : "");
              gCard.style.cssText = "margin-left:52px;padding:5px 10px;";
              gCard.innerHTML = `
                <input type="checkbox" ${gEx ? "checked" : ""} style="width:13px;height:13px;accent-color:#ff4757"/>
                <span class="nm" style="font-size:12px">${esc(g.name)}<span style="color:#8b93a5"> · ${(g.tags || []).length}</span></span>
              `;
              gCard.querySelector("input").onchange = (e2) => {
                const cur = excKeys();
                const key = `${cat.name}/${sub.name}/${g.name}`;
                e2.target.checked ? cur.add(key) : cur.delete(key);
                cur.delete(`${cat.name}/${sub.name}`);
                cur.delete(cat.name);
                setExcluded([...cur]);
                renderExclude();
              };
              body.appendChild(gCard);
            }
          }
        }
      }
    }
  }

  /* ---------- 页签: 挑标签 | 排除类目 | 设置 ---------- */
  const setView = $(".tp-setview");

  function refreshLibIfTouched() {
    if (!ui.libTouched) return;
    ui.libTouched = false;
    invalidateLibraryCache();   // 两级缓存一起清: 面板索引 + 挑选器全量库
    invalidateArchiveIndex();   // 档案也可能被改过 -> 右栏别拿旧档案列姿势
    Promise.all([fetchLibrary(), fetchPanelIndex()])
      .then(() => { renderCats(); renderChips(); });
  }

  /* ---------- 📦 预设页 (1.8.1): 预设的完整管理界面搬进挑选器 ---------- */
  const prView = $(".tp-prview");
  const CFG_KEYS = ["total_min", "total_max", "bundle_pose_prob", "extra_prob",
                    "max_weapons", "nsfw_intensity", "solo_lock", "bg_mode", "focus_mode"];

  function applyPresetToNode(p) {
    const st = getState(node);
    const wantPins = new Set((p.pinned || []).map((x) => String(x).toLowerCase()));
    const tags = st.tags.map((t) =>
      wantPins.has(String(t.en).toLowerCase()) ? { ...t, pinned: true } : t);
    const have = new Set(tags.map((t) => String(t.en).toLowerCase()));
    for (const en of p.pinned || []) {
      const lo = String(en).toLowerCase();
      if (have.has(lo)) continue;
      const t = { en, zh: "", pinned: true, enabled: true };
      const path = LIB_PATH.get(lo);
      if (path) t._cat = path[0];
      tags.push(t);
    }
    const upd = {
      tags: tags.map((t) => ({ ...t, enabled: t.enabled !== false })),
      exclude_categories: (p.exclude || []).slice(),
    };
    const cfg = p.config || {};
    for (const k of CFG_KEYS) upd[k] = cfg[k] !== undefined ? cfg[k] : null;
    setState(node, upd);
    onNodeState?.();
  }

  async function saveUserPresets(list) {
    const r = await fetch("/taglib/api/settings").then((x) => x.json());
    await fetch("/taglib/api/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings: { presets: list } }),
    });
  }

  async function renderPresetView() {
    let data;
    try { data = await fetch("/taglib/api/presets").then((x) => x.json()); }
    catch { prView.innerHTML = '<div class="tp-empty">预设加载失败</div>'; return; }
    const factory = data.factory || [], user = data.user || [];
    const esc = escapeHtml;
    const rowHtml = (p, isUser) => `
      <div class="tp-gitem2" data-pid="${esc(String(p.id))}" data-src="${isUser ? "u" : "f"}">
        <div class="tp-gitem2-h">
          <b>${esc(p.name)}</b><span class="tp-gn">${esc(p.kind || "")}</span>
          <span class="tp-gn">${esc(p.pinned?.length ? "钉 " + p.pinned.length : "")}${p.exclude?.length ? " · 排除 " + p.exclude.length : ""}${p.config && Object.keys(p.config).length ? " · 配置" : ""}</span>
          <span style="flex:1"></span>
          <button class="tp-eadd tp-pr-apply">载入到节点</button>
          ${isUser ? '<button class="tp-edel tp-pr-edit">✎</button><button class="tp-edel tp-pr-del">✕</button>' : ""}
        </div>
        <div class="tp-exc-hint" style="margin:4px 0 0;">
          ${esc(p.note || "")}${p.pinned?.length ? "<br/>钉选: " + esc(p.pinned.join(", ")) : ""}
          ${p.exclude?.length ? "<br/>排除: " + esc(p.exclude.join(", ")) : ""}</div>
      </div>`;
    prView.innerHTML = `
      <div class="tp-set-sec" style="margin-bottom:10px;">
        <div class="tp-exc-hint">预设 = 钉选词 + 排除域 + 配置 (强度/场景开关等) 的一键组合。
        「载入到节点」写进当前节点状态, 约束不锁死 —— 🎲 继续在预设框内随机。</div>
      </div>
      ${factory.length ? '<div class="tp-sub">出厂预设</div>' + factory.map((p) => rowHtml(p, false)).join("") : ""}
      ${user.length ? '<div class="tp-sub">我的预设</div>' + user.map((p) => rowHtml(p, true)).join("") : '<div class="tp-sub">我的预设 (空)</div>'}
      <div class="tp-gitem2">
        <div class="tp-gitem2-h"><b>💾 把当前节点面板存为预设</b></div>
        <div class="tp-erow">
          <input class="tp-ecell wide tp-pr-name" placeholder="预设名称" />
          <select class="tp-ecell tp-pr-kind">
            <option>场景</option><option>角色</option><option>局面</option><option>背景</option>
          </select>
          <button class="tp-eadd tp-pr-save">保存</button>
        </div>
        <div class="tp-exc-hint tp-pr-msg" style="margin:6px 0 0;"></div>
      </div>`;
    const findPreset = (pid, isUser) =>
      (isUser === "u" ? user : factory).find((x) => String(x.id) === pid);
    prView.querySelectorAll('.tp-gitem2[data-pid]').forEach((row) => {
      const pid = row.dataset.pid, srcFlag = row.dataset.src;
      row.querySelector(".tp-pr-apply")?.addEventListener("click", () => {
        const p = findPreset(pid, srcFlag);
        if (p) { applyPresetToNode(p); toast("已载入预设「" + p.name + "」", false); }
      });
      row.querySelector(".tp-pr-del")?.addEventListener("click", async () => {
        if (!confirm("删除预设「" + (findPreset(pid, srcFlag)?.name || pid) + "」?")) return;
        await saveUserPresets(user.filter((x) => String(x.id) !== pid));
        renderPresetView();
      });
      row.querySelector(".tp-pr-edit")?.addEventListener("click", () => {
        const p = findPreset(pid, srcFlag);
        if (!p) return;
        const existing = row.querySelector(".tp-pr-json");
        if (existing) { existing.remove(); return; }
        const box = document.createElement("div");
        box.className = "tp-pr-json";
        box.style.marginTop = "6px";
        box.innerHTML = '<textarea class="tp-ecell" style="width:100%;min-height:120px;font-family:monospace;">' + esc(JSON.stringify(p, null, 2)) + '</textarea>'
          + '<button class="tp-eadd tp-pr-jsave" style="margin-top:4px;">保存 JSON</button>'
          + '<span class="tp-exc-hint tp-pr-jmsg"></span>';
        row.appendChild(box);
        box.querySelector(".tp-pr-jsave").onclick = async () => {
          let obj;
          try { obj = JSON.parse(box.querySelector("textarea").value); }
          catch (e) { box.querySelector(".tp-pr-jmsg").textContent = "JSON 不合法: " + e.message; return; }
          if (!obj.name) { box.querySelector(".tp-pr-jmsg").textContent = "缺少 name"; return; }
          await saveUserPresets(user.map((x) => String(x.id) === pid ? obj : x));
          renderPresetView();
        };
      });
    });
    prView.querySelector(".tp-pr-save").onclick = async () => {
      const nameEl = prView.querySelector(".tp-pr-name");
      const name = nameEl.value.trim();
      const msg = prView.querySelector(".tp-pr-msg");
      if (!name) { msg.textContent = "⚠ 请先填预设名称"; return; }
      const st = getState(node);
      const preset = {
        id: "u" + Date.now().toString(36),
        name, kind: prView.querySelector(".tp-pr-kind").value,
        pinned: st.tags.filter((t) => t.pinned).map((t) => t.en),
        exclude: (st.exclude_categories || []).slice(),
        config: {}, note: "",
      };
      for (const k of CFG_KEYS) {
        if (st[k] !== undefined && st[k] !== null && st[k] !== false) preset.config[k] = st[k];
      }
      if (!preset.pinned.length && !preset.exclude.length && !Object.keys(preset.config).length) {
        msg.textContent = "⚠ 当前没有钉选词 / 排除域 / 配置, 没什么可存";
        return;
      }
      const r = await fetch("/taglib/api/settings").then((x) => x.json());
      await saveUserPresets([...(r?.settings?.presets || []), preset]);
      msg.textContent = "✅ 已保存「" + name + "」";
      nameEl.value = "";
      renderPresetView();
    };
  }

  /* ---------- 设置页: 节点参数(原⚙弹窗) + 全局偏好(与 ComfyUI 设置双向同步) ---------- */
  function renderSettingsView() {
    const st = getState(node);
    // 全局值读取 (旧版三模式值归一化为现行二态)
    const rawMode = getSetting(SET_DEFAULT_MODE, "manual");
    const gMode = rawMode === "random_mix" ? "auto" : rawMode === "random_by_category" ? "manual" : (rawMode === "auto" ? "auto" : "manual");
    const gNsfw = !!getSetting(SET_DEFAULT_NSFW, false);
    const gScale = getSetting(SET_SCALE, 100);
    const gFont = getSetting(SETTING_PREFIX + "chip_font_size", 0);
    const gRadius = getSetting(SETTING_PREFIX + "chip_radius", 7);
    const gLang = getSetting(SET_LANG, "bilingual");
    const row = (label, inner, hint) => `
      <div class="tp-set-row">
        <div class="tp-set-lab">${label}</div>
        ${inner}
        ${hint ? `<div class="tp-set-hint">${hint}</div>` : ""}
      </div>`;
    setView.innerHTML = `
      <details class="tp-set-sec" open>
      <summary>节点参数 <span class="sub">· 存入当前节点, 随工作流保存</span></summary>
      <div class="tp-set-card">
        ${row("输出分隔符", `<select class="sv-sep">
            <option value="comma" ${(st.separator ?? "comma") === "comma" ? "selected" : ""}>逗号 , (推荐)</option>
            <option value="space" ${st.separator === "space" ? "selected" : ""}>空格</option>
          </select>`)}
        ${row("权重语法 (tag:1.2)", `<input type="checkbox" class="sv-w" ${st.use_weights_syntax ? "checked" : ""}/>`,
          "开启后权重≠1 的标签输出为 (tag:权重) 形式")}
        ${row("去重", `<input type="checkbox" class="sv-dd" ${st.dedupe !== false ? "checked" : ""}/>`,
          "相同标签只输出一次")}
        ${row("组合随机过滤词", `<input type="text" class="sv-search" value="${(st.search_text || "").replace(/"/g, "&quot;")}" placeholder="留空 = 全库抽取"/>`,
          "只从匹配的标签里随机 (支持中文/英文/别名)")}
      </div>
      </details>
      <details class="tp-set-sec" open>
      <summary>🎛 场景控制 <span class="sub">· 单人锁 / 简洁背景 / 人物特写 / NSFW 强度</span></summary>
      <div class="tp-set-card">
        ${row("👤 单人锁", '<input type="checkbox" class="sv-solo" ' + (st.solo_lock ? "checked" : "") + '/>',
          "人数轴只出单词 (1girl/1boy/solo…), 禁多人词与互动槽 — 生效于下次 🎲/队列")}
        ${row("🖼 简洁背景", '<input type="checkbox" class="sv-bg" ' + (st.bg_mode === "simple" ? "checked" : "") + '/>',
          "禁具象场景/天气/粒子槽, 背景只出纯色/渐变/虚化/棚拍族")}
        ${row("🎯 人物特写", '<input type="checkbox" class="sv-focus" ' + (st.focus_mode === "portrait" ? "checked" : "") + '/>',
          "禁杂物道具槽, 取景只出 portrait/upper body 特写族")}
        ${row("🔞 NSFW 强度", '<select class="sv-ninten">'
            + '<option value="0"' + (Number(st.nsfw_intensity || 0) === 0 ? " selected" : "") + '>标准 (×1)</option>'
            + '<option value="1"' + (Number(st.nsfw_intensity) === 1 ? " selected" : "") + '>强调 (×2.5)</option>'
            + '<option value="2"' + (Number(st.nsfw_intensity) === 2 ? " selected" : "") + '>纯欲 (×6 + 槽位保底)</option>'
            + '</select>',
          "涩词抽样权重乘数; 纯欲档另有性行为/服装状态保底与显式词分层加权")}
      </div>
      </details>
      <details class="tp-set-sec" open>
      <summary>1.3.0 引擎 <span class="sub">· 组互斥/资源算账/武器束/NL 尾段</span></summary>
      <div class="tp-set-card">
        ${row("自然语言尾段", `<input type="checkbox" class="sv-nltail" ${st.nl_tail !== false ? "checked" : ""}/>`,
          "输出末尾追加 2~4 句连贯英文描述 (句式随 seed 变, 关掉=纯标签)")}
        ${row("武器带姿势概率", `<input type="number" class="sv-bundleprob" min="0" max="100" step="5" value="${Math.round((st.bundle_pose_prob ?? 0.85) * 100)}"/>`,
          "% · 抽中武器时自动带出该武器一条姿势的概率")}
        ${row("同时武器上限", `<input type="number" class="sv-maxweap" min="1" max="4" step="1" value="${st.max_weapons ?? 2}"/>`,
          "超过后新武器不再配姿势 (手部资源有限, 背着一把再举一把没有意义)")}
        ${row("配件出生概率", `<input type="number" class="sv-extrprob" min="0" max="100" step="5" value="${Math.round((st.extra_prob ?? 0.35) * 100)}"/>`,
          "% · 武器档案的配件 (刀鞘/箭袋/镜) 随武器出现的概率")}
      </div>
      </details>
      <details class="tp-set-sec" open>
      <summary>全局偏好 <span class="sub">· 与 ComfyUI 设置面板「标签库」双向同步</span></summary>
      <div class="tp-set-card">
        ${row("新节点的默认模式", `<select class="sv-gmode">
            <option value="manual" ${gMode === "manual" ? "selected" : ""}>手动</option>
            <option value="auto" ${gMode === "auto" ? "selected" : ""}>自动</option>
          </select>`)}
        ${row("默认启用 NSFW 标签", `<input type="checkbox" class="sv-gnsfw" ${gNsfw ? "checked" : ""}/>`,
          "关闭时隐藏并排除 NSFW 标签; 也可在每个节点上单独开关")}
        ${row("整体比例 (%) — 按钮/字体等内部 UI 缩放", `<input type="number" class="sv-gscale" min="50" max="200" step="5" value="${gScale}"/>`,
          "100% = 默认大小; 影响面板内所有按钮/字体/chip 大小")}
        ${row("标签字号覆盖 (px, 0=跟随比例)", `<input type="number" class="sv-gfont" min="0" max="24" step="1" value="${gFont}"/>`)}
        ${row("标签圆角 (px)", `<input type="number" class="sv-grad" min="0" max="16" step="1" value="${gRadius}"/>`)}
        ${row("标签文字显示", `<select class="sv-glang">
            <option value="bilingual" ${gLang === "bilingual" ? "selected" : ""}>双语 (英文+中文)</option>
            <option value="en" ${gLang === "en" ? "selected" : ""}>仅英文</option>
            <option value="zh" ${gLang === "zh" ? "selected" : ""}>仅中文</option>
          </select>`,
          "输出永远只有英文; 这里只控制面板里标签按钮的显示文字")}
      </div>
      </details>
      <details class="tp-set-sec">
      <summary>⚔ 道具 / 武器档案 <span class="sub">· 高级维护; 日常选用在「挑标签」右栏直接点</span></summary>
      <div class="tp-set-card">
        <div class="tp-set-hint" style="margin-bottom:8px">
          档案定义「一把武器有哪些持握姿势、各占几只手、带什么状态槽、和哪些词互斥」。
          这里只影响<b>自动模式</b>与<b>挑标签右栏列出的姿势列表</b>；选用入口在挑标签页右栏。
        </div>
        <div class="tp-jrow"><button class="tp-goprof">打开档案编辑器 →</button></div>
      </div>
      </details>
      <div class="tp-sync-note">💡 节点参数即改即存; 全局偏好写入 ComfyUI 设置 (设置面板搜「标签库」是同一批值, 两边改都生效)。</div>
    `;
    // 节点参数: 即改即存 + 让节点面板实时跟随
    $(".tp-goprof").onclick = () => switchTab("prof");
    const saveNode = (patch) => { setState(node, patch); onNodeState?.(); };
    $(".sv-sep").onchange = (e) => saveNode({ separator: e.target.value });
    $(".sv-w").onchange = (e) => saveNode({ use_weights_syntax: e.target.checked });
    $(".sv-dd").onchange = (e) => saveNode({ dedupe: e.target.checked });
    $(".sv-search").onchange = (e) => saveNode({ search_text: e.target.value.trim() });
    const clampPct = (v, d) => Math.min(100, Math.max(0, parseInt(v) ?? d)) / 100;
    $(".sv-nltail").onchange = (e) => saveNode({ nl_tail: e.target.checked });
    $(".sv-bundleprob").onchange = (e) => saveNode({ bundle_pose_prob: clampPct(e.target.value, 85) });
    $(".sv-maxweap").onchange = (e) => saveNode({ max_weapons: Math.min(4, Math.max(1, parseInt(e.target.value) || 2)) });
    $(".sv-extrprob").onchange = (e) => saveNode({ extra_prob: clampPct(e.target.value, 35) });
    // 场景控制 (1.8.1)
    $(".sv-solo").onchange = (e) => saveNode({ solo_lock: e.target.checked });
    $(".sv-bg").onchange = (e) => saveNode({ bg_mode: e.target.checked ? "simple" : "normal" });
    $(".sv-focus").onchange = (e) => saveNode({ focus_mode: e.target.checked ? "portrait" : "normal" });
    $(".sv-ninten").onchange = (e) => saveNode({ nsfw_intensity: Number(e.target.value) || null });
    // 全局偏好: 写入 ComfyUI 设置 (官方持久化) + 当前面板即时跟随; 其他节点由轮询跟进
    const saveGlobal = (id, value) => { setSetting(id, value); onGlobalChange?.(); };
    $(".sv-gmode").onchange = (e) => saveGlobal(SET_DEFAULT_MODE, e.target.value);
    $(".sv-gnsfw").onchange = (e) => saveGlobal(SET_DEFAULT_NSFW, e.target.checked);
    $(".sv-gscale").onchange = (e) => saveGlobal(SET_SCALE, Math.min(200, Math.max(50, parseInt(e.target.value) || 100)));
    $(".sv-gfont").onchange = (e) => saveGlobal(SETTING_PREFIX + "chip_font_size", Math.min(24, Math.max(0, parseInt(e.target.value) || 0)));
    $(".sv-grad").onchange = (e) => saveGlobal(SETTING_PREFIX + "chip_radius", Math.min(16, Math.max(0, parseInt(e.target.value) || 7)));
    $(".sv-glang").onchange = (e) => saveGlobal(SET_LANG, e.target.value);
  }

  /* ---------- 🧷 防冲突关系页签 ---------- */

  /* ---------- 1.3.0 新视图: 武器档案 / 互斥域 / NL 句式 ---------- */
  const profView = $(".tp-profview");
  const grpView = $(".tp-grpview");
  const nlView = $(".tp-nlview");

  function editorFoot(scope, apiUrl, getData) {
    const ta = scope.querySelector(".tp-json");
    const btn = scope.querySelector(".tp-jsave");
    const msg = scope.querySelector(".tp-jmsg");
    if (btn) btn.onclick = async () => {
      let payload;
      try { payload = JSON.parse(ta.value); }
      catch (e) { msg.textContent = "❌ JSON 解析失败: " + e.message; msg.style.color = "var(--tl-danger)"; return; }
      btn.disabled = true; msg.textContent = "保存中…"; msg.style.color = "var(--tl-muted)";
      try {
        const r = await fetch(apiUrl, { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(getData(payload)) });
        const d = await r.json();
        if (d.ok) { msg.textContent = "✅ 已保存, 引擎即时生效"; msg.style.color = "var(--tl-ok)"; invalidateArchiveIndex(); }
        else { msg.textContent = "❌ " + String(d.error || JSON.stringify(d.errors || "")).slice(0, 160); msg.style.color = "var(--tl-danger)"; }
      } catch (e) { msg.textContent = "❌ " + e.message; msg.style.color = "var(--tl-danger)"; }
      btn.disabled = false;
    };
  }

  /* ---------- 行内编辑原语 (档案 / 互斥域 / NL 三个视图共用) ----------
     三个视图的共同点: 一个实体列表 + 每个实体若干字段 + 字段里可能嵌子列表。
     统一在这里提供原语, 避免每个视图各写一套只读渲染 + JSON 兜底。
     规则: 先改内存工作副本, 点保存才落盘; 结构性改动 (增删行) 立即重绘。 */

  function tagDatalistHtml() {
    const opts = [];
    for (const c of libCats()) for (const s of c.subcategories || []) for (const t of s.tags || []) opts.push(t.en);
    return `<datalist id="tp-tagdl">${opts.map((v) => `<option value="${esc(String(v))}"/>`).join("")}</datalist>`;
  }

  function subDatalistHtml() {
    const opts = [];
    for (const c of libCats()) for (const s of c.subcategories || []) opts.push(`${c.name}/${s.name}`);
    return `<datalist id="tp-subdl">${opts.map((v) => `<option value="${esc(String(v))}"/>`).join("")}</datalist>`;
  }

  /** 可编辑 chip 列表: 每个 chip 带 ✕, 末尾一个回车即加的输入框。 */
  function fillChips(container, arr, onChange, datalistId) {
    container.innerHTML = "";
    arr.forEach((v, i) => {
      const c = document.createElement("span");
      c.className = "tp-chip tp-echip";
      c.innerHTML = `${bi(v)}<i class="tp-echip-x" title="移除">✕</i>`;
      c.querySelector(".tp-echip-x").onclick = () => { arr.splice(i, 1); onChange(); };
      container.appendChild(c);
    });
    const inp = document.createElement("input");
    inp.className = "tp-echip-add";
    inp.placeholder = "＋ 回车添加";
    if (datalistId) inp.setAttribute("list", datalistId);
    inp.onkeydown = (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const v = inp.value.trim();
      if (!v) return;
      if (!arr.some((x) => String(x).toLowerCase() === v.toLowerCase())) arr.push(v);
      onChange();
    };
    container.appendChild(inp);
  }

  function saveBarHtml(label) {
    return `<div class="tp-jrow"><button class="tp-save">💾 ${label}</button><span class="tp-smsg"></span></div>`;
  }

  async function postJson(apiUrl, payload, msgEl, okText) {
    msgEl.textContent = "保存中…"; msgEl.style.color = "var(--tl-muted)";
    try {
      const r = await fetch(apiUrl, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (d.ok) {
        msgEl.textContent = okText || "✅ 已保存, 引擎即时生效";
        msgEl.style.color = "var(--tl-ok)";
        invalidateArchiveIndex();
        return true;
      }
      msgEl.textContent = "❌ " + String(d.error || JSON.stringify(d.errors || "")).slice(0, 200);
      msgEl.style.color = "var(--tl-danger)";
      return false;
    } catch (e) {
      msgEl.textContent = "❌ " + e.message; msgEl.style.color = "var(--tl-danger)";
      return false;
    }
  }

  /** 把一行 input 的值写回实体字段。data-f 指定字段名。 */
  function applyFieldInput(t, f, el) {
    let v = el.value;
    if (f === "hands" || f === "gaze" || f === "weight") {
      const n = parseFloat(v);
      t[f] = Number.isFinite(n) ? n : (f === "weight" ? 1 : 0);
      return;
    }
    v = String(v).trim();
    if (f === "tags") {
      t[f] = v ? v.split(/[,，]/).map((x) => x.trim()).filter(Boolean) : [];
      return;
    }
    if (f === "state_slot") {
      const o = {};
      for (const kv of v.split(/[,，]/)) {
        const m2 = kv.split("=");
        if (m2.length >= 2) o[m2[0].trim()] = m2.slice(1).join("=").trim();
      }
      t[f] = Object.keys(o).length ? o : undefined;
      if (!t[f]) delete t[f];
      return;
    }
    if (v) t[f] = v; else delete t[f];
  }

  /** 在容器内统一绑定: 单元格变更 / 删除按钮 / 新增按钮。
   *  getEntity(pi, k, xi) -> 要修改的对象; data-k 为空表示改档案本体。 */
  function bindEditable(scope, { getEntity, onStructural }) {
    scope.querySelectorAll("input[data-f]").forEach((el) => {
      el.onchange = () => {
        const pi = Number(el.dataset.p);
        const xi = el.dataset.x === undefined ? null : Number(el.dataset.x);
        const t = getEntity(pi, el.dataset.k || "", xi);
        if (t) applyFieldInput(t, el.dataset.f, el);
      };
    });
    scope.querySelectorAll(".tp-edel").forEach((b) => {
      b.onclick = () => { onStructural("del", Number(b.dataset.p), b.dataset.k || "", b.dataset.x); };
    });
    scope.querySelectorAll(".tp-eadd").forEach((b) => {
      b.onclick = () => { onStructural("add", Number(b.dataset.p), b.dataset.k || "", null); };
    });
  }

  const esc = (x) => String(x).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

  /* ---- 双语辅助: 词→中文 (一次性建全库 EN_ZH 表 + 档案 lang 兜底库外束词) ---- */
  const TP_LANG = { en: false };  // 新 tab 独立的 中/英 显示开关
  try { TP_LANG.en = localStorage.getItem("taglib.tpLang") === "en"; } catch {}
  let _EN_ZH = null;
  function enZhMap() {
    if (_EN_ZH) return _EN_ZH;
    const m = {};
    for (const c of libCats())
      for (const s of c.subcategories || [])
        for (const t of s.tags || []) {
          const k = String(t.en).toLowerCase();
          if (t.zh && !(k in m)) m[k] = t.zh;
        }
    _EN_ZH = m;
    return m;
  }
  let LANG_MAP = {};  // 档案接口带回: 库外束词(如 drawing bow)的中文
  function zhOf(en) {
    const k = String(en).toLowerCase();
    return LANG_MAP[k] || enZhMap()[k] || "";
  }
  function langBtnHtml() {
    return `<button class="tp-langbtn ${TP_LANG.en ? "en" : ""}" title="中/英文显示切换">文A</button>`;
  }
  function bindLang(scope, rerender) {
    const b = scope.querySelector(".tp-langbtn");
    if (b) b.onclick = () => {
      TP_LANG.en = !TP_LANG.en;
      try { localStorage.setItem("taglib.tpLang", TP_LANG.en ? "en" : "zh"); } catch {}
      b.classList.toggle("en", TP_LANG.en);
      rerender();
    };
  }
  function bi(en) {  // 双语渲染: 纯英模式或被查词无中文 → 只留英文
    const z = zhOf(en);
    return (TP_LANG.en || !z) ? esc(en) : `${esc(en)}<span class="tp-zh">${esc(z)}</span>`;
  }

  let profWork = null;      // 编辑中的档案工作副本 (点保存才落盘)
  let profDiag = [];

  async function renderProfView() {
    profView.innerHTML = `<div style="padding:30px;text-align:center;color:#8b93a5">加载中…</div>`;
    let d;
    try { d = await fetch("/taglib/api/profiles").then((r) => r.json()); }
    catch { profView.innerHTML = `<div class="tp-empty" style="padding:30px;color:#ff6b6b">档案接口加载失败</div>`; return; }
    LANG_MAP = Object.assign(LANG_MAP, d.lang || {});
    _EN_ZH = null;
    profDiag = d.diag || [];
    const src = d.data && Array.isArray(d.data.profiles) ? d.data : { version: 1, profiles: [] };
    profWork = JSON.parse(JSON.stringify(src));
    drawProf();
  }

  function drawProf() {
    const profs = (profWork.profiles = profWork.profiles || []);
    const nPose = profs.reduce((n, p) => n + (p.poses || []).length + (p.extras || []).length, 0);
    let html = `
      <div style="margin-bottom:10px">
        <button class="tp-btn tp-goback">← 返回挑标签</button>
        <span class="tp-exc-hint" style="margin-left:10px">
          左栏「身份词」= 哪些道具标签归到这份档案 (给道具打武器分类就改这里)
        </span>
      </div>
      <div class="tp-h1">⚔ 武器 / 物品档案 ${langBtnHtml()}
        <span class="tp-h1-sub">${profs.length} 份 · ${nPose} 条姿势/配件</span>
        <button class="tp-eadd tp-addprof" style="margin-left:auto">＋ 新增档案</button></div>
      <div class="tp-note">全部字段可直接改: 档案 id / 中文名 / 挂载槽位 / 身份词, 以及每条姿势的 id、出词、手数、视线、权重、状态槽。改完点底部「💾 保存档案」写入 <code>profiles.json</code>。
      姿势不独立存在 —— 每条挂在档案下。⚠ <b>这里只是维护入口; 想手选姿势请到「挑标签」选「道具武器 ▸ 武器装备」, 下方会列出全部可手选姿势。</b>
      姿势成员词在随机池里永不单抽。</div>`;
    if (!profs.length) html += `<div class="tp-empty" style="padding:24px">还没有档案, 点右上「＋ 新增档案」开始。</div>`;
    profs.forEach((p, pi) => {
      const dg = (profDiag || []).find((x) => x.id === p.id) || {};
      const row = (x, xi, kind) => `
        <tr>
          <td><input class="tp-ecell" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="id" value="${esc(x.id || "")}" placeholder="姿势 id"/></td>
          <td><input class="tp-ecell" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="zh" value="${esc(x.zh || "")}" placeholder="中文"/></td>
          <td><input class="tp-ecell wide" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="tags" value="${esc((x.tags || []).join(", "))}" placeholder="出词, 逗号分隔"/></td>
          <td><input class="tp-ecell num" type="number" min="0" max="2" aria-label="手数" title="占用手数 0~2" placeholder="手" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="hands" value="${x.hands ?? 0}"/></td>
          <td><input class="tp-ecell num" type="number" min="0" max="1" aria-label="视线" title="是否占用视线 0/1" placeholder="眼" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="gaze" value="${x.gaze ?? 0}"/></td>
          <td><input class="tp-ecell num" type="number" min="0" max="3" step="0.1" aria-label="权重" title="抽取权重" placeholder="权" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="weight" value="${x.weight ?? 1}"/></td>
          <td><input class="tp-ecell" data-p="${pi}" data-k="${kind}" data-x="${xi}" data-f="state_slot" value="${esc(Object.entries(x.state_slot || {}).map(([k, v]) => k + "=" + v).join(", "))}" placeholder="drawn=yes"/></td>
          <td><button class="tp-edel" data-p="${pi}" data-k="${kind}" data-x="${xi}" title="删除该条姿势/配件">✕</button></td>
        </tr>`;
      html += `
      <div class="tp-pcard">
        <div class="tp-pcard-h">
          <input class="tp-ecell" data-p="${pi}" data-f="id" value="${esc(p.id || "")}" placeholder="档案 id" style="min-width:130px"/>
          <input class="tp-ecell" data-p="${pi}" data-f="zh" value="${esc(p.zh || "")}" placeholder="中文名" style="min-width:90px"/>
          <input class="tp-ecell wide" list="tp-subdl" data-p="${pi}" data-f="mount_sub" value="${esc(p.mount_sub || "")}" placeholder="挂载槽位 大类/子类" style="min-width:170px"/>
          <span class="tp-pbadges">
            <span class="tp-b">${(p.poses || []).length} 姿势</span>
            <span class="tp-b">${(p.extras || []).length} 配件</span>
            ${dg.mount_ok !== undefined ? `<span class="tp-b ${dg.mount_ok === dg.mount_total ? "ok" : "warn"}">挂载 ${dg.mount_ok}/${dg.mount_total}${dg.missing && dg.missing.length ? " 缺:" + esc(dg.missing.join(",")) : ""}</span>` : ""}
          </span>
          <button class="tp-edel tp-delprof" data-p="${pi}" title="删除该档案">✕</button>
        </div>
        <div class="tp-prow"><span class="tp-pl">身份词</span><span class="tp-echips" data-p="${pi}"></span></div>
        <table class="tp-ptab">
          <tr><th>姿势 id</th><th>中文</th><th>出词</th><th>手数</th><th>视线</th><th>权重</th><th>状态槽</th><th></th></tr>
          ${(p.poses || []).map((x, xi) => row(x, xi, "poses")).join("")}
          ${(p.extras || []).map((x, xi) => row(x, xi, "extras")).join("")}
        </table>
        <div class="tp-erow">
          <button class="tp-eadd" data-p="${pi}" data-k="poses">＋ 姿势</button>
          <button class="tp-eadd" data-p="${pi}" data-k="extras">＋ 配件</button>
        </div>
      </div>`;
    });
    if ((profWork.profiles || []).some((p) => !(p.tags || []).length)) {
      html += `<div class="tp-note" style="color:var(--tl-danger-soft)">⚠ 有档案没有身份词 —— 引擎无法在抽取时找到它, 请至少填一个。</div>`;
    }
    html += `${tagDatalistHtml()}${subDatalistHtml()}
      <div class="tp-savebox">${saveBarHtml("保存档案")}</div>
      <details class="tp-jsonbox"><summary>✏ 高级: 直接编辑 JSON (保存前自动备份 .bak)</summary>
        <textarea class="tp-json" rows="14" spellcheck="false">${esc(JSON.stringify(profWork, null, 1))}</textarea>
        <div class="tp-jrow"><button class="tp-jsave">💾 保存档案</button><span class="tp-jmsg"></span></div>
      </details>`;
    profView.innerHTML = html;
    profView.querySelector(".tp-goback").onclick = () => switchTab("pick");
    bindLang(profView, drawProf);

    // chip 列表 (身份词)
    profView.querySelectorAll(".tp-echips").forEach((el) => {
      const p = profWork.profiles[Number(el.dataset.p)];
      p.tags = p.tags || [];
      fillChips(el, p.tags, drawProf, "tp-tagdl");
    });
    bindEditable(profView, {
      getEntity: (pi, k, xi) => (k ? (profWork.profiles[pi][k] || [])[xi] : profWork.profiles[pi]),
      onStructural: (act, pi, k, xi) => {
        if (act === "del") {
          if (k) profWork.profiles[pi][k].splice(Number(xi), 1);
          else profWork.profiles.splice(pi, 1);
        } else if (act === "add" && k) {
          (profWork.profiles[pi][k] = profWork.profiles[pi][k] || []).push(
            k === "poses" ? { id: "new_pose", tags: [], hands: 1, gaze: 0, weight: 1 }
                          : { id: "new_extra", tags: [], weight: 1 });
        }
        drawProf();
      },
    });
    const addP = profView.querySelector(".tp-addprof");
    addP.onclick = () => {
      profWork.profiles.push({ id: "", zh: "", mount_sub: "", tags: [], poses: [], extras: [] });
      drawProf();
    };
    const save = async () => {
      const msg = profView.querySelector(".tp-smsg");
      const ok = await postJson("/taglib/api/profiles", { data: profWork }, msg);
      if (ok) renderProfView();
      // 高级 JSON 保存沿用原逻辑
    };
    profView.querySelector(".tp-save").onclick = save;
    editorFoot(profView, "/taglib/api/profiles", (payload) => ({ data: payload }));
  }


  let grpWork = null;

  async function renderGrpView() {
    grpView.innerHTML = `<div style="padding:30px;text-align:center;color:#8b93a5">加载中…</div>`;
    let d;
    try { d = await fetch("/taglib/api/grouprules").then((r) => r.json()); }
    catch { grpView.innerHTML = `<div style="padding:30px;color:#ff6b6b">互斥域接口加载失败</div>`; return; }
    grpWork = { groups: JSON.parse(JSON.stringify(d.groups || [])) };
    drawGrp();
  }

  function drawGrp() {
    const groups = grpWork.groups;
    let html = `
      <div class="tp-h1">🧬 互斥关系 ${langBtnHtml()}
        <span class="tp-h1-sub">${groups.length} 个互斥域 + 跨池规则</span></div>
      <div class="tp-note">两件事在这里统一: <b>互斥域</b>(同域内任意两词天然不可能同现, 抽取时查组名交集) 与 <b>跨池规则</b>(下方 A ⟂ {B,C} 的批量事实, 如 nude ⟂ 整个服装池)。
      武器姿势的排斥不在这里 —— 在档案的 <code>conflicts_with</code> 字段。域 id 与成员都可直接改。</div>
      <input class="tp-gsearch" placeholder="🔍 过滤组名 / 成员…" style="width:100%;box-sizing:border-box;margin-bottom:10px" />
      <div class="tp-glist">`;
    groups.forEach((g, gi) => {
      html += `
        <div class="tp-gitem2" data-key="${esc(String(g.id || "") + " " + (g.members || []).join(" "))}">
          <div class="tp-gitem2-h">
            <input class="tp-ecell" data-g="${gi}" data-f="id" value="${esc(g.id || "")}" placeholder="域 id"/>
            <span class="tp-gn">${(g.members || []).length} 词</span>
            <button class="tp-edel" data-g="${gi}" title="删除该域">✕</button>
          </div>
          <div class="tp-gmem tp-gchips" data-g="${gi}"></div>
        </div>`;
    });
    html += `</div>
      <div class="tp-erow"><button class="tp-eadd tp-addgrp">＋ 新增互斥域</button></div>
      <div class="tp-cf-host"></div>
      <div class="tp-savebox">${saveBarHtml("保存互斥域")}</div>
      ${tagDatalistHtml()}
      <details class="tp-jsonbox"><summary>✏ 高级: 直接编辑 JSON</summary>
        <textarea class="tp-json" rows="14" spellcheck="false">${esc(JSON.stringify(grpWork, null, 1))}</textarea>
        <div class="tp-jrow"><button class="tp-jsave">💾 保存互斥域</button><span class="tp-jmsg"></span></div>
      </details>`;
    grpView.innerHTML = html;
    bindLang(grpView, drawGrp);
    grpView.querySelectorAll(".tp-gchips").forEach((el) => {
      const g = grpWork.groups[Number(el.dataset.g)];
      g.members = g.members || [];
      fillChips(el, g.members, drawGrp, "tp-tagdl");
    });
    grpView.querySelectorAll("input[data-g][data-f]").forEach((el) => {
      el.onchange = () => {
        const g = grpWork.groups[Number(el.dataset.g)];
        const v = el.value.trim();
        if (v) g.id = v; else delete g.id;
      };
    });
    grpView.querySelectorAll(".tp-edel[data-g]").forEach((b) => {
      b.onclick = () => { grpWork.groups.splice(Number(b.dataset.g), 1); drawGrp(); };
    });
    grpView.querySelector(".tp-addgrp").onclick = () => {
      grpWork.groups.push({ id: "new_group", members: [] });
      drawGrp();
    };
    const gs = grpView.querySelector(".tp-gsearch");
    gs.oninput = () => {
      const q = gs.value.trim().toLowerCase();
      grpView.querySelectorAll(".tp-gitem2").forEach((el) => {
        el.style.display = !q || el.dataset.key.toLowerCase().includes(q) ? "" : "none";
      });
    };
    grpView.querySelector(".tp-save").onclick = async () => {
      const ok = await postJson("/taglib/api/grouprules", { groups: grpWork.groups },
                               grpView.querySelector(".tp-smsg"));
      if (ok) renderGrpView();
    };
    editorFoot(grpView, "/taglib/api/grouprules", (payload) => ({ groups: payload.groups }));
    renderCfView();   // 跨池互斥规则同属"互斥"语义, 与域规则并到一个页面
  }


  let nlWork = null;
  let nlUncovered = [];

  async function renderNlView() {
    nlView.innerHTML = `<div style="padding:30px;text-align:center;color:#8b93a5">加载中…</div>`;
    let d;
    try { d = await fetch("/taglib/api/nl").then((r) => r.json()); }
    catch { nlView.innerHTML = `<div style="padding:30px;color:#ff6b6b">NL 接口加载失败</div>`; return; }
    nlUncovered = d.uncovered || [];
    nlWork = JSON.parse(JSON.stringify(d.data || {}));
    nlWork.families = nlWork.families || {};
    nlWork.pose_map = nlWork.pose_map || {};
    drawNl();
  }

  function _nlFams() {
    return Object.entries(nlWork.families).map(([k, v]) => [k, v || []]);
  }

  function drawNl() {
    const fams = _nlFams();
    const total = fams.reduce((n, [, v]) => n + v.length, 0);
    const pm = Object.entries(nlWork.pose_map).filter(([k]) => k !== "null");
    let html = `
      <div class="tp-h1">✍ NL 句式素材
        <span class="tp-h1-sub">${fams.length} 族 · ${total} 句 · ${pm.length} 条动作映射</span>
        <button class="tp-eadd tp-addfam" style="margin-left:auto">＋ 新增句式族</button></div>
      <div class="tp-note">末尾自然语言段的素材库。占位符 <code>{S}</code> 主语 (随人数词自动 She/He/They) · <code>{POS}</code> 所有格 · <code>{O}</code> 宾语 (从档案 obj_kind→words 解析)。
      ${nlUncovered.length ? `<br><b style="color:var(--tl-warn,#e0a35e)">⚠ 档案姿势词未进下方映射 (${nlUncovered.length}): ${esc(nlUncovered.join(", "))}</b>` : `<br><b style="color:var(--tl-ok)">✓ 全部武器姿势词已有句式覆盖</b>`}</div>`;
    fams.forEach(([fam, vs], fi) => {
      html += `
        <div class="tp-fam">
          <div class="tp-fam-h">
            <input class="tp-ecell" data-fi="${fi}" data-nf="famname" value="${esc(fam)}"/>
            <span class="tp-gn">${vs.length} 变体</span>
            <button class="tp-edel tp-delfam" data-fi="${fi}" title="删除该族">✕</button>
          </div>
          ${vs.map((v, vi) => `
            <div class="tp-fam-s tp-fam-edit">
              <input class="tp-ecell wide" data-fi="${fi}" data-vi="${vi}" data-nf="variant" value="${esc(v)}"/>
              <button class="tp-edel tp-delvar" data-fi="${fi}" data-vi="${vi}" title="删除">✕</button>
            </div>`).join("")}
          <button class="tp-eadd tp-addvar" data-fi="${fi}">＋ 变体</button>
        </div>`;
    });
    html += `
      <div class="tp-fam">
        <div class="tp-fam-h">动作词 → 句式族 <span class="tp-gn">${pm.length} 项</span>
          <button class="tp-eadd tp-addpm" style="margin-left:auto">＋ 映射</button></div>
        ${pm.map(([k, v], mi) => `
          <div class="tp-fam-s tp-fam-edit">
            <input class="tp-ecell" data-mi="${mi}" data-nf="pmkey" value="${esc(k)}" list="tp-tagdl" placeholder="动作词"/>
            <span class="tp-arrow">→</span>
            <select class="tp-ecell" data-mi="${mi}" data-nf="pmval">
              ${fams.map(([f2]) => `<option value="${esc(f2)}"${f2 === v ? " selected" : ""}>${esc(f2)}</option>`).join("")}
            </select>
            <button class="tp-edel tp-delpm" data-mi="${mi}" title="删除">✕</button>
          </div>`).join("")}
      </div>
      <div class="tp-savebox">${saveBarHtml("保存句式")}</div>
      ${tagDatalistHtml()}
      <details class="tp-jsonbox"><summary>✏ 高级: 直接编辑 JSON (含 words / intro / env / light / obj_kind 等)</summary>
        <textarea class="tp-json" rows="18" spellcheck="false">${esc(JSON.stringify(nlWork, null, 1))}</textarea>
        <div class="tp-jrow"><button class="tp-jsave">💾 保存句式</button><span class="tp-jmsg"></span></div>
      </details>`;
    nlView.innerHTML = html;
    bindLang(nlView, drawNl);

    // 族改名 (保序重建 + 同步 pose_map 指向)
    nlView.querySelectorAll('input[data-nf="famname"]').forEach((el) => {
      el.onchange = () => {
        const arr = _nlFams();
        const fi = Number(el.dataset.fi);
        const oldName = arr[fi][0];
        const nv = el.value.trim();
        if (!nv || nv === oldName || nlWork.families[nv]) { drawNl(); return; }
        const rebuilt = {};
        for (const [k, v] of arr) rebuilt[k === oldName ? nv : k] = v;
        nlWork.families = rebuilt;
        for (const [k, v] of Object.entries(nlWork.pose_map)) {
          if (v === oldName) nlWork.pose_map[k] = nv;
        }
        drawNl();
      };
    });
    nlView.querySelectorAll('input[data-nf="variant"]').forEach((el) => {
      el.onchange = () => {
        const fam = _nlFams()[Number(el.dataset.fi)][0];
        nlWork.families[fam][Number(el.dataset.vi)] = el.value;
      };
    });
    nlView.querySelectorAll(".tp-delvar").forEach((b) => {
      b.onclick = () => {
        const fam = _nlFams()[Number(b.dataset.fi)][0];
        nlWork.families[fam].splice(Number(b.dataset.vi), 1);
        drawNl();
      };
    });
    nlView.querySelectorAll(".tp-addvar").forEach((b) => {
      b.onclick = () => { _nlFams()[Number(b.dataset.fi)][1].push(""); drawNl(); };
    });
    nlView.querySelectorAll(".tp-delfam").forEach((b) => {
      b.onclick = () => { delete nlWork.families[_nlFams()[Number(b.dataset.fi)][0]]; drawNl(); };
    });
    nlView.querySelector(".tp-addfam").onclick = () => {
      let name = "new_family", i = 2;
      while (nlWork.families[name]) name = "new_family" + i++;
      nlWork.families[name] = [""];
      drawNl();
    };
    nlView.querySelectorAll('input[data-nf="pmkey"]').forEach((el) => {
      el.onchange = () => {
        const keys = Object.keys(nlWork.pose_map).filter((k) => k !== "null");
        const old = keys[Number(el.dataset.mi)];
        const nv = el.value.trim();
        if (!nv || nv === old) { drawNl(); return; }
        const rebuilt = {};
        for (const k of Object.keys(nlWork.pose_map)) rebuilt[k === old ? nv : k] = nlWork.pose_map[k];
        nlWork.pose_map = rebuilt;
        drawNl();
      };
    });
    nlView.querySelectorAll('select[data-nf="pmval"]').forEach((el) => {
      el.onchange = () => {
        const keys = Object.keys(nlWork.pose_map).filter((k) => k !== "null");
        nlWork.pose_map[keys[Number(el.dataset.mi)]] = el.value;
      };
    });
    nlView.querySelectorAll(".tp-delpm").forEach((b) => {
      b.onclick = () => {
        const keys = Object.keys(nlWork.pose_map).filter((k) => k !== "null");
        delete nlWork.pose_map[keys[Number(b.dataset.mi)]];
        drawNl();
      };
    });
    nlView.querySelector(".tp-addpm").onclick = () => {
      const f = _nlFams()[0];
      nlWork.pose_map["new action"] = f ? f[0] : "new_family";
      drawNl();
    };
    nlView.querySelector(".tp-save").onclick = async () => {
      const ok = await postJson("/taglib/api/nl", { data: nlWork }, nlView.querySelector(".tp-smsg"));
      if (ok) renderNlView();
    };
    editorFoot(nlView, "/taglib/api/nl", (payload) => ({ data: payload }));
  }

  let cfRights = [];   // 新增规则的右侧引用 [{kind, value}]

  function cfKindName(kind) {
    return kind === "tag" ? "标签" : kind === "sub" ? "二级分类" : "一级分类";
  }

  function cfDatalist(kind) {
    const opts = [];
    if (kind === "tag") {
      for (const c of libCats()) for (const s of c.subcategories || [])
        for (const t of s.tags || []) opts.push(t.en);
    } else if (kind === "sub") {
      for (const c of libCats()) for (const s of c.subcategories || [])
        opts.push(`${c.name}/${s.name}`);
    } else {
      for (const c of libCats()) opts.push(c.name);
    }
    return `<datalist id="tp-cf-dl-${kind}">${opts.map((v) => `<option value="${escapeHtml(String(v))}"/>`).join("")}</datalist>`;
  }

  async function renderCfView() {
    // v1.6.0: 原「🧷 防冲突关系」独立页签已删, 规则列表并入「🧬 互斥域」页
    // (两者都是"两两互斥", 用户不该判断该去哪个页签加互斥)。
    const cfView = grpView.querySelector(".tp-cf-host");
    if (!cfView) return;
    cfView.innerHTML = `<div style="padding:20px;text-align:center;color:#8b93a5">加载中…</div>`;
    let st;
    try {
      st = await fetch("/taglib/api/conflicts").then((r) => r.json());
    } catch {
      cfView.innerHTML = `<div class="tp-empty" style="padding:30px;color:#8b93a5">反冲突规则加载失败</div>`;
      return;
    }
    const rules = st.rules || [];
    cfRights = [];
    const invalidVals = new Set((st.invalid || []).map((x) => String(x.value)));
    cfView.innerHTML = `
      <div class="tp-cf-stats">
        共 <b style="color:#54a0ff">${rules.length}</b> 条双向互斥规则
        ${(st.invalid || []).length ? `，<span style="color:#ff6b6b">⚠ ${invalidVals.size} 个失效引用</span>` : ""}
        —— 填充/自动模式抽到一侧，另一侧自动让位（手动点选不受影响）
      </div>
      <div class="tp-cf-list"></div>
      <div class="tp-cf-h">新增规则</div>
      <div class="tp-cf-form">
        <div class="tp-cf-frow">
          <span class="cf-klab">左侧</span>
          <select class="cf-lkind">
            <option value="tag">标签</option>
            <option value="sub">二级分类</option>
            <option value="cat">一级分类</option>
          </select>
          <input class="cf-linput" list="tp-cf-dl-tag" placeholder="标签英文…" style="flex:1;min-width:180px"/>
        </div>
        <div class="tp-cf-frow">
          <span class="cf-klab">右侧</span>
          <select class="cf-rkind">
            <option value="tag">标签</option>
            <option value="sub">二级分类</option>
            <option value="cat">一级分类</option>
          </select>
          <input class="cf-rinput" list="tp-cf-dl-tag" placeholder="可连续添加多个…" style="flex:1;min-width:180px"/>
          <button class="tp-cf-add">＋ 添加到右侧</button>
        </div>
        <div class="tp-cf-rights"></div>
        <button class="tp-cf-save">💾 保存规则</button>
        <span class="tp-cf-note" style="font-size:11px;color:#6b7385;margin-left:10px">保存后立即写入 data/taglib/conflicts.json</span>
      </div>
      ${cfDatalist("tag")}${cfDatalist("sub")}${cfDatalist("cat")}`;

    const listBox = cfView.querySelector(".tp-cf-list");
    if (!rules.length) {
      listBox.innerHTML = `<div style="color:#8b93a5;font-size:12px">暂无规则</div>`;
    }
    for (const r of rules) {
      const card = document.createElement("div");
      card.className = "tp-cf-rule";
      const warns = [];
      if (invalidVals.has(String(r.left?.value))) warns.push(escapeHtml(String(r.left?.value)));
      const rts = (r.right || []).map((ref) => {
        const bad = invalidVals.has(String(ref.value));
        if (bad) warns.push(escapeHtml(String(ref.value)));
        return `<span class="cf-rt">${escapeHtml(String(ref.value))}</span>`;
      }).join(" ");
      card.innerHTML = `
        <span class="cf-l">${escapeHtml(String(r.left?.value ?? "?"))}</span>
        <span class="cf-vs">⟂</span>${rts}
        ${r.note ? `<span class="cf-note">${escapeHtml(String(r.note))}</span>` : ""}
        ${warns.length ? `<span class="cf-warn">⚠ 失效: ${warns.join("、")}</span>` : ""}
        <button class="cf-del" title="删除规则">✕</button>`;
      card.querySelector(".cf-del").onclick = async () => {
        const rest = rules.filter((x) => x !== r);
        try {
          const res = await fetch("/taglib/api/conflicts", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ rules: rest }),
          });
          const out = await res.json();
          if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
          toast("规则已删除");
          renderCfView();
        } catch (err) {
          toast(`删除失败: ${err.message}`, true);
        }
      };
      listBox.appendChild(card);
    }

    // 新增表单
    const lkind = cfView.querySelector(".cf-lkind");
    const linput = cfView.querySelector(".cf-linput");
    const rkind = cfView.querySelector(".cf-rkind");
    const rinput = cfView.querySelector(".cf-rinput");
    const rightsBox = cfView.querySelector(".tp-cf-rights");
    const renderRights = () => {
      rightsBox.innerHTML = cfRights.length
        ? cfRights.map((ref, i) =>
            `<span class="cf-rt-chip">${escapeHtml(String(ref.value))}<span class="x" data-i="${i}">✕</span></span>`).join("")
        : `<span style="color:#6b7385;font-size:11px">尚未添加右侧对象</span>`;
      rightsBox.querySelectorAll(".x").forEach((x) => {
        x.onclick = () => { cfRights.splice(Number(x.dataset.i), 1); renderRights(); };
      });
    };
    renderRights();
    lkind.onchange = () => {
      const dl = cfView.querySelector(`#tp-cf-dl-${lkind.value}`);
      linput.setAttribute("list", `tp-cf-dl-${lkind.value}`);
      if (dl) { dl.remove(); cfView.appendChild(dl); }
      linput.value = "";
    };
    rkind.onchange = () => {
      const dl = cfView.querySelector(`#tp-cf-dl-${rkind.value}`);
      rinput.setAttribute("list", `tp-cf-dl-${rkind.value}`);
      if (dl) { dl.remove(); cfView.appendChild(dl); }
      rinput.value = "";
    };
    cfView.querySelector(".tp-cf-add").onclick = () => {
      const v = rinput.value.trim();
      if (!v) return toast("先填右侧对象", true);
      const ref = { kind: rkind.value, value: v };
      if (cfRights.some((x) => x.kind === ref.kind && String(x.value).toLowerCase() === String(v).toLowerCase()))
        return toast("已添加过", true);
      cfRights.push(ref);
      rinput.value = "";
      renderRights();
    };
    cfView.querySelector(".tp-cf-save").onclick = async () => {
      const lv = linput.value.trim();
      if (!lv) return toast("先填左侧对象", true);
      if (!cfRights.length) return toast("至少添加一个右侧对象", true);
      const rule = { id: `cf.${Date.now().toString(36)}.${Math.floor(Math.random() * 999)}`,
                     left: { kind: lkind.value, value: lv },
                     right: cfRights.slice() };
      try {
        const res = await fetch("/taglib/api/conflicts", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rules: [...rules, rule] }),
        });
        const out = await res.json();
        if (!res.ok || !out.ok) throw new Error(out.error || `HTTP ${res.status}`);
        toast(`✅ 规则已保存 (共 ${out.count} 条)`);
        renderCfView();
      } catch (err) {
        toast(`保存失败: ${err.message}`, true);
      }
    };
  }

  function switchTab(tab) {
    ui.tab = tab;
    rootEl.querySelector(".tp-hometab")?.classList.toggle("active", tab === "home");
    rootEl.querySelector(".tp-picktab").classList.toggle("active", tab === "pick");
    rootEl.querySelector(".tp-settab").classList.toggle("active", tab === "settings");
    rootEl.querySelector(".tp-proftab")?.classList.toggle("active", tab === "prof");
    rootEl.querySelector(".tp-grptab")?.classList.toggle("active", tab === "grp");
    rootEl.querySelector(".tp-nltab")?.classList.toggle("active", tab === "nl");
    rootEl.querySelector(".tp-prtab")?.classList.toggle("active", tab === "preset");
    for (const el of pickCols) el.style.display = tab === "pick" ? "" : "none";
    // 右栏只在挑标签页出现 (它是手动挑选的工作区, 其他页用不到)
    if (sideBox) sideBox.hidden = tab !== "pick";
    homeView.style.display = tab === "home" ? "flex" : "none";
    setView.style.display = tab === "settings" ? "block" : "none";
    profView.style.display = tab === "prof" ? "block" : "none";
    grpView.style.display = tab === "grp" ? "block" : "none";
    nlView.style.display = tab === "nl" ? "block" : "none";
    prView.style.display = tab === "preset" ? "block" : "none";
    searchEl.style.visibility = tab === "pick" ? "visible" : "hidden";
    const info = $(".tp-footinfo");
    if (tab === "pick") {
      info.innerHTML = `已挑选 <b class="tp-count">${ui.picked.length}</b> 个`;
    } else if (tab === "home") {
      info.innerHTML = `🏠 流水线首页 · 按官方六段次序 · 点入口直接进该类目`;
    } else if (tab === "prof") {
      info.innerHTML = `⚔ 档案维护 (高级) · 挑标签页右栏可直接选姿势`;
    } else if (tab === "grp") {
      info.innerHTML = `🧬 同域任意两词永不共存 (引擎抽取期拦截)`;
    } else if (tab === "nl") {
      info.innerHTML = `✍ 句式素材 · 与标签同 seed 确定性输出`;
    } else {
      info.innerHTML = `节点参数即改即存 · 全局偏好双向同步`;
    }
    // 底部按钮: 挑选/排除 -> 取消+确定; 管理/防冲突/设置 -> 仅关闭
    const pickLike = tab === "pick";
    $(".tp-cancel").style.display = pickLike ? "" : "none";
    $(".tp-ok").style.display = pickLike ? "" : "none";
    $(".tp-close2").style.display = pickLike ? "none" : "";
    if (tab === "settings") renderSettingsView();
    if (tab === "prof") renderProfView();
    if (tab === "grp") renderGrpView();
    if (tab === "nl") renderNlView();
    if (tab === "preset") renderPresetView();
  }
  $(".tp-hometab").onclick = () => switchTab("home");
  rootEl.querySelector(".tp-picktab").onclick = () => switchTab("pick");
  rootEl.querySelector(".tp-prtab").onclick = () => switchTab("preset");
  rootEl.querySelector(".tp-settab").onclick = () => switchTab("settings");
  rootEl.querySelector(".tp-proftab")?.addEventListener("click", () => switchTab("prof"));
  rootEl.querySelector(".tp-grptab")?.addEventListener("click", () => switchTab("grp"));
  rootEl.querySelector(".tp-nltab")?.addEventListener("click", () => switchTab("nl"));
  $(".tp-close2").onclick = onCancel;

  searchEl.oninput = () => { ui.filter = searchEl.value; renderChips(); };
  $(".tp-cancel").onclick = onCancel;
  $(".tp-ok").onclick = () => onConfirm(ui.picked);

  /* ---------- 键盘可达 (1.9.0 批次 5) ----------
     现状缺口: 标签云里的 chip 全是不可聚焦的 span, 键盘用户一个都点不到。
     用 roving tabindex: 整片云只占一个 Tab 位, 进去之后方向键在 chip 间走, Enter 选中。 */
  function chipsInGrid() {
    return [...chipsBox.querySelectorAll(".tp-tag[data-kbd]")].filter((el) => el.offsetParent !== null);
  }
  function setRoving(el) {
    for (const x of chipsBox.querySelectorAll(".tp-tag[data-kbd]")) {
      x.tabIndex = x === el ? 0 : -1;
    }
  }
  function moveChipFocus(from, dir) {
    const els = chipsInGrid();
    const i = els.indexOf(from);
    if (i < 0) return;
    let target = null;
    if (dir === "left") target = els[i - 1];
    else if (dir === "right") target = els[i + 1];
    else {
      const r = from.getBoundingClientRect();
      let best = Infinity;
      for (const el of els) {
        if (el === from) continue;
        const b = el.getBoundingClientRect();
        if (dir === "down" ? b.top <= r.top + 2 : b.top >= r.top - 2) continue;
        const dy = Math.abs(b.top - r.top);
        const dx = Math.abs(b.left - r.left);
        const score = dy + dx * 2;         // 同列优先, 其次最近的
        if (score < best) { best = score; target = el; }
      }
    }
    if (!target) return;
    setRoving(target);
    target.focus();
    target.scrollIntoView({ block: "nearest" });
  }
  rootEl.addEventListener("keydown", (e) => {
    const t = e.target;
    const inField = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA"
      || t.tagName === "SELECT" || t.isContentEditable);
    if (e.key === "/" && !inField) { e.preventDefault(); searchEl.focus(); return; }
    if (e.key === "Escape" && t === searchEl && searchEl.value) {
      e.preventDefault(); searchEl.value = ""; ui.filter = ""; renderChips(); return;
    }
    if (!t || !t.classList || !t.classList.contains("tp-tag")) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); t.click(); return; }
    const dir = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" }[e.key];
    if (dir) { e.preventDefault(); moveChipFocus(t, dir); }
  });

  renderCats();
  renderChips();

  // 默认落到流水线首页: 先看"提示词是怎么拼起来的", 再点进具体类目。
  // onPick 复用现成的挑标签视图 —— 直接设 activeAxis 后重渲染, 不另做一套筛选。
  switchTab("home");
  renderPipeline(homeView, {
    onPick: (axisId, axisZh) => {
      ui.activeAxis = axisId;
      ui.activeSlot = null;
      ui.openAxes?.add(axisZh);          // 展开该轴的槽位, 落地即是可挑状态
      switchTab("pick");
      renderCats();
      renderChips();
    },
    onIncomplete: (inc) => {
      const c = inc?.counts || {};
      toast(`待完善 ${inc?.total ?? 0} 项 · 未建档武器 ${c.weapon_unregistered ?? 0} · ` +
            `陈旧引用 ${c.dangling_ref ?? 0} · 缺句式族 ${c.pose_no_family ?? 0}`);
    },
  });

  return {
    destroy() { disposePipeline(homeView); },
    libTouched: () => ui.libTouched,
    /* 供节点面板"排除类目"控件直接跳到对应位置用 (避免在面板里再实现一套排除 UI)。 */
    openTab(tab, opts) {
      switchTab(tab || "pick");
      if (opts && opts.openExclude) {
        const d = catsBox.querySelector(".tp-exc");
        if (d) { d.open = true; d.scrollIntoView({ block: "nearest" }); }
      }
    },
  };
}


export { mountTagPicker };
