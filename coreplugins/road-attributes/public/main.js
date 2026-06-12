// 桥梁数据库 — main.js entry
// Layout (per the user's mockup):
//   ┌── tab bar (5 tabs: 桥梁/隧道/涵洞/边坡/路段)  +  [global search]  [⟳] ──┐
//   │ [➕新增] [✎编辑] [🗑删除] [📷照片] [📤导出] [📍地图]                │
//   │ ┌── col-header filter row (筛选… dropdowns) ──┐                  │
//   │ │ ☐ │评定│线路编号│线路名称│桥梁编号│桥梁名称│…│经纬度│            │
//   │ ├── table rows ─────────────────────────────────┤                  │
//   │ ├── « ‹ 1/23 › »   每页 10 条 ▾   共有 230 项  │                  │
//   └────────────────────────────────────────────────────┘

(function () {
  'use strict';

  // =========================================================================
  // Constants
  // =========================================================================
  const TABS = [
    { key: 'bridges',         label: '桥梁基本信息' },
    { key: 'tunnels',         label: '隧道基本信息' },
    { key: 'culverts',        label: '涵洞基本数据' },
    { key: 'slopes',          label: '边坡基本数据' },
    { key: 'road-segments',   label: '路段健康趋势' },
  ];

  // The 14 list columns (last column is the photo thumbnail).
  // The 'rating' kind renders as a circular badge.
  // The 'photo' kind renders a 36px-wide thumbnail from general_photo_url.
  const COLUMNS = [
    { key: 'eval_level',      label: '评定等级',     kind: 'rating', width: 64 },
    { key: 'route_id',        label: '线路编号',     kind: 'enum',   width: 88 },
    { key: 'route_name',      label: '线路名称',     kind: 'text',   width: 200 },
    { key: 'bridge_id_code',  label: '桥梁编号',     kind: 'text',   width: 200 },
    { key: 'bridge_name',     label: '桥梁名称',     kind: 'text',   width: 220, link: true },
    { key: 'length_m',        label: '桥梁全长(米)', kind: 'text',   width: 88 },
    { key: 'max_span_m',      label: '最大跨径(米)', kind: 'text',   width: 88 },
    { key: 'stake_no',        label: '桥位桩号',     kind: 'text',   width: 110 },
    { key: 'design_stake_no', label: '设计桩号',     kind: 'text',   width: 110 },
    { key: 'bridge_type',     label: '桥梁类型',     kind: 'enum',   width: 160 },
    { key: 'span_category',   label: '跨径分类',     kind: 'enum',   width: 80 },
    { key: 'longitude',       label: '经度',         kind: 'text',   width: 90 },
    { key: 'latitude',        label: '纬度',         kind: 'text',   width: 90 },
    { key: 'photo',           label: '照片',         kind: 'photo',  width: 64 },
  ];

  // Sub-table descriptors (label shown in detail modal tabs).
  const SUBTABLES = [
    { kind: 'evaluations',       label: '评定记录' },
    { kind: 'piers',             label: '桥墩' },
    { kind: 'bearings',          label: '支座' },
    { kind: 'main-beams',        label: '主梁/桥面系' },
    { kind: 'expansion-joints',  label: '伸缩缝' },
    { kind: 'diseases',          label: '病害' },
    { kind: 'archives',          label: '档案' },
  ];

  // Map rating value (一类桥/二类桥) to a CSS badge color. Fallback: gray.
  function ratingClass(v) {
    if (!v) return 'ra-badge ra-badge-unknown';
    const s = String(v);
    if (s.includes('一类') || /^[1-2]$/.test(s)) return 'ra-badge ra-badge-good';
    if (s.includes('二类') || /^[3]$/.test(s)) return 'ra-badge ra-badge-ok';
    if (s.includes('三类') || /^[4]$/.test(s)) return 'ra-badge ra-badge-warn';
    if (s.includes('四类') || /^[5]$/.test(s)) return 'ra-badge ra-badge-bad';
    if (s.includes('五类')) return 'ra-badge ra-badge-bad';
    return 'ra-badge ra-badge-ok';
  }

  // =========================================================================
  // State
  // =========================================================================
  const state = {
    tab: 'bridges',
    rows: [],
    total: 0,
    page: 1,
    pageSize: 10,
    totalPages: 1,
    filters: {},   // { columnKey: value }
    q: '',
    ordering: 'route_id,bridge_id_code',   // comma-separated; "-field" = DESC
    selected: new Set(),   // ids on the CURRENT page only (so selection clears on page change)
    meta: null,
    placeholder: null,
    detailId: null,
    detailData: null,
    stats: null,   // cached stats for the summary strip + stats modal
  };

  // =========================================================================
  // App shell
  // =========================================================================
  const APP_HTML = [
    '<div class="ra-app">',
    '  <div class="ra-header">',
    '    <div class="ra-tabs" id="ra-tabs"></div>',
    '    <div class="ra-global">',
    '      <input type="text" id="ra-search" placeholder="🔍 全局模糊搜索" />',
    '      <button class="ra-icon-btn" id="ra-refresh" title="刷新"><i class="fa fa-refresh"></i></button>',
    '    </div>',
    '  </div>',
    '',
    '  <div class="ra-toolbar" id="ra-toolbar"></div>',
    '',
    '  <div class="ra-summary" id="ra-summary"></div>',
    '',
    '  <div class="ra-filter-row" id="ra-filter-row"></div>',
    '',
    '  <div class="ra-table-wrap">',
    '    <table class="ra-table" id="ra-table"><thead id="ra-thead"></thead><tbody id="ra-tbody"></tbody></table>',
    '    <div class="ra-empty" id="ra-empty" style="display:none"></div>',
    '  </div>',
    '',
    '  <div class="ra-footer" id="ra-footer"></div>',
    '',
    '  <div class="ra-modal-bg" id="ra-modal" style="display:none">',
    '    <div class="ra-modal" id="ra-modal-inner"></div>',
    '  </div>',
    '  <div class="ra-loading" id="ra-loading" style="display:none"><div class="ra-spinner"></div></div>',
    '  <div class="ra-toast" id="ra-toast"></div>',
    '</div>',
  ].join('\n');

  const APP_CSS = [
    // Reset + base
    'body { margin: 0; }',
    '.ra-app { display:flex; flex-direction:column; height:calc(100vh - 80px); background:#fff; color:#333; font:13px/1.5 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; padding:0; box-sizing:border-box; }',
    '.ra-app *, .ra-app *::before, .ra-app *::after { box-sizing:border-box; }',
    // Tabs
    '.ra-header { display:flex; align-items:center; border-bottom:1px solid #e6e6e6; padding:0 16px; background:#fafafa; }',
    '.ra-tabs { display:flex; flex:1; }',
    '.ra-tab { background:transparent; border:none; border-bottom:2px solid transparent; padding:12px 18px; cursor:pointer; color:#666; font-size:14px; margin-right:4px; }',
    '.ra-tab:hover { color:#409eff; }',
    '.ra-tab.active { color:#409eff; border-bottom-color:#409eff; font-weight:500; }',
    '.ra-global { display:flex; align-items:center; gap:8px; }',
    '.ra-global input { border:1px solid #dcdfe6; border-radius:4px; padding:5px 10px; width:220px; font:inherit; }',
    '.ra-global input:focus { outline:none; border-color:#409eff; }',
    '.ra-icon-btn { background:#fff; border:1px solid #dcdfe6; border-radius:4px; padding:5px 10px; cursor:pointer; color:#666; }',
    '.ra-icon-btn:hover { color:#409eff; border-color:#409eff; }',
    // Toolbar
    '.ra-toolbar { display:flex; align-items:center; gap:10px; padding:10px 16px; border-bottom:1px solid #ebeef5; background:#fff; }',
    '.ra-tb-btn { background:#fff; border:1px solid #dcdfe6; color:#606266; padding:6px 14px; border-radius:4px; cursor:pointer; font-size:13px; display:inline-flex; align-items:center; gap:4px; }',
    '.ra-tb-btn:hover { color:#409eff; border-color:#c6e2ff; background:#ecf5ff; }',
    '.ra-tb-btn:disabled { color:#c0c4cc; cursor:not-allowed; background:#f5f7fa; border-color:#e4e7ed; }',
    '.ra-tb-btn:disabled:hover { color:#c0c4cc; background:#f5f7fa; border-color:#e4e7ed; }',
    '.ra-tb-btn-primary { background:#409eff; border-color:#409eff; color:#fff; }',
    '.ra-tb-btn-primary:hover { background:#66b1ff; border-color:#66b1ff; color:#fff; }',
    '.ra-tb-btn-primary:disabled { background:#a0cfff; border-color:#a0cfff; }',
    '.ra-tb-btn-danger { color:#f56c6c; border-color:#fbc4c4; }',
    '.ra-tb-btn-danger:hover { color:#f56c6c; background:#fef0f0; border-color:#f56c6c; }',
    // Filter row
    '.ra-filter-row { display:flex; align-items:center; border-bottom:1px solid #ebeef5; background:#fafbfc; padding:6px 16px; gap:6px; overflow-x:auto; }',
    '.ra-filter-cell { display:flex; flex-direction:column; min-width:80px; }',
    '.ra-filter-cell label { font-size:11px; color:#909399; margin-bottom:2px; white-space:nowrap; }',
    '.ra-filter-cell input, .ra-filter-cell select { border:1px solid #dcdfe6; background:#fff; border-radius:3px; padding:3px 6px; font:inherit; min-width:80px; }',
    '.ra-filter-cell input:focus, .ra-filter-cell select:focus { outline:none; border-color:#409eff; }',
    '.ra-filter-clear { color:#909399; cursor:pointer; font-size:12px; padding:4px 8px; }',
    '.ra-filter-clear:hover { color:#f56c6c; }',
    // Table
    '.ra-table-wrap { flex:1; overflow:auto; background:#fff; }',
    '.ra-table { width:100%; border-collapse:collapse; font-size:13px; }',
    '.ra-table thead th { background:#f5f7fa; color:#606266; font-weight:500; padding:8px 12px; border-bottom:1px solid #ebeef5; text-align:left; position:sticky; top:0; z-index:2; white-space:nowrap; }',
    '.ra-table tbody td { padding:8px 12px; border-bottom:1px solid #ebeef5; color:#606266; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:300px; }',
    '.ra-table tbody tr:hover { background:#f5f7fa; }',
    '.ra-table tbody tr.selected { background:#ecf5ff; }',
    '.ra-table input[type=checkbox] { cursor:pointer; }',
    '.ra-table a.ra-link { color:#409eff; text-decoration:none; }',
    '.ra-table a.ra-link:hover { text-decoration:underline; }',
    // Rating badge
    '.ra-badge { display:inline-block; min-width:24px; height:24px; line-height:24px; border-radius:50%; text-align:center; font-weight:600; font-size:12px; }',
    '.ra-badge-good { background:#67c23a; color:#fff; }',
    '.ra-badge-ok   { background:#e6a23c; color:#fff; }',
    '.ra-badge-warn { background:#f56c6c; color:#fff; }',
    '.ra-badge-bad  { background:#c45656; color:#fff; }',
    '.ra-badge-unknown { background:#909399; color:#fff; }',
    // Empty state
    '.ra-empty { padding:40px; text-align:center; color:#909399; }',
    // Footer / pagination
    '.ra-footer { display:flex; align-items:center; justify-content:space-between; padding:10px 16px; border-top:1px solid #ebeef5; background:#fff; }',
    '.ra-pager { display:flex; align-items:center; gap:6px; }',
    '.ra-page-btn { background:#fff; border:1px solid #dcdfe6; padding:4px 10px; min-width:30px; text-align:center; cursor:pointer; border-radius:3px; color:#606266; }',
    '.ra-page-btn:hover:not(:disabled) { color:#409eff; border-color:#409eff; }',
    '.ra-page-btn:disabled { color:#c0c4cc; cursor:not-allowed; background:#f5f7fa; }',
    '.ra-page-btn.active { background:#409eff; color:#fff; border-color:#409eff; }',
    '.ra-total { color:#606266; font-size:13px; }',
    // Loading + toast
    '.ra-loading { position:fixed; inset:0; background:rgba(255,255,255,0.6); z-index:1500; display:flex; align-items:center; justify-content:center; }',
    '.ra-spinner { width:28px; height:28px; border:3px solid #ebeef5; border-top-color:#409eff; border-radius:50%; animation:ra-spin 0.7s linear infinite; }',
    '@keyframes ra-spin { to { transform: rotate(360deg); } }',
    '.ra-toast { position:fixed; bottom:24px; right:24px; background:#67c23a; color:#fff; padding:8px 18px; border-radius:4px; z-index:2000; box-shadow:0 2px 12px rgba(0,0,0,0.15); display:none; }',
    // Modal
    '.ra-modal-bg { position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:1000; display:flex; align-items:flex-start; justify-content:center; overflow-y:auto; padding:40px 0; }',
    '.ra-modal { background:#fff; border-radius:6px; min-width:680px; max-width:90vw; max-height:80vh; overflow:hidden; display:flex; flex-direction:column; box-shadow:0 4px 24px rgba(0,0,0,0.2); }',
    '.ra-modal-head { display:flex; align-items:center; justify-content:space-between; padding:14px 20px; border-bottom:1px solid #ebeef5; }',
    '.ra-modal-title { font-size:16px; font-weight:600; }',
    '.ra-modal-close { cursor:pointer; color:#909399; font-size:20px; line-height:1; padding:4px 8px; }',
    '.ra-modal-close:hover { color:#f56c6c; }',
    '.ra-modal-body { padding:16px 20px; overflow-y:auto; flex:1; }',
    '.ra-modal-foot { padding:12px 20px; border-top:1px solid #ebeef5; display:flex; gap:8px; justify-content:flex-end; background:#fafafa; }',
    '.ra-modal-foot .left { margin-right:auto; }',
    // Detail layout
    '.ra-detail-tabs { display:flex; border-bottom:1px solid #ebeef5; margin-bottom:12px; }',
    '.ra-detail-tab { padding:8px 16px; cursor:pointer; color:#606266; border-bottom:2px solid transparent; }',
    '.ra-detail-tab:hover { color:#409eff; }',
    '.ra-detail-tab.active { color:#409eff; border-bottom-color:#409eff; }',
    '.ra-detail-section { display:grid; grid-template-columns:repeat(2, 1fr); gap:8px 24px; }',
    '.ra-detail-section.cols-3 { grid-template-columns:repeat(3, 1fr); }',
    '.ra-field { display:flex; padding:4px 0; border-bottom:1px dashed #f0f0f0; align-items:flex-start; }',
    '.ra-field-label { color:#909399; font-size:12px; min-width:120px; flex-shrink:0; padding-top:2px; }',
    '.ra-field-value { color:#303133; font-size:13px; word-break:break-all; }',
    // Form
    '.ra-form-row { margin-bottom:12px; display:flex; align-items:center; }',
    '.ra-form-row label { min-width:120px; color:#606266; font-size:13px; }',
    '.ra-form-row input, .ra-form-row select, .ra-form-row textarea { flex:1; border:1px solid #dcdfe6; border-radius:4px; padding:6px 10px; font:inherit; }',
    '.ra-form-row input:focus, .ra-form-row select:focus, .ra-form-row textarea:focus { outline:none; border-color:#409eff; }',
    // Subtable
    '.ra-subtable { width:100%; border-collapse:collapse; font-size:12px; }',
    '.ra-subtable th { background:#f5f7fa; padding:6px 10px; border-bottom:1px solid #ebeef5; text-align:left; color:#606266; }',
    '.ra-subtable td { padding:6px 10px; border-bottom:1px solid #f0f0f0; color:#606266; }',
    '.ra-photo-grid { display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; }',
    '.ra-photo-slot { background:#fafafa; border:1px dashed #dcdfe6; border-radius:4px; min-height:160px; display:flex; align-items:center; justify-content:center; flex-direction:column; padding:8px; }',
    '.ra-photo-slot img { max-width:100%; max-height:200px; border-radius:3px; }',
    '.ra-photo-slot .ph-label { color:#909399; font-size:12px; margin-bottom:6px; }',
    '.ra-photo-slot .ph-actions { margin-top:6px; display:flex; gap:6px; }',
    // Summary strip
    '.ra-summary { display:grid; grid-template-columns:repeat(5, 1fr); gap:8px; padding:10px 16px; background:#fafbfc; border-bottom:1px solid #ebeef5; }',
    '.ra-summary-card { background:#fff; border:1px solid #ebeef5; border-radius:4px; padding:10px 14px; display:flex; align-items:center; gap:10px; }',
    '.ra-summary-icon { width:36px; height:36px; border-radius:50%; background:#ecf5ff; color:#409eff; display:flex; align-items:center; justify-content:center; font-size:16px; flex-shrink:0; }',
    '.ra-summary-text { line-height:1.2; }',
    '.ra-summary-num { font-size:20px; font-weight:600; color:#303133; }',
    '.ra-summary-lbl { font-size:12px; color:#909399; }',
    '.ra-summary-card.alt1 .ra-summary-icon { background:#f0f9eb; color:#67c23a; }',
    '.ra-summary-card.alt2 .ra-summary-icon { background:#fdf6ec; color:#e6a23c; }',
    '.ra-summary-card.alt3 .ra-summary-icon { background:#fef0f0; color:#f56c6c; }',
    '.ra-summary-card.alt4 .ra-summary-icon { background:#ecf5ff; color:#409eff; }',
    // Sort indicator on table header
    '.ra-sortable { cursor:pointer; user-select:none; }',
    '.ra-sortable:hover { background:#ecf5ff; color:#409eff; }',
    '.ra-sort-arrow { display:inline-block; width:10px; margin-left:4px; opacity:0.4; }',
    '.ra-sortable.sorted-asc .ra-sort-arrow, .ra-sortable.sorted-desc .ra-sort-arrow { opacity:1; color:#409eff; }',
    // Stats modal bar chart
    '.ra-bar-list { padding:8px 16px; }',
    '.ra-bar-row { display:grid; grid-template-columns:140px 1fr 60px; align-items:center; gap:10px; padding:6px 0; border-bottom:1px solid #f5f5f5; }',
    '.ra-bar-row .ra-bar-lbl { color:#606266; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }',
    '.ra-bar-row .ra-bar-track { background:#f5f7fa; border-radius:3px; height:16px; overflow:hidden; }',
    '.ra-bar-row .ra-bar-fill { background:linear-gradient(90deg, #409eff, #66b1ff); height:100%; border-radius:3px; transition:width 0.4s; }',
    '.ra-bar-row .ra-bar-val { text-align:right; color:#303133; font-size:13px; font-weight:500; }',
    '.ra-stats-grid { display:grid; grid-template-columns:1fr 1fr; gap:24px; padding:0 16px 16px; }',
    '.ra-stats-section h4 { font-size:13px; color:#909399; margin:0 0 8px; font-weight:500; padding-bottom:6px; border-bottom:1px solid #ebeef5; }',
    // Photo thumbnail column
    '.ra-thumb { width:44px; height:32px; object-fit:cover; border-radius:3px; cursor:zoom-in; border:1px solid #ebeef5; }',
    '.ra-thumb:hover { border-color:#409eff; transform:scale(1.05); }',
    '.ra-thumb-empty { color:#c0c4cc; font-size:18px; }',
    // Photo preview modal
    '.ra-photo-viewer { display:flex; align-items:center; justify-content:center; flex-direction:column; padding:20px; min-height:60vh; background:#000; }',
    '.ra-photo-viewer img { max-width:80vw; max-height:70vh; object-fit:contain; }',
    '.ra-photo-viewer .ph-caption { color:#fff; margin-top:12px; font-size:14px; opacity:0.7; }',
    // Detail header (hero with photo)
    '.ra-detail-hero { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px; }',
    '.ra-detail-hero .ra-photo-slot { background:#fafafa; border:1px solid #ebeef5; border-radius:4px; min-height:140px; display:flex; align-items:center; justify-content:center; overflow:hidden; position:relative; }',
    '.ra-detail-hero .ra-photo-slot img { max-width:100%; max-height:240px; object-fit:cover; }',
    '.ra-detail-hero .ra-photo-slot .ph-label { position:absolute; top:6px; left:6px; background:rgba(255,255,255,0.9); color:#606266; font-size:11px; padding:2px 8px; border-radius:3px; }',
    '.ra-detail-hero .ra-photo-slot .ph-empty { color:#c0c4cc; font-size:13px; padding:30px 0; }',
  ].join('\n');

  // =========================================================================
  // Utilities
  // =========================================================================
  function getCookie(name) {
    const m = document.cookie.match(new RegExp('(^|;)\\s*' + name + '=([^;]+)'));
    return m ? decodeURIComponent(m[2]) : '';
  }
  function api(path, options) {
    options = options || {};
    const headers = Object.assign({
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken'),
      'Referer': window.location.origin,
    }, options.headers || {});
    if (options.body instanceof FormData) {
      delete headers['Content-Type']; // browser sets the multipart boundary
    }
    return fetch('/api/plugins/road-attributes' + path, {
      method: options.method || 'GET',
      credentials: 'same-origin',
      headers: headers,
      body: options.body
        ? (options.body instanceof FormData ? options.body : JSON.stringify(options.body))
        : undefined,
    }).then(r => {
      if (r.status === 204) return null;
      const ct = r.headers.get('Content-Type') || '';
      if (ct.includes('application/json')) {
        return r.json().then(j => {
          if (!r.ok) {
            const err = new Error(j && (j.detail || j.error) || ('HTTP ' + r.status));
            err.body = j;
            throw err;
          }
          return j;
        });
      }
      return r.text().then(t => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return t;
      });
    });
  }
  function showLoading() { document.getElementById('ra-loading').style.display = 'flex'; }
  function hideLoading() { document.getElementById('ra-loading').style.display = 'none'; }
  function toast(msg, kind) {
    const t = document.getElementById('ra-toast');
    t.textContent = msg;
    t.style.background = kind === 'err' ? '#f56c6c' : kind === 'warn' ? '#e6a23c' : '#67c23a';
    t.style.display = 'block';
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.style.display = 'none', 2500);
  }
  function escHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function showEmpty(msg) {
    const t = document.getElementById('ra-tbody');
    t.innerHTML = '';
    const e = document.getElementById('ra-empty');
    e.textContent = msg;
    e.style.display = 'block';
  }
  function hideEmpty() { document.getElementById('ra-empty').style.display = 'none'; }

  // =========================================================================
  // Render: tabs + toolbar + global search
  // =========================================================================
  function renderTabs() {
    document.getElementById('ra-tabs').innerHTML = TABS.map(t =>
      `<button class="ra-tab${t.key === state.tab ? ' active' : ''}" data-tab="${t.key}">${escHtml(t.label)}</button>`
    ).join('');
  }
  function renderToolbar() {
    const tb = document.getElementById('ra-toolbar');
    const sel = state.selected.size;
    const oneSelected = sel === 1;
    const anySelected = sel > 0;
    const isBridgesTab = state.tab === 'bridges';
    const selLabel = anySelected ? ` (${sel})` : '';
    tb.innerHTML = [
      '<button class="ra-tb-btn ra-tb-btn-primary" id="ra-b-new"  ' + (isBridgesTab ? '' : 'disabled') + '><i class="fa fa-plus"></i> 新增桥梁</button>',
      '<button class="ra-tb-btn"                 id="ra-b-edit"  ' + (oneSelected && isBridgesTab ? '' : 'disabled') + '><i class="fa fa-pencil"></i> 编辑</button>',
      '<button class="ra-tb-btn ra-tb-btn-danger" id="ra-b-del"  ' + (anySelected && isBridgesTab ? '' : 'disabled') + '><i class="fa fa-trash"></i> 删除' + selLabel + '</button>',
      '<button class="ra-tb-btn"                 id="ra-b-photo" ' + (oneSelected && isBridgesTab ? '' : 'disabled') + '><i class="fa fa-camera"></i> 照片管理</button>',
      '<button class="ra-tb-btn"                 id="ra-b-stats" ' + (isBridgesTab ? '' : 'disabled') + '><i class="fa fa-bar-chart"></i> 统计</button>',
      '<button class="ra-tb-btn"                 id="ra-b-export"><i class="fa fa-download"></i> ' + (anySelected ? '导出选中' : '导出Excel') + selLabel + '</button>',
      '<button class="ra-tb-btn"                 id="ra-b-map"  ' + (isBridgesTab ? '' : 'disabled') + '><i class="fa fa-map-marker"></i> 地图查看</button>',
    ].join('');
    tb.querySelector('#ra-b-new').onclick = openNewBridge;
    tb.querySelector('#ra-b-edit').onclick = () => {
      const id = [...state.selected][0];
      if (id) openEditBridge(id);
    };
    tb.querySelector('#ra-b-del').onclick = deleteBridges;
    tb.querySelector('#ra-b-photo').onclick = () => {
      const id = [...state.selected][0];
      if (id) openPhotoModal(id);
    };
    tb.querySelector('#ra-b-stats').onclick = openStatsModal;
    tb.querySelector('#ra-b-export').onclick = exportCsv;
    tb.querySelector('#ra-b-map').onclick = openMapModal;
  }

  // =========================================================================
  // Render: column-header filter row
  // =========================================================================
  function renderFilterRow() {
    const host = document.getElementById('ra-filter-row');
    if (state.tab !== 'bridges') {
      host.innerHTML = '';
      return;
    }
    if (!state.meta) {
      // meta not yet loaded — show placeholders
      host.innerHTML = COLUMNS.map(c =>
        `<div class="ra-filter-cell"><label>${escHtml(c.label)}</label><input disabled placeholder="筛选..." /></div>`
      ).join('') + '<a class="ra-filter-clear" id="ra-clear">清空筛选</a>';
      document.getElementById('ra-clear').onclick = clearFilters;
      return;
    }
    host.innerHTML = COLUMNS.map(c => {
      const v = state.filters[c.key] || '';
      let inputHtml;
      if (c.kind === 'enum' && state.meta) {
        const optKey = c.key === 'eval_level' ? 'eval_levels' : c.key === 'span_category' ? 'span_categories' : c.key === 'route_id' ? 'route_ids' : c.key === 'bridge_type' ? 'bridge_types' : null;
        const opts = (optKey && state.meta[optKey]) || [];
        inputHtml = `<select data-col="${c.key}"><option value="">全部</option>${opts.map(o => `<option value="${escHtml(o)}"${v === o ? ' selected' : ''}>${escHtml(o)}</option>`).join('')}</select>`;
      } else {
        inputHtml = `<input data-col="${c.key}" value="${escHtml(v)}" placeholder="筛选..." />`;
      }
      return `<div class="ra-filter-cell"><label>${escHtml(c.label)}</label>${inputHtml}</div>`;
    }).join('') + '<a class="ra-filter-clear" id="ra-clear">清空筛选</a>';

    host.querySelectorAll('[data-col]').forEach(el => {
      let t = null;
      const handler = (e) => {
        const col = el.getAttribute('data-col');
        const val = e.target.value.trim();
        clearTimeout(t);
        t = setTimeout(() => {
          if (val) state.filters[col] = val; else delete state.filters[col];
          state.page = 1;
          loadList();
        }, 250);
      };
      el.addEventListener('input', handler);
      el.addEventListener('change', handler);
    });
    document.getElementById('ra-clear').onclick = clearFilters;
  }
  function clearFilters() {
    state.filters = {};
    state.q = '';
    const s = document.getElementById('ra-search');
    if (s) s.value = '';
    state.page = 1;
    renderFilterRow();
    loadList();
  }

  // =========================================================================
  // Render: table
  // =========================================================================
  function renderTableHead() {
    const parts = state.ordering.split(',').map(s => {
      const desc = s.startsWith('-');
      return { field: desc ? s.slice(1) : s, desc };
    });
    document.getElementById('ra-thead').innerHTML = '<tr>' +
      '<th style="width:36px"><input type="checkbox" id="ra-check-all" /></th>' +
      COLUMNS.map(c => {
        const sortEntry = parts.find(p => p.field === c.key);
        const klass = sortEntry ? (sortEntry.desc ? 'sorted-desc' : 'sorted-asc') : '';
        const arrow = sortEntry ? (sortEntry.desc ? '↓' : '↑') : '↕';
        return `<th class="ra-sortable ${klass}" data-sort-key="${c.key}" style="min-width:${c.width}px">${escHtml(c.label)}<span class="ra-sort-arrow">${arrow}</span></th>`;
      }).join('') +
      '</tr>';
    const cb = document.getElementById('ra-check-all');
    cb.checked = state.rows.length > 0 && state.rows.every(r => state.selected.has(r.id));
    cb.indeterminate = !cb.checked && state.rows.some(r => state.selected.has(r.id));
    cb.onchange = function () {
      if (cb.checked) state.rows.forEach(r => state.selected.add(r.id));
      else state.rows.forEach(r => state.selected.delete(r.id));
      renderTableBody();
      renderToolbar();
    };
    // Click to sort
    document.querySelectorAll('.ra-sortable').forEach(th => {
      th.onclick = () => {
        const key = th.getAttribute('data-sort-key');
        const cur = state.ordering.split(',').map(s => s.startsWith('-') ? s.slice(1) : s);
        if (cur[0] === key) {
          // Toggle direction
          if (state.ordering.startsWith('-')) state.ordering = key;
          else state.ordering = '-' + key;
        } else {
          state.ordering = key;  // ASC by default
        }
        state.page = 1;
        loadList();
      };
    });
  }
  function renderTableBody() {
    if (state.tab !== 'bridges') {
      showEmpty('请选择上方的「桥梁基本信息」标签查看数据。');
      return;
    }
    hideEmpty();
    if (!state.rows.length) {
      showEmpty('暂无数据。调整筛选条件后重试，或点击「新增桥梁」录入。');
      return;
    }
    document.getElementById('ra-tbody').innerHTML = state.rows.map(r => {
      const cells = COLUMNS.map(c => {
        if (c.kind === 'rating') {
          return `<td><span class="${ratingClass(r[c.key])}">${r[c.key] ? escHtml(String(r[c.key]).replace(/[^一二三四五类桥0-9]/g, '').slice(0,2) || '?') : '?'}</span></td>`;
        }
        if (c.kind === 'photo') {
          const url = r.general_photo_url;
          if (url) {
            return `<td><img class="ra-thumb" data-act="photo-preview" data-url="${escHtml(url)}" data-name="${escHtml(r.bridge_name)}" src="${escHtml(url)}" loading="lazy" onerror="this.outerHTML='<span class=\\'ra-thumb-empty\\'>无图</span>'" /></td>`;
          }
          return '<td><span class="ra-thumb-empty">—</span></td>';
        }
        if (c.link) {
          return `<td><a class="ra-link" data-act="detail" data-id="${r.id}" href="javascript:;">${escHtml(r[c.key]) || '—'}</a></td>`;
        }
        return `<td title="${escHtml(r[c.key])}">${escHtml(r[c.key]) || '—'}</td>`;
      }).join('');
      const sel = state.selected.has(r.id) ? ' selected' : '';
      return `<tr class="${sel}" data-id="${r.id}">
        <td><input type="checkbox" data-act="select" data-id="${r.id}" ${sel ? 'checked' : ''} /></td>
        ${cells}
      </tr>`;
    }).join('');
    // Wire events
    document.getElementById('ra-tbody').querySelectorAll('input[data-act=select]').forEach(cb => {
      cb.onchange = (e) => {
        const id = cb.getAttribute('data-id');
        if (cb.checked) state.selected.add(id);
        else state.selected.delete(id);
        const tr = cb.closest('tr');
        tr.classList.toggle('selected', cb.checked);
        renderTableHead();
        renderToolbar();
      };
    });
    document.getElementById('ra-tbody').querySelectorAll('a[data-act=detail]').forEach(a => {
      a.onclick = () => openDetail(a.getAttribute('data-id'));
    });
    // Photo preview
    document.getElementById('ra-tbody').querySelectorAll('img[data-act=photo-preview]').forEach(img => {
      img.onclick = (e) => {
        e.stopPropagation();
        openPhotoPreview(img.getAttribute('data-url'), img.getAttribute('data-name'));
      };
    });
    document.getElementById('ra-tbody').querySelectorAll('tr').forEach(tr => {
      tr.onclick = (e) => {
        if (e.target.closest('input,a,img')) return;
        const id = tr.getAttribute('data-id');
        const cb = tr.querySelector('input[data-act=select]');
        if (state.selected.has(id)) { state.selected.delete(id); cb.checked = false; }
        else { state.selected.add(id); cb.checked = true; }
        tr.classList.toggle('selected', cb.checked);
        renderTableHead();
        renderToolbar();
      };
    });
  }

  // =========================================================================
  // Render: footer / pagination
  // =========================================================================
  function renderFooter() {
    if (state.tab !== 'bridges') {
      document.getElementById('ra-footer').innerHTML = '';
      return;
    }
    const total = state.total;
    const from = total === 0 ? 0 : (state.page - 1) * state.pageSize + 1;
    const to = Math.min(state.page * state.pageSize, total);
    const tp = state.totalPages;
    const cur = state.page;
    // Build page buttons
    const pages = [];
    const push = (p, label, active, disabled) => pages.push(
      `<button class="ra-page-btn${active ? ' active' : ''}" data-page="${p}"${disabled ? ' disabled' : ''}>${label}</button>`
    );
    push(1, '«', cur === 1, cur === 1);
    push(Math.max(1, cur - 1), '‹', false, cur === 1);
    // Show up to 5 page numbers around current
    const window = 2;
    const start = Math.max(1, cur - window);
    const end = Math.min(tp, cur + window);
    if (start > 1) push(1, '1', false, false);
    if (start > 2) push(0, '…', false, true);
    for (let p = start; p <= end; p++) push(p, String(p), p === cur, false);
    if (end < tp - 1) push(0, '…', false, true);
    if (end < tp) push(tp, String(tp), false, false);
    push(Math.min(tp, cur + 1), '›', false, cur === tp);
    push(tp, '»', false, cur === tp);

    document.getElementById('ra-footer').innerHTML = [
      '<div class="ra-pager">' + pages.join('') + '</div>',
      '<div>',
      '  <span class="ra-total">每页</span>',
      '  <select class="ra-page-size" id="ra-page-size">',
            [10, 20, 50, 100].map(n => `<option value="${n}"${n === state.pageSize ? ' selected' : ''}>${n}</option>`).join(''),
      '  </select>',
      '  <span class="ra-total">条</span>',
      '</div>',
      '<div class="ra-total">共 ' + total + ' 项 / 第 ' + from + '–' + to + ' 条</div>',
    ].join('');

    document.getElementById('ra-footer').querySelectorAll('button[data-page]').forEach(b => {
      b.onclick = () => {
        const p = parseInt(b.getAttribute('data-page'), 10);
        if (p >= 1 && p <= tp && p !== cur) {
          state.page = p;
          loadList();
        }
      };
    });
    document.getElementById('ra-page-size').onchange = (e) => {
      state.pageSize = parseInt(e.target.value, 10);
      state.page = 1;
      loadList();
    };
  }

  // =========================================================================
  // Data loading
  // =========================================================================
  function loadMeta() {
    if (state.meta) return Promise.resolve(state.meta);
    return api('/meta/').then(m => { state.meta = m; return m; });
  }
  function loadStats(force) {
    if (state.stats && !force) return Promise.resolve(state.stats);
    return api('/bridges/stats/').then(s => { state.stats = s; return s; });
  }

  function renderSummaryStrip() {
    const host = document.getElementById('ra-summary');
    if (state.tab !== 'bridges') { host.innerHTML = ''; return; }
    const s = state.stats || {};
    const total = s.total != null ? s.total : '…';
    const len = s.total_length_m != null ? Math.round(s.total_length_m).toLocaleString() + ' m' : '…';
    const avg = s.avg_length_m != null ? Math.round(s.avg_length_m) + ' m' : '…';
    const one = (s.by_eval_level || []).find(x => String(x.k).includes('一类'));
    const all = (s.by_span_category || []).reduce((sum, x) => sum + (x.c || 0), 0);
    host.innerHTML = [
      '<div class="ra-summary-card alt0"><div class="ra-summary-icon"><i class="fa fa-bridge"></i></div><div class="ra-summary-text"><div class="ra-summary-num">' + total + '</div><div class="ra-summary-lbl">桥梁总数</div></div></div>',
      '<div class="ra-summary-card alt1"><div class="ra-summary-icon"><i class="fa fa-check-circle"></i></div><div class="ra-summary-text"><div class="ra-summary-num">' + (one ? one.c : '…') + '</div><div class="ra-summary-lbl">一类桥</div></div></div>',
      '<div class="ra-summary-card alt2"><div class="ra-summary-icon"><i class="fa fa-road"></i></div><div class="ra-summary-text"><div class="ra-summary-num">' + len + '</div><div class="ra-summary-lbl">总桥长</div></div></div>',
      '<div class="ra-summary-card alt3"><div class="ra-summary-icon"><i class="fa fa-arrows-h"></i></div><div class="ra-summary-text"><div class="ra-summary-num">' + avg + '</div><div class="ra-summary-lbl">平均桥长</div></div></div>',
      '<div class="ra-summary-card alt4"><div class="ra-summary-icon"><i class="fa fa-list"></i></div><div class="ra-summary-text"><div class="ra-summary-num">' + all + '</div><div class="ra-summary-lbl">含子表数据</div></div></div>',
    ].join('');
  }

  function openStatsModal() {
    showLoading();
    loadStats(true).then(s => {
      hideLoading();
      // Pick top items per section
      function barRows(items, limit) {
        const arr = (items || []).slice(0, limit || 20);
        const max = arr.length ? Math.max.apply(null, arr.map(x => x.c || 0)) : 1;
        return arr.map(x => {
          const pct = max > 0 ? ((x.c / max) * 100).toFixed(1) : 0;
          return '<div class="ra-bar-row">' +
            '<div class="ra-bar-lbl" title="' + escHtml(String(x.k)) + '">' + escHtml(String(x.k)) + '</div>' +
            '<div class="ra-bar-track"><div class="ra-bar-fill" style="width:' + pct + '%"></div></div>' +
            '<div class="ra-bar-val">' + x.c + '</div>' +
            '</div>';
        }).join('') || '<div style="color:#909399;padding:20px;text-align:center">暂无数据</div>';
      }
      const body = '<div class="ra-stats-grid">' +
        '<div class="ra-stats-section"><h4>按评定等级</h4><div class="ra-bar-list">' + barRows(s.by_eval_level) + '</div></div>' +
        '<div class="ra-stats-section"><h4>按跨径分类</h4><div class="ra-bar-list">' + barRows(s.by_span_category) + '</div></div>' +
        '<div class="ra-stats-section"><h4>按线路编号 (Top 20)</h4><div class="ra-bar-list">' + barRows(s.by_route_id) + '</div></div>' +
        '<div class="ra-stats-section"><h4>按桥梁类型 (Top 20)</h4><div class="ra-bar-list">' + barRows(s.by_bridge_type) + '</div></div>' +
        '</div>' +
        (s.by_built_date && s.by_built_date.length ?
          '<div class="ra-stats-section" style="margin:0 16px 16px"><h4>按建成年份 (Top 20)</h4><div class="ra-bar-list">' + barRows(s.by_built_date) + '</div></div>'
          : '');
      const foot = footHtml([{ id: 'ra-foot-close', label: '关闭', primary: true }]);
      const close = openModal('统计概览（' + (s.total || 0) + ' 座桥）', body, { footHtml: foot });
      document.getElementById('ra-foot-close').onclick = close;
    }).catch(e => { hideLoading(); toast('加载失败: ' + e.message, 'err'); });
  }
  function loadList() {
    if (state.tab !== 'bridges') {
      loadPlaceholder();
      return;
    }
    showLoading();
    const params = new URLSearchParams();
    params.set('page', state.page);
    params.set('page_size', state.pageSize);
    params.set('ordering', state.ordering);
    Object.entries(state.filters).forEach(([k, v]) => { if (v) params.set(k, v); });
    if (state.q) params.set('q', state.q);
    Promise.all([
      api('/bridges/?' + params.toString()),
      loadStats(false),   // refresh summary strip too
    ]).then(([j, _]) => {
      hideLoading();
      state.rows = j.results || [];
      state.total = j.count || 0;
      state.totalPages = j.total_pages || 1;
      // Drop selected ids that are no longer in the current page
      const pageIds = new Set(state.rows.map(r => r.id));
      [...state.selected].forEach(id => { if (!pageIds.has(id)) state.selected.delete(id); });
      renderTableHead();
      renderTableBody();
      renderSummaryStrip();
      renderFooter();
      renderToolbar();
    }).catch(e => { hideLoading(); toast('加载失败: ' + e.message, 'err'); });
  }
  function loadPlaceholder() {
    showLoading();
    api('/placeholders/' + state.tab + '/').then(j => {
      hideLoading();
      state.placeholder = j;
      state.rows = [];
      state.total = 0;
      renderTableHead();
      showEmpty('「' + (j.label || state.tab) + '」数据未建表。');
      renderFooter();
      renderToolbar();
    }).catch(e => { hideLoading(); toast('加载失败: ' + e.message, 'err'); });
  }
  function loadDetail(id) {
    showLoading();
    return api('/bridges/' + id + '/').then(j => {
      hideLoading();
      state.detailData = j;
      return j;
    });
  }

  // =========================================================================
  // Modal helpers
  // =========================================================================
  function openModal(title, bodyHtml, opts) {
    opts = opts || {};
    const host = document.getElementById('ra-modal');
    host.innerHTML = '<div class="ra-modal" id="ra-modal-inner">' +
      '<div class="ra-modal-head"><span class="ra-modal-title">' + escHtml(title) + '</span>' +
      '<span class="ra-modal-close" id="ra-modal-close">×</span></div>' +
      '<div class="ra-modal-body" id="ra-modal-body">' + bodyHtml + '</div>' +
      '<div class="ra-modal-foot" id="ra-modal-foot">' + (opts.footHtml || '') + '</div>' +
      '</div>';
    host.style.display = 'flex';
    const close = () => { host.style.display = 'none'; };
    document.getElementById('ra-modal-close').onclick = close;
    host.onclick = (e) => { if (e.target === host) close(); };
    if (opts.onMount) opts.onMount(close);
    return close;
  }
  function closeModal() {
    document.getElementById('ra-modal').style.display = 'none';
  }
  function footHtml(buttons) {
    return '<div class="left"></div>' + buttons.map(b => `<button class="ra-tb-btn${b.primary ? ' ra-tb-btn-primary' : ''}${b.danger ? ' ra-tb-btn-danger' : ''}" id="${b.id}">${b.label}</button>`).join('');
  }

  // =========================================================================
  // Detail modal
  // =========================================================================
  function openDetail(id) {
    showLoading();
    Promise.all([
      api('/bridges/' + id + '/'),
      api('/bridges/' + id + '/evaluations/').catch(() => ({ rows: [] })),
    ]).then(([bridge, evals]) => {
      hideLoading();
      const subData = { evaluations: evals };
      const subLoaders = {};
      SUBTABLES.forEach(st => {
        subLoaders[st.kind] = () => api('/bridges/' + id + '/' + st.kind + '/').then(j => subData[st.kind] = j).catch(e => subData[st.kind] = { rows: [], error: e.message });
      });
      // Lazy load subtables as user clicks tabs
      const labels = {};
      COLUMNS.concat(SUBTABLES.map(s => ({ key: s.kind, label: s.label }))).forEach(c => labels[c.key] = c.label);
      // Add a "基本信息" tab + each subtable tab
      const tabs = [{ kind: '_basic', label: '基本信息' }].concat(SUBTABLES);

      function renderTab(kind) {
        const body = document.getElementById('ra-modal-body');
        if (kind === '_basic') {
          body.innerHTML = renderBasicInfo(bridge);
        } else {
          body.innerHTML = '<div style="color:#909399">加载中...</div>';
          if (subData[kind]) {
            body.innerHTML = renderSubtable(subData[kind]);
          } else {
            subLoaders[kind]().then(() => {
              if (document.getElementById('ra-modal').style.display === 'flex') {
                body.innerHTML = renderSubtable(subData[kind]);
              }
            });
          }
        }
      }

      const head = '<div class="ra-detail-tabs" id="ra-detail-tabs">' +
        tabs.map((t, i) => `<span class="ra-detail-tab${i === 0 ? ' active' : ''}" data-kind="${t.kind}">${escHtml(t.label)}</span>`).join('') +
        '</div><div id="ra-detail-body"></div>';

      const foot = footHtml([
        { id: 'ra-foot-edit', label: '编辑' },
        { id: 'ra-foot-close', label: '关闭', primary: true },
      ]);
      const close = openModal('桥梁详情：' + (bridge.bridge_name || id), head, { footHtml: foot });
      // Replace the body placeholder with a real body container
      document.getElementById('ra-modal-body').innerHTML = '<div id="ra-detail-body"></div>';
      // Inline foot mount: render the body inside ra-detail-body
      function showTab(kind) {
        document.querySelectorAll('#ra-detail-tabs .ra-detail-tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-kind') === kind));
        const target = document.getElementById('ra-detail-body');
        if (kind === '_basic') target.innerHTML = renderBasicInfo(bridge);
        else {
          target.innerHTML = '<div style="color:#909399;padding:20px">加载中...</div>';
          const p = subData[kind] ? Promise.resolve() : subLoaders[kind]();
          p.then(() => { target.innerHTML = renderSubtable(subData[kind]); });
        }
      }
      document.querySelectorAll('#ra-detail-tabs .ra-detail-tab').forEach(t => {
        t.onclick = () => showTab(t.getAttribute('data-kind'));
      });
      document.getElementById('ra-foot-edit').onclick = () => { close(); openEditBridge(id); };
      document.getElementById('ra-foot-close').onclick = close;
      showTab('_basic');
    }).catch(e => { hideLoading(); toast('加载详情失败: ' + e.message, 'err'); });
  }

  function renderBasicInfo(b) {
    // Hero with the two photo slots at the top.
    const photoHero = '<div class="ra-detail-hero">' +
      photoSlotForHero('正面照', b.general_photo_url) +
      photoSlotForHero('立面照', b.front_photo_url) +
      '</div>';
    function photoSlotForHero(label, url) {
      if (url) {
        return '<div class="ra-photo-slot"><span class="ph-label">' + escHtml(label) + '</span>' +
          '<img data-act="hero-photo" data-url="' + escHtml(url) + '" src="' + escHtml(url) + '" /></div>';
      }
      return '<div class="ra-photo-slot"><span class="ph-label">' + escHtml(label) + '</span>' +
        '<div class="ph-empty">未上传</div></div>';
    }
    // Skip empty columns; show everything in a 2-column grid grouped logically.
    const skipIfEmpty = c => c.trim().length > 0;
    // Group definition: list of (group label, [fields])
    const groups = [
      ['基本信息', [
        ['bridge_id_code', '桥梁编号'], ['bridge_name', '桥梁名称'], ['report_code', '报告编码'],
        ['admin_code', '行政区编码'], ['location', '所在地'], ['township', '乡镇'],
      ]],
      ['线路信息', [
        ['route_id', '线路编号'], ['route_name', '线路名称'], ['route_level', '技术等级'],
        ['secondary_route', '并行路线'], ['ramp_route_id', '匝道路线编号'],
        ['ramp_stake_value', '匝道桩号'], ['start_stake_no', '起点桩号'], ['end_stake_no', '终点桩号'],
        ['stake_no', '中心桩号'], ['design_stake_no', '设计桩号'], ['construction_stake', '施工桩号'],
      ]],
      ['结构尺寸', [
        ['length_m', '桥长(m)'], ['total_width_m', '总宽(m)'], ['deck_net_width', '桥面净宽(m)'],
        ['lane_width_m', '行车道宽(m)'], ['sidewalk_width_m', '人行道宽(m)'], ['lane_count', '车道数'],
        ['bridge_width_count', '桥面宽度组成'], ['bridge_height', '桥高(m)'], ['max_span_m', '最大跨径(m)'],
        ['total_span_m', '总跨径(m)'], ['span_count', '跨数'], ['span_category', '跨径分类'],
        ['bridge_type', '桥梁类型'], ['bridge_slope', '桥面纵坡(%)'], ['curve_radius', '平曲线半径(m)'],
        ['subgrade_form', '路基形式'], ['driving_direction', '行车方向'],
      ]],
      ['设计参数', [
        ['design_load', '设计荷载'], ['pass_load', '验算荷载'], ['seismic_level', '抗震烈度'],
        ['peak_acceleration', '峰值加速度'], ['design_life_period', '设计使用年限(年)'],
        ['service_life', '已使用年限(年)'], ['built_date', '建成年月'],
      ]],
      ['通航/净空', [
        ['nav_clearance', '通航等级'], ['bridge_height_limit', '桥高限制(m)'],
        ['std_deck_clearance_m', '桥面标准净空(m)'], ['actual_deck_clearance_m', '桥面实际净空(m)'],
        ['std_under_clearance_m', '桥下标准净空(m)'], ['actual_under_clearance_m', '桥下实际净空(m)'],
        ['over_clearance_m', '上部净空(m)'],
      ]],
      ['水文/交安', [
        ['design_flood_level', '设计洪水位'], ['history_flood_level', '历史最高水位'],
        ['design_flood_freq', '设计洪水频率'], ['normal_water_level', '常水位'],
        ['design_water_level', '设计水位'],
        ['expansion_joint_type', '伸缩缝类型'], ['bearing_type', '支座类型'],
        ['deck_pavement', '桥面铺装'], ['railing_material', '护栏材料'],
        ['median_guardrail_level', '中央护栏等级'], ['side_guardrail_level', '路侧护栏等级'],
        ['anti_collision', '防撞设施'], ['anti_ship_collision', '防船撞'],
        ['has_health_monitor', '健康监测'], ['is_attached_pipeline', '附挂管线'],
        ['is_long_large_bridge', '是否长大桥'], ['is_wide_road_narrow_bridge', '宽路窄桥'],
      ]],
      ['建设/管养', [
        ['design_unit', '设计单位'], ['constructor_unit', '施工单位'], ['supervisor_unit', '监理单位'],
        ['design_leader', '设计负责人'], ['constructor_leader', '施工负责人'], ['supervisor_leader', '监理负责人'],
        ['maintenance_unit', '管养单位'], ['maintainer_unit', '养护单位'],
        ['maintenance_start_stake', '管养起点桩号'], ['maintenance_end_stake', '管养终点桩号'],
        ['maintenance_length_m', '管养长度(m)'], ['maintenance_unit_nature', '管养单位性质'],
        ['is_co_maintained', '是否共养'], ['bridge_status', '桥梁状态'],
        ['maintenance_check_level', '经常检查等级'], ['eval_date', '最近评定日期'],
        ['reconstruct_part', '改建部位'], ['is_widened_bridge', '是否加宽'],
        ['is_in_annual_report', '是否纳入年报'],
      ]],
      ['评定与位置', [
        ['eval_level', '评定等级'], ['bridge_engineer', '桥梁工程师'],
        ['longitude', '经度'], ['latitude', '纬度'],
        ['general_photo_url', '正面照 URL'], ['front_photo_url', '立面照 URL'],
      ]],
    ];
    const html = groups.map(([label, fields]) => {
      const rows = fields.filter(([k]) => skipIfEmpty(b[k] || ''));
      if (!rows.length) return '';
      return `<div style="margin-bottom:14px">
        <div style="font-size:13px;font-weight:600;color:#303133;margin-bottom:6px;border-left:3px solid #409eff;padding-left:8px">${escHtml(label)}</div>
        <div class="ra-detail-section">${rows.map(([k, lbl]) =>
          `<div class="ra-field"><div class="ra-field-label">${escHtml(lbl)}</div><div class="ra-field-value">${escHtml(b[k]) || '—'}</div></div>`
        ).join('')}</div>
      </div>`;
    }).join('');
    return photoHero + html + (b.remarks ? `<div style="margin-top:8px"><div class="ra-field"><div class="ra-field-label">备注</div><div class="ra-field-value">${escHtml(b.remarks)}</div></div></div>` : '');
  }

  function renderSubtable(data) {
    if (data.error) return `<div style="color:#f56c6c;padding:20px">加载失败: ${escHtml(data.error)}</div>`;
    if (!data.rows || !data.rows.length) {
      return `<div style="color:#909399;padding:30px;text-align:center">「${escHtml(data.label)}」下无数据</div>`;
    }
    const keys = Object.keys(data.rows[0]).filter(k => k !== 'id' && k !== 'bridge_card_id');
    let h = '<div style="margin-bottom:8px;font-size:13px;font-weight:600">' + escHtml(data.label) + '（' + data.count + ' 条）</div>';
    h += '<table class="ra-subtable"><thead><tr>';
    for (const k of keys) h += '<th>' + escHtml(k) + '</th>';
    h += '</tr></thead><tbody>';
    for (const row of data.rows) {
      h += '<tr>';
      for (const k of keys) h += '<td>' + escHtml(row[k]) + '</td>';
      h += '</tr>';
    }
    h += '</tbody></table>';
    return h;
  }

  // =========================================================================
  // Edit / New form
  // =========================================================================
  function openEditBridge(id) {
    showLoading();
    api('/bridges/' + id + '/').then(b => {
      hideLoading();
      openBridgeForm('编辑桥梁：' + (b.bridge_name || id), b);
    }).catch(e => { hideLoading(); toast('加载失败: ' + e.message, 'err'); });
  }
  function openNewBridge() {
    openBridgeForm('新增桥梁', {});
  }
  function openBridgeForm(title, bridge) {
    bridge = bridge || {};
    const fields = [
      ['bridge_id_code', '桥梁编号 *'], ['bridge_name', '桥梁名称 *'],
      ['route_id', '线路编号'], ['route_name', '线路名称'], ['route_level', '技术等级'],
      ['admin_code', '行政区编码'], ['location', '所在地'], ['township', '乡镇'],
      ['stake_no', '中心桩号'], ['start_stake_no', '起点桩号'], ['end_stake_no', '终点桩号'],
      ['design_stake_no', '设计桩号'], ['construction_stake', '施工桩号'],
      ['length_m', '桥长(m)'], ['max_span_m', '最大跨径(m)'], ['total_span_m', '总跨径(m)'],
      ['span_count', '跨数'], ['span_category', '跨径分类（中桥/小桥/大桥/特大桥）'],
      ['bridge_type', '桥梁类型'], ['lane_count', '车道数'],
      ['total_width_m', '总宽(m)'], ['deck_net_width', '桥面净宽(m)'],
      ['bridge_height', '桥高(m)'], ['bridge_slope', '桥面纵坡(%)'],
      ['design_load', '设计荷载'], ['seismic_level', '抗震烈度'],
      ['built_date', '建成年月'], ['eval_level', '评定等级（一类桥/二类桥）'],
      ['longitude', '经度'], ['latitude', '纬度'],
      ['bridge_status', '桥梁状态'], ['bridge_engineer', '桥梁工程师'],
    ];
    const formHtml = '<div class="ra-form-row" style="display:block"><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 16px">' +
      fields.map(([k, lbl]) =>
        `<div class="ra-form-row" style="margin:0"><label style="min-width:90px">${escHtml(lbl)}</label><input id="f-${k}" value="${escHtml(bridge[k])}" /></div>`
      ).join('') + '</div></div>';

    const foot = footHtml([
      { id: 'ra-foot-cancel', label: '取消' },
      { id: 'ra-foot-save',   label: '保存', primary: true },
    ]);
    const close = openModal(title, formHtml, { footHtml: foot });
    document.getElementById('ra-foot-cancel').onclick = close;
    document.getElementById('ra-foot-save').onclick = () => {
      const payload = {};
      for (const [k] of fields) {
        const el = document.getElementById('f-' + k);
        if (el && el.value !== '') payload[k] = el.value;
      }
      if (!payload.bridge_name) { toast('桥梁名称必填', 'err'); return; }
      if (!payload.bridge_id_code) { toast('桥梁编号必填', 'err'); return; }
      showLoading();
      const req = bridge.id
        ? api('/bridges/' + bridge.id + '/', { method: 'PATCH', body: payload })
        : api('/bridges/', { method: 'POST', body: payload });
      req.then(() => {
        hideLoading();
        toast('✓ 已保存');
        close();
        loadList();
      }).catch(e => { hideLoading(); toast('保存失败: ' + e.message, 'err'); });
    };
  }

  // =========================================================================
  // Delete
  // =========================================================================
  function deleteBridges() {
    if (!state.selected.size) return;
    const ids = [...state.selected];
    if (!confirm('确定删除 ' + ids.length + ' 条桥梁记录？\n\n关联的桥墩/支座/评定/病害等子表记录会一并删除（CASCADE）。')) return;
    showLoading();
    Promise.all(ids.map(id => api('/bridges/' + id + '/', { method: 'DELETE' }).catch(e => e)))
      .then(results => {
        hideLoading();
        const ok = results.filter(r => !(r instanceof Error)).length;
        const fail = results.length - ok;
        toast(ok + ' 条已删除' + (fail ? '，' + fail + ' 条失败' : ''), fail ? 'warn' : 'ok');
        state.selected.clear();
        loadList();
      });
  }

  // =========================================================================
  // Photo management
  // =========================================================================
  function openPhotoModal(id) {
    window.__ra_current_photo_id = id;
    showLoading();
    api('/bridges/' + id + '/').then(b => {
      hideLoading();
      const body = '<div class="ra-photo-grid">' +
        photoSlot(id, 'general', '正面照', b.general_photo_url) +
        photoSlot(id, 'front',   '立面照', b.front_photo_url) +
        '</div>' +
        '<div style="margin-top:12px;color:#909399;font-size:12px">支持 JPG / PNG，单张 10MB 以内。' +
        '上传后立即生效，刷新列表或详情即可查看。</div>';
      const foot = footHtml([{ id: 'ra-foot-close', label: '关闭', primary: true }]);
      const close = openModal('照片管理：' + (b.bridge_name || id), body, { footHtml: foot });
      document.getElementById('ra-foot-close').onclick = close;
    }).catch(e => { hideLoading(); toast('加载失败: ' + e.message, 'err'); });
  }
  function photoSlot(id, kind, label, url) {
    return `<div class="ra-photo-slot">
      <div class="ph-label">${escHtml(label)}</div>
      ${url ? '<img src="' + escHtml(url) + '" />' : '<div style="color:#c0c4cc;padding:30px 0">未上传</div>'}
      <div class="ph-actions">
        <input type="file" accept="image/*" id="ra-photo-${kind}" style="display:none" />
        <button class="ra-tb-btn ra-tb-btn-sm" data-act="upload" data-kind="${kind}">${url ? '替换' : '上传'}</button>
        ${url ? '<button class="ra-tb-btn ra-tb-btn-sm ra-tb-btn-danger" data-act="delete" data-kind="' + kind + '">删除</button>' : ''}
      </div>
    </div>`;
  }
  // Wire photo upload + delete via event delegation once modal opens
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-act="upload"], [data-act="delete"]');
    if (!btn) return;
    const kind = btn.getAttribute('data-kind');
    const act = btn.getAttribute('data-act');
    const id = window.__ra_current_photo_id;
    if (!id) return;
    if (act === 'upload') {
      const input = document.getElementById('ra-photo-' + kind);
      if (input) input.click();
    } else if (act === 'delete') {
      if (!confirm('删除这张照片？')) return;
      showLoading();
      api('/bridges/' + id + '/photos/' + kind + '/', { method: 'DELETE' }).then(() => {
        hideLoading();
        toast('✓ 已删除');
        openPhotoModal(id);
      }).catch(err => { hideLoading(); toast('删除失败: ' + err.message, 'err'); });
    }
  });
  document.addEventListener('change', (e) => {
    if (e.target.id && e.target.id.startsWith('ra-photo-')) {
      const kind = e.target.id.replace('ra-photo-', '');
      const file = e.target.files[0];
      if (!file) return;
      // Find the bridge id from the modal context
      const id = window.__ra_current_photo_id;
      if (!id) { toast('内部错误：未找到当前桥梁', 'err'); return; }
      const fd = new FormData();
      fd.append('file', file);
      showLoading();
      api('/bridges/' + id + '/photos/?kind=' + kind, { method: 'POST', body: fd }).then(() => {
        hideLoading();
        toast('✓ 上传成功');
        openPhotoModal(id);
      }).catch(err => { hideLoading(); toast('上传失败: ' + err.message, 'err'); });
    }
  });

  // =========================================================================
  // Photo preview (lightbox-style)
  // =========================================================================
  function openPhotoPreview(url, name) {
    const body = '<div class="ra-photo-viewer"><img src="' + escHtml(url) + '" alt="' + escHtml(name) + '" />' +
      '<div class="ph-caption">' + escHtml(name) + '</div></div>';
    const foot = footHtml([{ id: 'ra-foot-close', label: '关闭', primary: true }]);
    const close = openModal('照片预览', body, { footHtml: foot });
    document.getElementById('ra-foot-close').onclick = close;
  }

  // Photo click delegation (list thumbs + detail hero)
  document.addEventListener('click', (e) => {
    const hero = e.target.closest('[data-act=hero-photo]');
    if (hero) {
      e.stopPropagation();
      const nameEl = document.querySelector('.ra-modal-title');
      openPhotoPreview(hero.getAttribute('data-url'), nameEl ? nameEl.textContent : '');
      return;
    }
  });

  // =========================================================================
  // Map view (with marker clustering at low zoom)
  // =========================================================================
  function openMapModal() {
    showLoading();
    const params = new URLSearchParams();
    Object.entries(state.filters).forEach(([k, v]) => { if (v) params.set(k, v); });
    if (state.q) params.set('q', state.q);
    params.set('page_size', '100');
    api('/bridges/?' + params.toString()).then(j => {
      hideLoading();
      const rows = (j.results || []).filter(r => r.longitude && r.latitude);
      if (!rows.length) { toast('当前筛选下没有带经纬度的桥梁', 'warn'); return; }
      const body = '<div id="ra-map" style="width:780px;height:540px;background:#0f1117"></div>' +
        '<div style="margin-top:8px;font-size:12px;color:#909399">共 ' + rows.length + ' 座桥（每页最多 100 座）。缩放看聚类，点 marker 查看详情。</div>';
      const foot = footHtml([{ id: 'ra-foot-close', label: '关闭', primary: true }]);
      const close = openModal('地图查看：' + rows.length + ' 座桥', body, { footHtml: foot });
      document.getElementById('ra-foot-close').onclick = close;
      // Load OL + render
      ensureOL().then(() => {
        const mapEl = document.getElementById('ra-map');
        if (!mapEl) return;
        const features = rows.map(r => {
          const lng = parseFloat(r.longitude), lat = parseFloat(r.latitude);
          if (isNaN(lng) || isNaN(lat)) return null;
          const f = new ol.Feature({ geometry: new ol.geom.Point(ol.proj.fromLonLat([lng, lat])) });
          f.set('name', r.bridge_name);
          f.set('id', r.id);
          f.set('count', 1);
          return f;
        }).filter(Boolean);
        const rawSource = new ol.source.Vector({ features });

        // Cluster source: points within ~40px are merged into a single
        // "cluster" feature whose attributes.features is the array of
        // contained points. We style clusters differently from singletons.
        const clusterSource = new ol.source.Cluster({
          distance: 40,
          minDistance: 20,
          source: rawSource,
        });
        const clusterLayer = new ol.layer.Vector({
          source: clusterSource,
          style: clusterStyle,
        });
        const map = new ol.Map({
          target: mapEl,
          layers: [
            new ol.layer.Tile({
              source: new ol.source.XYZ({
                url: 'https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}',
                attributions: '© 高德地图',
                crossOrigin: 'anonymous',
              }),
            }),
            clusterLayer,
          ],
          view: new ol.View({ center: ol.proj.fromLonLat([113.0, 23.4]), zoom: 9 }),
        });
        // Auto-fit to features extent
        if (features.length) {
          const ext = rawSource.getExtent();
          map.getView().fit(ext, { padding: [40, 40, 40, 40], maxZoom: 14, duration: 500 });
        }
        // Tooltip overlay for clusters / individual bridges
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:absolute;background:#fff;border:1px solid #ebeef5;padding:4px 8px;border-radius:3px;font-size:12px;display:none;pointer-events:none;box-shadow:0 2px 8px rgba(0,0,0,0.15);z-index:100';
        mapEl.style.position = 'relative';
        mapEl.appendChild(overlay);
        map.on('pointermove', (evt) => {
          const hit = map.hasFeatureAtPixel(evt.pixel);
          mapEl.style.cursor = hit ? 'pointer' : '';
        });
        map.on('singleclick', (evt) => {
          const f = map.forEachFeatureAtPixel(evt.pixel, ff => ff);
          if (!f) { overlay.style.display = 'none'; return; }
          const feats = f.get('features') || [f];
          if (feats.length > 1) {
            // Cluster: zoom in to expand it.
            const view = map.getView();
            const extent = new ol.extent.createEmpty();
            feats.forEach(ft => ol.extent.extend(extent, ft.getGeometry().getExtent()));
            view.fit(extent, { padding: [60, 60, 60, 60], maxZoom: view.getZoom() + 2, duration: 500 });
            return;
          }
          // Single bridge: show tooltip with name + link
          const ff = feats[0];
          const name = ff.get('name') || '';
          const coord = ff.getGeometry().getCoordinates();
          const [lng, lat] = ol.proj.toLonLat(coord);
          overlay.innerHTML = '<strong>' + escHtml(name) + '</strong><br>(' + lng.toFixed(4) + ', ' + lat.toFixed(4) + ')<br><a href="javascript:void(0)" data-bridge-id="' + escHtml(ff.get('id')) + '" style="color:#409eff">打开详情</a>';
          overlay.style.left = (evt.originalEvent.offsetX + 12) + 'px';
          overlay.style.top  = (evt.originalEvent.offsetY + 12) + 'px';
          overlay.style.display = 'block';
          const link = overlay.querySelector('a[data-bridge-id]');
          if (link) link.onclick = (ev) => { ev.stopPropagation(); close(); openDetail(ff.get('id')); };
        });
      }).catch(e => toast('OpenLayers 加载失败: ' + e.message, 'err'));
    }).catch(e => { hideLoading(); toast('加载失败: ' + e.message, 'err'); });
  }

  // Cluster / single-point style. Clusters get a sized circle with the count.
  function clusterStyle(feature) {
    const features = feature.get('features') || [];
    const count = features.length;
    if (count === 1) {
      // Individual bridge marker
      return new ol.style.Style({
        image: new ol.style.Circle({
          radius: 6, fill: new ol.style.Fill({ color: '#409eff' }),
          stroke: new ol.style.Stroke({ color: '#fff', width: 2 }),
        }),
      });
    }
    // Cluster: size by count
    const r = count < 10 ? 12 : count < 50 ? 16 : count < 200 ? 20 : 24;
    const color = count < 10 ? '#67c23a' : count < 50 ? '#e6a23c' : count < 200 ? '#f56c6c' : '#c45656';
    return new ol.style.Style({
      image: new ol.style.Circle({
        radius: r, fill: new ol.style.Fill({ color: color }),
        stroke: new ol.style.Stroke({ color: '#fff', width: 2 }),
      }),
      text: new ol.style.Text({
        text: String(count),
        font: 'bold 12px sans-serif',
        fill: new ol.style.Fill({ color: '#fff' }),
      }),
    });
  }
  function ensureOL() {
    if (typeof ol !== 'undefined' && ol.Map) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = '/static/app/js/vendor/potree/libs/openlayers3/ol.js';
      s.onload = () => resolve();
      s.onerror = () => reject(new Error('OL 加载失败'));
      document.head.appendChild(s);
    });
  }

  // =========================================================================
  // Export
  // =========================================================================
  function exportCsv() {
    const params = new URLSearchParams();
    Object.entries(state.filters).forEach(([k, v]) => { if (v) params.set(k, v); });
    if (state.q) params.set('q', state.q);
    if (state.selected.size) params.set('ids', [...state.selected].join(','));
    showLoading();
    fetch('/api/plugins/road-attributes/bridges/export/?' + params.toString(), {
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': getCookie('csrftoken') },
    }).then(r => r.blob()).then(blob => {
      hideLoading();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const suffix = state.selected.size ? '_selected_' + state.selected.size : '';
      a.download = 'bridges' + suffix + '_' + new Date().toISOString().slice(0, 10) + '.csv';
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast('✓ 已下载 CSV');
    }).catch(e => { hideLoading(); toast('导出失败: ' + e.message, 'err'); });
  }

  // =========================================================================
  // Tab switch + global search + refresh
  // =========================================================================
  function switchTab(tab) {
    state.tab = tab;
    state.selected.clear();
    state.page = 1;
    state.filters = {};
    state.q = '';
    const s = document.getElementById('ra-search');
    if (s) s.value = '';
    renderTabs();
    renderToolbar();
    renderFilterRow();
    loadList();
  }
  function bindUIEvents() {
    document.getElementById('ra-tabs').addEventListener('click', (e) => {
      const t = e.target.closest('.ra-tab');
      if (t) switchTab(t.getAttribute('data-tab'));
    });
    document.getElementById('ra-refresh').onclick = () => loadList();
    let searchTimer = null;
    document.getElementById('ra-search').addEventListener('input', (e) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.q = e.target.value.trim();
        state.page = 1;
        loadList();
      }, 300);
    });
  }

  // =========================================================================
  // Init
  // =========================================================================
  function injectCSS() {
    if (document.getElementById('ra-css')) return;
    const s = document.createElement('style');
    s.id = 'ra-css';
    s.textContent = APP_CSS;
    document.head.appendChild(s);
  }
  window.roadAttributesInit = function (opts) {
    const mountEl = opts && opts.mountEl;
    if (!mountEl) return;
    injectCSS();
    mountEl.innerHTML = APP_HTML;
    renderTabs();
    renderToolbar();
    renderFilterRow();
    bindUIEvents();
    loadMeta().then(() => {
      renderFilterRow();
      loadList();
    });
  };
})();
