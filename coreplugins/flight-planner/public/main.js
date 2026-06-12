/* Flight Planner plugin - vanilla JS implementation */
(function() {
  "use strict";

  var PLUGIN_BASE = "/plugins/flight-planner/";
  var API_BASE = "/api/plugins/flight-planner/";

  function realApi(path) { return API_BASE + path; }

  function $(id) { return document.getElementById(id); }
  function el(tag, props, children) {
    var e = document.createElement(tag);
    if (props) for (var k in props) e[k] = props[k];
    if (children) children.forEach(function (c) { if (c) e.appendChild(c); });
    return e;
  }

  // ----------------------------------------------------------------
  // APP_HTML — full UI template, injected when init(mountEl) is called
  // with a non-#fp-map mount point (i.e., from the React wrapper).
  // This is the sidebar + map area shell that WebODM's React wrapper
  // expects to find inside #flight-planner-app.
  // ----------------------------------------------------------------
  var APP_HTML = [
    '<div class="fp-sidebar">',
    '  <div class="fp-header">',
    '    <h2>✈ 航线规划</h2>',
    '    <div class="fp-header-actions">',
    '      <button id="fp-btn-new-project" class="fp-btn fp-btn-sm" title="新建项目">+ 新项目</button>',
    '    </div>',
    '  </div>',
    '  <div id="fp-project-info" class="fp-section fp-project-info"></div>',
    '  <div class="fp-section fp-project-list-section">',
    '    <details open>',
    '      <summary>项目库 <span id="fp-project-count" class="fp-count-badge">0</span></summary>',
    '      <div id="fp-project-list" class="fp-project-list">',
    '        <div class="fp-list-empty">加载中…</div>',
    '      </div>',
    '    </details>',
    '  </div>',
    '  <div class="fp-tabs">',
    '    <button data-mode="polygon" class="active">多边形</button>',
    '    <button data-mode="spiral">螺旋</button>',
    '    <button data-mode="orbit">环绕</button>',
    '    <button data-mode="cable">索道</button>',
    '    <button data-mode="corkscrew">螺旋上升</button>',
    '    <button data-mode="grid">面板网格</button>',
    '  </div>',
    '  <div class="fp-mode-panel active" data-panel="polygon">',
    '    <div class="fp-hint">📍 在地图上依次点击多边形顶点，双击结束。</div>',
    '    <label>旁向重叠 (0-1) <input type="number" id="fp-poly-overlap" value="0.7" min="0" max="0.95" step="0.05" /></label>',
    '    <label>前向重叠 (0-1) <input type="number" id="fp-poly-frontoverlap" value="0.8" min="0" max="0.95" step="0.05" title="沿飞行方向的照片重叠率。配合 multipleTiming 触发模式自动算 photo_interval" /></label>',
    '    <label>行间距 (m) <input type="number" id="fp-poly-spacing" value="20" min="0.5" max="500" step="0.5" /></label>',
    '    <label>航线角度 (°) <input type="number" id="fp-poly-angle" value="0" min="-90" max="180" step="1" /></label>',
    '    <label>多边形内缩 (m) <input type="number" id="fp-poly-margin" value="5" min="0" max="200" step="1" /></label>',
    '  </div>',
    '  <div class="fp-mode-panel" data-panel="spiral">',
    '    <div class="fp-hint">📍 点击中心点生成螺旋。</div>',
    '    <label>起始半径 (m) <input type="number" id="fp-cs-radius" value="30" min="1" max="500" /></label>',
    '    <label>圈数 <input type="number" id="fp-cs-turns" value="6" min="1" max="50" /></label>',
    '    <label>起始高度 (m) <input type="number" id="fp-cs-alt0" value="40" min="1" max="500" /></label>',
    '    <label>终止高度 (m) <input type="number" id="fp-cs-alt1" value="80" min="1" max="500" /></label>',
    '    <label>每圈采样点 <input type="number" id="fp-cs-ppt" value="24" min="4" max="120" /></label>',
    '  </div>',
    '  <div class="fp-mode-panel" data-panel="orbit">',
    '    <div class="fp-hint">📍 点击 POI（兴趣点）生成环绕轨迹。</div>',
    '    <label>环绕半径 (m) <input type="number" id="fp-orbit-radius" value="50" min="1" max="500" /></label>',
    '    <label>航点数 <input type="number" id="fp-orbit-samples" value="16" min="4" max="64" /></label>',
    '  </div>',
    '  <div class="fp-mode-panel" data-panel="cable">',
    '    <div class="fp-hint">📍 依次点击索道路径顶点。</div>',
    '    <label>采样 <input type="number" id="fp-cable-samples" value="10" min="2" max="100" /></label>',
    '    <label>重复次数 <input type="number" id="fp-cable-repeat" value="1" min="1" max="10" /></label>',
    '  </div>',
    '  <div class="fp-mode-panel" data-panel="corkscrew">',
    '    <div class="fp-hint">📍 点击中心点生成螺旋上升航线。</div>',
    '    <label>半径 (m) <input type="number" id="fp-cs2-radius" value="20" min="1" max="200" /></label>',
    '    <label>上升高度 (m) <input type="number" id="fp-cs2-alt" value="60" min="1" max="500" /></label>',
    '    <label>圈数 <input type="number" id="fp-cs2-turns" value="8" min="1" max="40" /></label>',
    '  </div>',
    '  <div class="fp-mode-panel" data-panel="grid">',
    '    <div class="fp-hint">📍 在地图上点击矩形对角点。</div>',
    '    <label>宽 (m) <input type="number" id="fp-grid-w" value="100" min="10" max="5000" /></label>',
    '    <label>高 (m) <input type="number" id="fp-grid-h" value="100" min="10" max="5000" /></label>',
    '    <label>间距 (m) <input type="number" id="fp-grid-spacing" value="20" min="1" max="500" /></label>',
    '    <label>角度 (°) <input type="number" id="fp-grid-angle" value="0" min="-90" max="90" /></label>',
    '    <label>旁向重叠 (0-1) <input type="number" id="fp-grid-overlap" value="0.7" min="0" max="0.95" step="0.05" /></label>',
    '    <label>前向重叠 (0-1) <input type="number" id="fp-grid-frontoverlap" value="0.8" min="0" max="0.95" step="0.05" title="沿飞行方向的照片重叠率" /></label>',
    '  </div>',
    '  <div class="fp-section fp-flight-params">',
    '    <details open>',
    '      <summary>📐 飞行参数（适用所有模式）</summary>',
    '      <div class="fp-wpml-grid">',
    '        <label>飞行高度 (m) <input type="number" id="fp-flight-alt" value="60" min="1" max="500" step="1" /></label>',
    '        <label>飞行速度 (m/s) <input type="number" id="fp-flight-speed" value="5" min="0.1" max="20" step="0.1" /></label>',
    '        <label>云台俯仰 (°) <input type="number" id="fp-flight-gimbal" value="-90" min="-90" max="30" step="1" /></label>',
    '        <label>朝向 (°) <input type="number" id="fp-flight-heading" value="" min="0" max="359" placeholder="自动" /></label>',
    '        <label>动作',
    '          <select id="fp-flight-action">',
    '            <option value="none">none</option>',
    '            <option value="photo" selected>photo</option>',
    '            <option value="video_start">video_start</option>',
    '            <option value="video_stop">video_stop</option>',
    '            <option value="hover">hover</option>',
    '          </select>',
    '        </label>',
    '      </div>',
    '      <p class="fp-hint">💡 改这些会同步应用到当前模式；已生成的航线不受影响（需重新生成）。</p>',
    '    </details>',
    '  </div>',
    '  <div class="fp-section">',
    '    <label>机型 <select id="fp-drone-model"><option value="">加载中…</option></select></label>',
    '    <div id="fp-model-detail" class="fp-model-detail"></div>',
    '  </div>',
    '  <div class="fp-section">',
    '    <details>',
    '      <summary>高级 / WPML 设置 (19 项)</summary>',
    '      <div class="fp-wpml-grid">',
    '        <label>飞行至航线 <select id="fp-wpml-flyto"><option value="safely">safely</option><option value="pointToPoint">pointToPoint</option></select></label>',
    '        <label>结束动作 <select id="fp-wpml-finish"><option value="goHome">goHome</option><option value="autoLand">autoLand</option><option value="hover">hover</option></select></label>',
    '        <label>RC 失联动作 <select id="fp-wpml-rclow"><option value="goHome">goHome</option><option value="hover">hover</option><option value="autoLand">autoLand</option></select></label>',
    '        <label>信号丢失 <select id="fp-wpml-siglost"><option value="goHome">goHome</option><option value="hover">hover</option><option value="autoLand">autoLand</option></select></label>',
    '        <label>起飞安全高度 (m) <input type="number" id="fp-wpml-tksec" value="20" min="0" max="200" /></label>',
    '        <label>标定飞行 <select id="fp-wpml-cali"><option value="false">false</option><option value="true">true</option></select></label>',
    '        <label>高度模式 <select id="fp-wpml-hmode"><option value="WGS84">WGS84</option><option value="relativeToStartPoint">relativeToStartPoint</option><option value="EGM96">EGM96</option></select></label>',
    '        <label>朝向模式 <select id="fp-wpml-headmode"><option value="auto">auto</option><option value="fixed">fixed</option><option value="manual">manual</option></select></label>',
    '        <label>云台模式 <select id="fp-wpml-gimbal"><option value="useRouteSetting">useRouteSetting</option><option value="manual">manual</option><option value="fixed">fixed</option></select></label>',
    '        <label>转弯模式 <select id="fp-wpml-turn"><option value="">默认</option><option value="toPoint">toPoint</option><option value="toPointAndPassWithContinuityCurvature">toPointAndPass…</option></select></label>',
    '        <label>镜头索引 <input type="number" id="fp-wpml-lens" value="0" min="0" max="5" /></label>',
    '        <label>挂载位 <input type="number" id="fp-wpml-payload" value="0" min="0" max="5" /></label>',
    '        <label>相机类型 <input type="text" id="fp-wpml-camtype" value="" placeholder="(留空)" /></label>',
    '        <label>触发模式 <select id="fp-wpml-trigger"><option value="reachPoint">reachPoint</option><option value="multipleTiming">multipleTiming</option><option value="betweenAdjacentPoints">betweenAdjacentPoints</option><option value="reachEnd">reachEnd</option></select></label>',
    '        <div id="fp-wpml-interval-row" style="display:none"><label>时间间隔 (s) <input type="number" id="fp-wpml-interval" value="2" min="0.1" max="60" step="0.1" /></label></div>',
    '        <label>动作组 <select id="fp-wpml-actmode"><option value="sequence">sequence</option><option value="parallel">parallel</option></select></label>',
    '        <label>文件前缀 <input type="text" id="fp-wpml-prefix" value="DJI" maxlength="32" /></label>',
    '        <label>镜头/挂载(legacy) <input type="text" id="fp-wpml-legacy" value="" placeholder="(留空)" /></label>',
    '      </div>',
    '    </details>',
    '  </div>',
    '  <div class="fp-section fp-actions">',
    '    <button id="fp-btn-generate" class="fp-btn fp-btn-primary" disabled>生成航线</button>',
    '    <button id="fp-btn-clear" class="fp-btn">清空</button>',
    '  </div>',
    '  <div id="fp-waypoint-editor" class="fp-section fp-waypoint-editor" style="display:none">',
    '    <h3>航点编辑 <span id="fp-wp-editor-label" class="fp-wp-editor-label"></span></h3>',
    '    <details open><summary>基础参数</summary>',
    '    <div class="fp-wp-grid">',
    '      <label>高度 (m)<br><input type="number" id="fp-wp-alt" value="60" min="1" max="500" step="1" /></label>',
    '      <label>速度 (m/s)<br><input type="number" id="fp-wp-speed" value="5" min="0.1" max="20" step="0.5" /></label>',
    '      <label>云台俯仰 (°)<br><input type="number" id="fp-wp-gimbal" value="-90" min="-90" max="30" /></label>',
    '      <label>朝向 (°)<br><input type="number" id="fp-wp-heading" value="" min="0" max="359" placeholder="自动" /></label>',
    '      <label>朝向模式<br><select id="fp-wp-headmode"><option value="">默认 (auto)</option><option value="auto">auto</option><option value="fixed">fixed</option><option value="manual">manual</option><option value="followWayline">followWayline</option></select></label>',
    '      <label>动作<br><select id="fp-wp-action"><option value="none">none</option><option value="photo" selected>photo</option><option value="video_start">video_start</option><option value="video_stop">video_stop</option><option value="hover">hover</option><option value="gimbal_rotate">gimbal_rotate</option><option value="rotate_yaw">rotate_yaw</option><option value="zoom">zoom</option><option value="focus">focus</option></select></label>',
    '      <label>悬停时间 (s)<br><input type="number" id="fp-wp-hold" value="0" min="0" max="60" /></label>',
    '      <label>转弯半径 (m, 0=直角)<br><input type="number" id="fp-wp-curve" value="0" min="0" max="100" step="0.5" /></label>',
    '    </div>',
    '    </details>',
    '    <details><summary>动作参数（gimbal/zoom/focus）</summary>',
    '    <div class="fp-wp-grid">',
    '      <label>目标云台俯仰 (°)<br><input type="number" id="fp-wp-actionpitch" value="" min="-90" max="30" placeholder="(留空)" /></label>',
    '      <label>旋转时间 (s)<br><input type="number" id="fp-wp-rotatetime" value="2" min="0.1" max="10" step="0.1" /></label>',
    '      <label>焦距 (mm, zoom)<br><input type="number" id="fp-wp-focal" value="24" min="1" max="200" step="0.5" /></label>',
    '      <label>对焦 X (0-1)<br><input type="number" id="fp-wp-focusx" value="0.5" min="0" max="1" step="0.05" /></label>',
    '      <label>对焦 Y (0-1)<br><input type="number" id="fp-wp-focusy" value="0.5" min="0" max="1" step="0.05" /></label>',
    '    </div>',
    '    </details>',
    '    <details><summary>高级（hyperlapse / 点延时）</summary>',
    '    <div class="fp-wp-grid">',
    '      <label><input type="checkbox" id="fp-wp-hyperlat" /> 横向 hyperlapse (hyperlateral)</label>',
    '      <label><input type="checkbox" id="fp-wp-hypervert" /> 纵向 hyperlapse (hypervertical)</label>',
    '    </div>',
    '    </details>',
    '    <div class="fp-wp-row">',
    '      <span id="fp-wp-coord" class="fp-wp-coord"></span>',
    '    </div>',
    '    <div class="fp-wp-actions">',
    '      <button id="fp-wp-apply" class="fp-btn fp-btn-primary">应用到当前</button>',
    '      <button id="fp-wp-apply-all" class="fp-btn" title="把当前编辑的字段批量应用到所有航点（除 lat/lng 外）">应用到全部</button>',
    '      <button id="fp-wp-save-server" class="fp-btn fp-btn-primary" style="display:none" title="把当前所有航点的修改一次性保存到服务器（更新 mission 表）">保存到服务器</button>',
    '      <button id="fp-wp-delete" class="fp-btn fp-btn-danger">删除该航点</button>',
    '      <button id="fp-wp-close" class="fp-btn">关闭</button>',
    '    </div>',
    '    <p id="fp-wp-dirty-hint" class="fp-wp-tip" style="display:none;color:#fbbf24">● 有未保存的修改</p>',
    '    <p class="fp-wp-tip">💡 拖动地图上的圆点也可改位置；双击圆点也可删除。</p>',
    '  </div>',
    '  <div id="fp-result-section" class="fp-section fp-result" style="display:none">',
    '    <h3>生成结果</h3>',
    '    <div id="fp-result-stats"></div>',
    '    <div class="fp-result-actions">',
    '      <button id="fp-btn-add-to-project" class="fp-btn">加入项目</button>',
    '      <button id="fp-btn-export-kmz" class="fp-btn fp-btn-primary">导出 KMZ</button>',
    '      <button id="fp-btn-export-kml" class="fp-btn">导出 KML</button>',
    '    </div>',
    '  </div>',
    '</div>',
    '<div class="fp-map-area">',
    '  <div class="fp-map-wrap">',
    '    <div id="fp-map"></div>',
    '  </div>',
    '  <div id="fp-map-status" class="fp-map-status">地图加载中…</div>',
    '  <div class="fp-nav">',
    '    <h3>导航</h3>',
    '    <div class="fp-nav-row"><input id="fp-nav-lat" type="number" step="any" placeholder="lat (纬度)" /><input id="fp-nav-lng" type="number" step="any" placeholder="lng (经度)" /></div>',
    '    <div class="fp-nav-row">',
    '      <button id="fp-btn-goto" class="fp-btn">跳转</button>',
    '      <button id="fp-btn-fit-world" class="fp-btn">全球</button>',
    '      <button id="fp-btn-fit-bounds" class="fp-btn">定位航线</button>',
    '    </div>',
    '    <div class="fp-nav-row">',
    '      <button id="fp-btn-zoom-in" class="fp-btn">+</button>',
    '      <button id="fp-btn-zoom-out" class="fp-btn">−</button>',
    '      <select id="fp-basemap-sel" class="fp-basemap-sel">',
    '        <option value="高德卫星影像 (国内)">高德卫星 (国内)</option>',
    '        <option value="高德矢量 (国内)">高德矢量 (国内)</option>',
    '        <option value="Esri 卫星 (全球)">Esri 卫星 (全球)</option>',
    '        <option value="OpenStreetMap (全球)">OSM (全球)</option>',
    '      </select>',
    '      <button id="fp-btn-refresh" class="fp-btn">⟳</button>',
    '    </div>',
    '  </div>',
    '</div>',
  ].join("\n");

  // ======================================================================
  // Map = OpenLayers (no WebGL, Canvas 2D rendering)
  // OL renders tiles to a Canvas via the default ol/render/canvas
  // pipeline. No WebGL required. No dependency on maplibre / Leaflet.
  //
  // We use OL as a thin wrapper exposing a small surface area so the
  // existing call sites (addPoint / drawFlightPath / changeBasemap / etc.)
  // don't have to know about OL specifics.
  // ======================================================================

  // OLMap wraps an ol.Map and exposes the methods the rest of main.js uses.
  function OLMap(targetEl) {
    var self = this;
    this.target = targetEl;
    this.sources = [];            // [{ id, name, url, maxZoom, attribution }]
    this.activeName = null;
    this.listeners = { move: [], click: [], dblclick: [] };
    this._polylineFeats = [];     // ol.Feature references for our 2 dynamic polylines (drawing / flight)
    this._drawing = true;         // cursor mode
    this._suppressClick = false;  // set true during drag

    var vectorSource = new ol.source.Vector();
    var vectorLayer = new ol.layer.Vector({
      source: vectorSource,
      zIndex: 10,
      style: function (feature) { return feature.get("__style") || null; },
    });
    this._vectorSource = vectorSource;
    this._vectorLayer = vectorLayer;

    var tileLayer = new ol.layer.Tile({
      source: new ol.source.XYZ({ url: "", crossOrigin: "anonymous" }),
    });
    this._tileLayer = tileLayer;

    this._map = new ol.Map({
      target: targetEl,
      layers: [tileLayer, vectorLayer],
      view: new ol.View({
        center: ol.proj.fromLonLat([113.9, 22.5]),
        zoom: 10,
        minZoom: 2,
        maxZoom: 19,
        enableRotation: false,
      }),
      controls: [],                // no zoom buttons, no attribution — we draw our own
      // OL 9.x UMD: ol.interaction is an object whose `defaults` key holds
      // another object whose `defaults` key is the actual factory. We
      // disable doubleClickZoom because double-click finishes the
      // polygon/cable drawing instead of zooming the map.
      interactions: (ol.interaction.defaults.defaults
                        || ol.interaction.defaults
                        || ol.defaults)({ doubleClickZoom: false }),
    });

    // Forward map events
    // Forward map events
    this._map.on("click", function (e) {
      if (self._suppressClick) { self._suppressClick = false; return; }
      // If click hit an existing waypoint marker, leave it to the
      // Select interaction — don't add a new point.
      var hit = self._map.forEachFeatureAtPixel(e.pixel, function (f) { return f; });
      if (hit) return;
      if (!self._drawing) return;
      var ll = ol.proj.toLonLat(e.coordinate);
      self._fire("click", { latLng: { lat: ll[1], lng: ll[0] }, originalEvent: e });
    });
    this._map.on("dblclick", function (e) {
      e.preventDefault ? null : null;
      self._fire("dblclick", { originalEvent: e });
    });

    // Suppress the click that follows a drag (OL fires both otherwise).
    var downPx = null;
    this._map.on("pointerdown", function (e) { downPx = e.pixel; });
    this._map.on("pointerup", function (e) {
      if (downPx) {
        var dx = e.pixel[0] - downPx[0], dy = e.pixel[1] - downPx[1];
        if (Math.abs(dx) + Math.abs(dy) > 5) self._suppressClick = true;
      }
      downPx = null;
    });

    // -----------------------------------------------------------------
    // Waypoint editing: select + translate interactions on point features.
    // - select: single-click a waypoint to fire "waypoint:select" with its
    //   marker payload; click on empty map fires "waypoint:deselect".
    // - translate: drag a waypoint to move it; fires "waypoint:move" with
    //   new (lat, lng).
    // -----------------------------------------------------------------
    var Select = (ol.interaction.Select || function(){});
    var selectInteraction = new Select({
      layers: [vectorLayer],
      hitTolerance: 8,  // markers are 6-12px wide; allow 8px of slop
      style: function (feature) {
        // Highlight selected: red ring + larger radius
        var base = feature.get("__style");
        var hl = new ol.style.Style({
          image: new ol.style.Circle({
            radius: 12,
            fill: new ol.style.Fill({ color: "rgba(248,113,113,0.4)" }),
            stroke: new ol.style.Stroke({ color: "#f87171", width: 3 }),
          }),
        });
        if (base) hl.setText(base.getText());
        return hl;
      },
    });
    this._map.addInteraction(selectInteraction);
    this._select = selectInteraction;

    var Translate = (ol.interaction.Translate || function(){});
    var translateInteraction = new Translate({
      layers: [vectorLayer],
    });
    this._map.addInteraction(translateInteraction);
    this._translate = translateInteraction;

    // Bridge: when a feature is dragged, fire our own event with payload.
    translateInteraction.on("translateend", function (evt) {
      var feat = evt.feature;
      if (!feat) return;
      var payload = feat.get("__payload");
      if (!payload) return;
      var coord = feat.getGeometry().getCoordinates();
      var ll = ol.proj.toLonLat(coord);
      payload.lat = ll[1];
      payload.lng = ll[0];
      // Re-render the marker style (radius/label) from payload
      self._refreshFeatureStyle(feat, payload);
      self._fire("waypoint:move", payload);
    });

    // Bridge: when a feature is selected, fire our own event.
    selectInteraction.on("select", function (evt) {
      var added = evt.selected && evt.selected[0];
      if (added) {
        var payload = added.get("__payload");
        if (payload) {
          self._fire("waypoint:select", payload);
          return;
        }
      }
      self._fire("waypoint:deselect", null);
    });

    // Click on empty map → deselect (only if no marker click happened)
    this._map.on("click", function (e) {
      var hit = self._map.forEachFeatureAtPixel(e.pixel, function (f) { return f; });
      if (!hit) {
        // empty area — fire deselect
        self._fire("waypoint:deselect", null);
      }
    });
  }

  OLMap.prototype._refreshFeatureStyle = function (feat, payload) {
    if (!feat || !payload) return;
    var radius = payload.radius || 6;
    var color = payload.color || "#4ade80";
    var weight = payload.weight || 2;
    var style = new ol.style.Style({
      image: new ol.style.Circle({
        radius: radius,
        fill: new ol.style.Fill({ color: this._withAlpha(color, 0.9) }),
        stroke: new ol.style.Stroke({ color: color, width: weight }),
      }),
    });
    if (payload.label) {
      style.setText(new ol.style.Text({
        text: payload.label,
        font: "10px monospace",
        offsetX: 14,
        offsetY: 0,
        fill: new ol.style.Fill({ color: "#e5e7eb" }),
        backgroundFill: new ol.style.Fill({ color: "rgba(0,0,0,0.7)" }),
        padding: [1, 2, 1, 2],
      }));
    }
    feat.set("__style", style);
  };

  // Bridge: extend event API with waypoint:* events
  OLMap.prototype.onWaypoint = function (name, cb) {
    (this.listeners[name] = this.listeners[name] || []).push(cb);
    return this;
  };
  // Patch _fire to also accept waypoint:* events via the same registry.
  // (Already generic via the existing _fire.)

  OLMap.prototype._fire = function (name, data) {
    (this.listeners[name] || []).forEach(function (cb) { cb(data); });
  };
  OLMap.prototype.on = function (name, cb) {
    (this.listeners[name] = this.listeners[name] || []).push(cb);
    return this;
  };

  OLMap.prototype.setSource = function (name, spec) {
    this.activeName = name;
    var srcOpts = {
      crossOrigin: "anonymous",
      maxZoom: spec.maxZoom || 19,
      attributions: spec.attribution ? [spec.attribution] : undefined,
    };
    // OL 9.x XYZ source does NOT expand {s} placeholders. For tiled
    // services that use {s} subdomain rotation (Gaode, Mapbox), expand
    // to an explicit urls[] array so OL fetches them in parallel.
    if (spec.subdomains && spec.subdomains.length) {
      srcOpts.urls = spec.subdomains.map(function (s) {
        return spec.url.replace(/\{s\}/g, s);
      });
    } else {
      srcOpts.url = spec.url;
    }
    var newSrc = new ol.source.XYZ(srcOpts);
    this._map.getLayers().setAt(0, new ol.layer.Tile({ source: newSrc }));
  };

  OLMap.prototype.setView = function (centerLat, centerLng, zoom) {
    var v = this._map.getView();
    if (centerLat !== undefined && centerLng !== undefined) {
      v.setCenter(ol.proj.fromLonLat([centerLng, centerLat]));
    }
    if (zoom !== undefined) v.setZoom(zoom);
    this._fire("move");
  };

  OLMap.prototype.zoomIn = function () {
    var v = this._map.getView();
    v.setZoom((v.getZoom() || 0) + 1);
  };
  OLMap.prototype.zoomOut = function () {
    var v = this._map.getView();
    v.setZoom((v.getZoom() || 0) - 1);
  };

  OLMap.prototype.fitBounds = function (latLngs, paddingPx) {
    if (!latLngs || !latLngs.length) return;
    var minLat = Infinity, maxLat = -Infinity, minLng = Infinity, maxLng = -Infinity;
    latLngs.forEach(function (ll) {
      if (ll.lat < minLat) minLat = ll.lat;
      if (ll.lat > maxLat) maxLat = ll.lat;
      if (ll.lng < minLng) minLng = ll.lng;
      if (ll.lng > maxLng) maxLng = ll.lng;
    });
    var extent = ol.proj.transformExtent(
      [minLng, minLat, maxLng, maxLat],
      "EPSG:4326", "EPSG:3857"
    );
    this._map.getView().fit(extent, {
      padding: [paddingPx || 50, paddingPx || 50, paddingPx || 50, paddingPx || 50],
      maxZoom: 18,
      duration: 0,
    });
  };

  OLMap.prototype.clearOverlays = function () {
    this._vectorSource.clear();
    this._polylineFeats = [];
  };

  OLMap.prototype._styledMarker = function (m) {
    return new ol.Feature({
      geometry: new ol.geom.Point(ol.proj.fromLonLat([m.lng, m.lat])),
    });
  };

  OLMap.prototype.addMarker = function (m) {
    var f = this._styledMarker(m);
    var radius = m.radius || 6;
    var color = m.color || "#4ade80";
    var weight = m.weight || 2;
    var style = new ol.style.Style({
      image: new ol.style.Circle({
        radius: radius,
        fill: new ol.style.Fill({ color: this._withAlpha(color, m.fillOpacity != null ? m.fillOpacity : 0.9) }),
        stroke: new ol.style.Stroke({ color: color, width: weight }),
      }),
    });
    if (m.label) {
      style.setText(new ol.style.Text({
        text: m.label,
        font: "10px monospace",
        offsetX: 14,
        offsetY: 0,
        fill: new ol.style.Fill({ color: "#e5e7eb" }),
        backgroundFill: new ol.style.Fill({ color: "rgba(0,0,0,0.7)" }),
        padding: [1, 2, 1, 2],
      }));
    }
    f.set("__style", style);
    f.set("__payload", Object.assign({}, m));  // snapshot for select/translate
    this._vectorSource.addFeature(f);
    return f;
  };

  // Update a feature's position from a {lat, lng} payload. Used when
  // a waypoint's coordinates change via the side-panel (alt / heading)
  // or the dispatch event from another interaction.
  OLMap.prototype.updateMarker = function (payload) {
    if (!payload) return;
    var self = this;
    this._vectorSource.forEachFeature(function (f) {
      var p = f.get("__payload");
      if (p && p.id === payload.id) {
        // Update payload in place so style refresh uses new values.
        Object.assign(p, payload);
        var coord = ol.proj.fromLonLat([p.lng, p.lat]);
        f.getGeometry().setCoordinates(coord);
        self._refreshFeatureStyle(f, p);
      }
    });
  };

  // Remove a feature whose payload.id matches.
  OLMap.prototype.removeMarker = function (id) {
    if (id == null) return;
    var src = this._vectorSource;
    var toRemove = [];
    src.forEachFeature(function (f) {
      var p = f.get("__payload");
      if (p && p.id === id) toRemove.push(f);
    });
    toRemove.forEach(function (f) { src.removeFeature(f); });
  };

  // Return the count of currently-rendered waypoint markers.
  OLMap.prototype.markerCount = function () {
    return this._vectorSource.getFeatures().length;
  };

  OLMap.prototype._withAlpha = function (hex, alpha) {
    // hex like "#4ade80" → rgba(74,222,128,alpha)
    var h = hex.replace("#", "");
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    var r = parseInt(h.slice(0, 2), 16);
    var g = parseInt(h.slice(2, 4), 16);
    var b = parseInt(h.slice(4, 6), 16);
    return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
  };

  OLMap.prototype.addLine = function (line) {
    var coords = line.coords.map(function (p) { return ol.proj.fromLonLat([p[1], p[0]]); });
    var f = new ol.Feature({ geometry: new ol.geom.LineString(coords) });
    f.set("__style", new ol.style.Style({
      stroke: new ol.style.Stroke({
        color: line.color || "#4ade80",
        width: line.width || 2,
        lineDash: line.dash || undefined,
      }),
    }));
    this._vectorSource.addFeature(f);
    this._polylineFeats.push(f);
    return f;
  };

  // Replace an existing line feature (matched by id) or add a new one.
  OLMap.prototype.upsertLine = function (id, line) {
    var self = this;
    var existing = this._vectorSource.getFeatures().filter(function (f) {
      return f.get("__lineId") === id;
    });
    if (existing.length) {
      this._vectorSource.removeFeature(existing[0]);
      this._polylineFeats = this._polylineFeats.filter(function (f) { return f !== existing[0]; });
    }
    var coords = line.coords.map(function (p) { return ol.proj.fromLonLat([p[1], p[0]]); });
    var f = new ol.Feature({ geometry: new ol.geom.LineString(coords) });
    f.set("__lineId", id);
    f.set("__style", new ol.style.Style({
      stroke: new ol.style.Stroke({
        color: line.color || "#4ade80",
        width: line.width || 2,
        lineDash: line.dash || undefined,
      }),
    }));
    this._vectorSource.addFeature(f);
    this._polylineFeats.push(f);
  };

  OLMap.prototype.setCursor = function (drawing) {
    this._drawing = !!drawing;
    // OL creates a child <div class="ol-viewport"> inside our target.
    // Cursor must be set on that child since it captures pointer events.
    var viewport = this.target ? this.target.querySelector(".ol-viewport") : null;
    if (viewport) viewport.classList.toggle("fp-idle", !drawing);
  };

  OLMap.prototype.updateSize = function () {
    this._map.updateSize();
  };

  OLMap.prototype.getCenter = function () {
    var c = ol.proj.toLonLat(this._map.getView().getCenter());
    return { lat: c[1], lng: c[0] };
  };

  OLMap.prototype.getZoom = function () {
    return this._map.getView().getZoom();
  };

  var state = {
    mode: "polygon",
    drawing: true,
    points: [],
    markers: [],
    polylines: [],
    map: null,
    layers: {},
    lastMission: null,
    failedTiles: 0,
    droneModels: {},
    currentProject: null,
    allProjects: [],
    lastModelId: null,
    // When a saved mission is loaded via "查看", this is its id; the
    // waypoint editor's "保存到服务器" button is enabled while non-null.
    editingMissionId: null,
    // True if the user has changed waypoints (alt, position, etc.) since
    // the last save. Drives the "● 有未保存修改" hint.
    editingMissionDirty: false,
  };

  function setStatus(msg, level) {
    var s = $("fp-map-status");
    if (!s) return;
    s.textContent = msg;
    s.className = "fp-map-status" + (level ? " " + level : "");
  }

  function toast(msg, isError) {
    var t = el("div", { className: "fp-toast" + (isError ? " error" : "") });
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 4000);
  }

  function clearDrawing() {
    if (!state.map) return;
    state.markers = [];
    state.polylines = [];
    if (state.wpLabels) state.wpLabels = [];
    state.map.clearOverlays();
    setCursor(false);
  }

  function setCursor(drawing) {
    if (!state.map) return;
    state.map.setCursor(!!drawing);
  }

  // In OL mode, markers are just data objects {lat, lng, color, radius, weight, label}.
  // The renderer adds them as ol.Feature with ol.style.Style.

  function addPoint(lat, lng) {
    if (!state.map) return;
    var idx = state.points.length;
    var isFirst = idx === 0;
    var isPOI = (state.mode === "orbit" || state.mode === "spiral" || state.mode === "corkscrew");
    var color, radius, weight, label;
    if (isPOI) {
      color = "#38bdf8"; radius = 8; weight = 3; label = "POI";
    } else if (isFirst) {
      color = "#fbbf24"; radius = 8; weight = 3; label = "#1";
    } else {
      color = "#4ade80"; radius = 6; weight = 2; label = "#" + (idx + 1);
    }
    var marker = {
      id: "wp_" + Date.now() + "_" + Math.floor(Math.random() * 1e6),
      lat: lat, lng: lng,
      color: color, radius: radius, weight: weight, label: label,
      alt: 60, speed: 5, heading: null, gimbal_pitch: -90, action: "photo",
    };
    state.map.addMarker(marker);
    state.markers.push(marker);
    state.points.push([lat, lng]);

    // Update or create connecting polyline
    if (state.points.length >= 2 && !isPOI) {
      var lineId = "fp-line-draw";
      var coords = state.points.map(function (p) { return [p[0], p[1]]; });
      state.map.upsertLine(lineId, {
        coords: coords,
        color: "#4ade80",
        width: 2,
        dash: [4, 4],
      });
      if (state.polylines.indexOf(lineId) < 0) state.polylines.push(lineId);
    }
    checkGenerateReady();
  }

  function setMode(mode) {
    state.mode = mode;
    state.drawing = true;
    state.points = [];
    clearDrawing();
    document.querySelectorAll(".fp-tabs button").forEach(function (b) {
      b.classList.toggle("active", b.dataset.mode === mode);
    });
    document.querySelectorAll(".fp-mode-panel").forEach(function (p) {
      p.classList.toggle("active", p.dataset.panel === mode);
    });
    updateHints();
    setCursor(true);  // drawing on
    checkGenerateReady();
  }

  function updateHints() {
    var hints = {
      polygon: "📍 在地图上依次点击多边形顶点，双击或回车结束。",
      spiral: "📍 点击中心点，生成螺旋。",
      orbit: "📍 点击 POI（兴趣点），生成环绕轨迹。",
      cable: "📍 依次点击路径点（起点→终点），双击结束。",
      corkscrew: "📍 点击中心点，生成螺旋柱。",
      grid: "📍 点击矩形中心，生成矩形扫描。",
    };
    // APP_HTML has a single <div class="fp-hint"> per mode tab panel; the
    // current active panel's hint gets updated.
    var active = document.querySelector(".fp-mode-panel.active .fp-hint")
              || document.querySelector(".fp-hint");
    if (active) active.textContent = hints[state.mode] || "";
  }

  function checkGenerateReady() {
    var ready = (state.mode === "polygon" || state.mode === "cable")
      ? state.points.length >= 2
      : state.points.length >= 1;
    $("fp-btn-generate").disabled = !ready;
    $("fp-btn-generate").textContent = ready ? "生成航线" : "请先在地图上绘制";
  }

  function gatherParams() {
    // Common flight params (always apply to every mode unless an
    // algorithm-specific field overrides — e.g. spiral has its own alt0/alt1).
    // These map directly to the Litchi-style "Flight settings" panel.
    function opt(name) {
      var el = $(name);
      return el ? el.value : null;
    }
    function numOpt(name) {
      var v = opt(name);
      return v === "" || v == null ? null : Number(v);
    }
    var p = {
      name: "Mission " + new Date().toISOString().slice(0, 16).replace("T", " "),
      altitude:    numOpt("fp-flight-alt")    != null ? numOpt("fp-flight-alt")    : 60,
      speed:       numOpt("fp-flight-speed")  != null ? numOpt("fp-flight-speed")  : 5,
      gimbal_pitch: numOpt("fp-flight-gimbal") != null ? numOpt("fp-flight-gimbal") : -90,
      heading:     numOpt("fp-flight-heading"),  // null = auto
      action:      opt("fp-flight-action")   || "photo",
      drone_model: opt("fp-drone-model") || undefined,
    };

    // ----- WPML mission-level params (19 fields) -----
    function opt(name) {
      var el = $(name);
      return el ? el.value : null;
    }
    function numOpt(name) {
      var v = opt(name);
      return v === "" || v == null ? null : Number(v);
    }
    p.fly_to_wayline_mode    = opt("fp-wpml-flyto");
    p.finish_action          = opt("fp-wpml-finish");
    p.exit_on_rc_low         = opt("fp-wpml-rclow");
    p.exit_on_signal_lost    = opt("fp-wpml-siglost");
    p.takeoff_security_height = numOpt("fp-wpml-tksec");
    if (p.takeoff_security_height == null) p.takeoff_security_height = 20;
    p.cali_flight_enable     = (opt("fp-wpml-cali") === "true") ? 1 : 0;
    p.height_mode            = opt("fp-wpml-hmode");
    p.ellipsoid_height       = 0;
    p.heading_mode           = opt("fp-wpml-headmode");
    p.gimbal_mode            = opt("fp-wpml-gimbal");
    p.auto_flight_speed      = 0;
    p.turn_mode_override     = opt("fp-wpml-turn");
    p.payload_position_index = numOpt("fp-wpml-payload");
    p.camera_type_override   = opt("fp-wpml-camtype") || "";
    p.lens_index             = numOpt("fp-wpml-lens");
    p.action_group_mode      = opt("fp-wpml-actmode");
    p.action_trigger_type    = opt("fp-wpml-trigger");
    p.photo_interval         = (opt("fp-wpml-trigger") === "multipleTiming")
                                ? numOpt("fp-wpml-interval") : null;
    p.file_suffix_prefix     = opt("fp-wpml-prefix") || "DJI";
    p.recording_suffix_prefix = "REC";

    var body = null;
    if (state.mode === "polygon") {
      var polyFrontOverlap = parseFloat($("fp-poly-frontoverlap").value);
      // Auto-derive photo_interval when trigger is multipleTiming:
      // distance between photos = swath × (1 - front_overlap); interval
      // = distance / speed. Heuristic without GSD/camera: scale by
      // sqrt(altitude/60) so low-altitude flights get shorter intervals.
      var frontOlap = isFinite(polyFrontOverlap) ? polyFrontOverlap : 0.8;
      var autoInterval = ((1 - frontOlap) * Math.sqrt((p.altitude || 60) / 60));
      body = Object.assign({}, p, {
        polygon: state.points,
        // Per-Litchi polygon params — all editable in the side panel
        line_spacing:    parseFloat($("fp-poly-spacing").value),
        angle_deg:       parseFloat($("fp-poly-angle").value),
        margin:          parseFloat($("fp-poly-margin").value),
        overlap:         parseFloat($("fp-poly-overlap").value),  // 旁向 (side)
        front_overlap:   frontOlap,                                // 前向 (front)
        // Only override the WPML photo_interval if the user picked
        // multipleTiming in the advanced panel.
        photo_interval:   (p.action_trigger_type === "multipleTiming") ? autoInterval : (p.photo_interval || null),
      });
    } else if (state.mode === "spiral") {
      // Spiral has its own start_alt / end_alt; only use the global
      // altitude as a default if the user hasn't set them.
      var spAlt0 = parseFloat($("fp-cs-alt0").value);
      var spAlt1 = parseFloat($("fp-cs-alt1").value);
      if (!isFinite(spAlt0) || isNaN(spAlt0)) spAlt0 = p.altitude - 20;
      if (!isFinite(spAlt1) || isNaN(spAlt1)) spAlt1 = p.altitude;
      body = Object.assign({}, p, {
        center: { lat: state.points[0][0], lon: state.points[0][1] },
        start_radius: parseFloat($("fp-cs-radius").value),
        end_radius: parseFloat($("fp-cs-radius").value),
        turns: parseFloat($("fp-cs-turns").value),
        start_alt: spAlt0,
        end_alt: spAlt1,
        points_per_turn: parseInt($("fp-cs-ppt").value, 10),
        heading_mode: "followWayline",
      });
    } else if (state.mode === "orbit") {
      body = Object.assign({}, p, {
        center: { lat: state.points[0][0], lon: state.points[0][1] },
        radius: parseFloat($("fp-orbit-radius").value),
        points: parseInt($("fp-orbit-samples").value, 10),
        clockwise: true,
      });
    } else if (state.mode === "cable") {
      body = Object.assign({}, p, {
        path: state.points,
        samples: parseInt($("fp-cable-samples").value, 10),
        repeat: parseInt($("fp-cable-repeat").value, 10),
      });
    } else if (state.mode === "corkscrew") {
      body = Object.assign({}, p, {
        center: { lat: state.points[0][0], lon: state.points[0][1] },
        radius: parseFloat($("fp-cs2-radius").value),
        start_alt: parseFloat($("fp-cs2-alt").value) / 2,
        end_alt: parseFloat($("fp-cs2-alt").value),
        turns: parseFloat($("fp-cs2-turns").value),
        points_per_turn: 24,
      });
    } else if (state.mode === "grid") {
      var gridFrontOverlap = parseFloat($("fp-grid-frontoverlap").value);
      var frontOlap2 = isFinite(gridFrontOverlap) ? gridFrontOverlap : 0.8;
      var autoInterval2 = ((1 - frontOlap2) * Math.sqrt((p.altitude || 60) / 60));
      body = Object.assign({}, p, {
        center: { lat: state.points[0][0], lon: state.points[0][1] },
        width: parseFloat($("fp-grid-w").value),
        height: parseFloat($("fp-grid-h").value),
        line_spacing: parseFloat($("fp-grid-spacing").value),
        angle_deg: parseFloat($("fp-grid-angle").value),
        overlap: parseFloat($("fp-grid-overlap").value),  // 旁向
        front_overlap: frontOlap2,                          // 前向
        photo_interval: (p.action_trigger_type === "multipleTiming") ? autoInterval2 : (p.photo_interval || null),
      });
    }
    return body;
  }

  function getCookie(name) {
    var m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }

  // ----------------------------------------------------------------
  // Scale bar helpers — convert a meters value into a "nice" round
  // number (1, 2, 5 × 10^n) for the floating scale bar.
  // ----------------------------------------------------------------
  function niceScale(rawM) {
    if (!isFinite(rawM) || rawM <= 0) return 1000;
    var exp = Math.floor(Math.log10(rawM));
    var base = Math.pow(10, exp);
    var m = rawM / base;
    var nice;
    if (m < 1.5) nice = 1;
    else if (m < 3.5) nice = 2;
    else if (m < 7.5) nice = 5;
    else nice = 10;
    return nice * base;
  }
  function formatScale(m) {
    if (m >= 1000) return (m / 1000) + " km";
    if (m >= 1) return Math.round(m) + " m";
    return (m * 100).toFixed(0) + " cm";
  }

  // Haversine distance (meters) between two lat/lng points.
  function haversine(lat1, lng1, lat2, lng2) {
    var R = 6371000;
    var dLat = (lat2 - lat1) * Math.PI / 180;
    var dLng = (lng2 - lng1) * Math.PI / 180;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  function apiHeaders() {
    var h = { "Content-Type": "application/json" };
    var csrf = getCookie("csrftoken");
    if (csrf) h["X-CSRFToken"] = csrf;
    return h;
  }

  function generate() {
    var body = gatherParams();
    if (!body) return;
    setStatus("正在生成航线...");
    fetch(realApi(state.mode + "/"), {
      method: "POST",
      headers: apiHeaders(),
      credentials: "same-origin",
      body: JSON.stringify(body),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || r.statusText); });
        return r.json();
      })
      .then(function (m) {
        state.lastMission = m;
        renderMission(m);
        drawFlightPath(m);
        setStatus("✓ 已生成 " + m.stats.waypoints + " 航点");
        toast("✓ 生成 " + m.stats.waypoints + " 航点 · " +
              Math.round(m.stats.distance_m) + "m · " +
              Math.round(m.stats.duration_s) + "s");
      })
      .catch(function (e) {
        setStatus("✗ " + e.message, "error");
        toast("✗ " + e.message, true);
      });
  }

  function renderMission(m) {
    $("fp-result-section").style.display = "";
    var s = m.stats;
    var statsEl = $("fp-stats") || $("fp-result-stats");
    if (statsEl) statsEl.innerHTML =
      "<strong>航点:</strong> " + s.waypoints + "<br>" +
      "<strong>航线长度:</strong> " + Math.round(s.distance_m) + " m<br>" +
      "<strong>预计飞行:</strong> " + Math.round(s.duration_s) + " s (" + (s.duration_s / 60).toFixed(1) + " min)<br>" +
      "<strong>覆盖面积:</strong> " + Math.round(s.area_m2) + " m²<br>" +
      "<strong>边界:</strong><br>" +
      "&nbsp;lat " + m.bounds[0].toFixed(6) + " → " + m.bounds[2].toFixed(6) + "<br>" +
      "&nbsp;lon " + m.bounds[1].toFixed(6) + " → " + m.bounds[3].toFixed(6);
    var dlKml = $("fp-dl-kml");
    if (dlKml) {
      dlKml.href = realApi("export/" + m.id + ".kml");
      dlKml.download = m.name + ".kml";
    }
    var dlGeo = $("fp-dl-geojson");
    if (dlGeo) {
      dlGeo.href = realApi("export/" + m.id + ".geojson");
      dlGeo.download = m.name + ".geojson";
    }
  }

  // -------------------------------------------------------------------------
  // Project / model
  // -------------------------------------------------------------------------

  function loadDroneModels() {
    return fetch(realApi("drone-models/"), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var sel = $("fp-drone-model");
        if (!sel) return;
        // Group by category
        var byCat = { consumer: [], enterprise: [], professional: [], fpv: [] };
        (j.models || []).forEach(function (m) {
          state.droneModels[m.model_id] = m;
          (byCat[m.category] || (byCat[m.category] = [])).push(m);
        });
        var labels = {
          consumer: "── 消费级 ──",
          enterprise: "── 行业级 ──",
          professional: "── 专业级 ──",
          fpv: "── FPV ──",
        };
        sel.innerHTML = "";
        Object.keys(labels).forEach(function (cat) {
          if (!byCat[cat] || byCat[cat].length === 0) return;
          var og = document.createElement("optgroup");
          og.label = labels[cat];
          byCat[cat].forEach(function (m) {
            var opt = document.createElement("option");
            opt.value = m.model_id;
            opt.textContent = m.display_name + "  (id=" + m.model_id + ")";
            og.appendChild(opt);
          });
          sel.appendChild(og);
        });
        // Default: Mavic 3 (a safe mid-range consumer choice)
        sel.value = "MAVIC_3";
        onModelChange();
      })
      .catch(function (e) {
        toast("✗ 加载机型列表失败: " + e.message, true);
      });
  }

  function onModelChange() {
    var sel = $("fp-drone-model");
    if (!sel) return;
    var mid = sel.value;
    if (!mid) {
      $("fp-model-info").style.display = "none";
      return;
    }
    var m = state.droneModels[mid];
    if (!m) return;
    state.lastModelId = mid;

    // Show spec panel
    $("fp-model-info").style.display = "";
    var sLo = m.speed_range_m_s ? m.speed_range_m_s[0] : (m.min_speed || 1);
    var sHi = m.speed_range_m_s ? m.speed_range_m_s[1] : (m.max_speed || 20);
    var aLo = m.altitude_range_m ? m.altitude_range_m[0] : 2;
    var aHi = m.altitude_range_m ? m.altitude_range_m[1] : 500;
    var features = [];
    if (m.supports_hyper) features.push("超采样");
    if (m.supports_overlap) features.push("重叠率");
    if (m.supports_pano) features.push("全景");
    if (m.supports_curve) features.push("平滑转弯");
    $("fp-model-specs").innerHTML =
      "<strong>类别:</strong> " + m.category + "<br>" +
      "<strong>速度:</strong> " + sLo + "–" + sHi + " m/s<br>" +
      "<strong>高度:</strong> " + aLo + "–" + aHi + " m<br>" +
      "<strong>最大距离:</strong> " + (m.max_flight_distance != null ? m.max_flight_distance : "—") + " m<br>" +
      "<strong>最长航时:</strong> " + (m.max_flight_time != null ? m.max_flight_time : "—") + " min<br>" +
      "<strong>相机:</strong> " + (m.camera_type || "—") + "<br>" +
      "<strong>支持特性:</strong> " + (features.join("、") || "—") + "<br>" +
      "<strong>支持动作:</strong> " + (m.supported_actions || []).join("、") + "<br>" +
      (m.notes ? "<br><em style=\"color:#9ca3af\">" + m.notes + "</em>" : "");

    // Clamp altitude and speed inputs to model envelope
    var altEl = $("fp-param-altitude");
    if (altEl) { altEl.min = aLo; altEl.max = aHi; if (parseFloat(altEl.value) < aLo) altEl.value = aLo; if (parseFloat(altEl.value) > aHi) altEl.value = aHi; }
    var spdEl = $("fp-param-speed");
    if (spdEl) { spdEl.min = sLo; spdEl.max = sHi; if (parseFloat(spdEl.value) < sLo) spdEl.value = sLo; if (parseFloat(spdEl.value) > sHi) spdEl.value = sHi; }

    // Enable / disable action options based on model's supported_actions
    var actionMap = {
      "takePhoto": "photo", "startRecord": "video_start", "stopRecord": "video_stop",
      "hover": "hover", "gimbalRotate": "gimbal_rotate", "rotateYaw": "rotate_yaw",
      "zoom": "zoom", "focusCamera": "focus"
    };
    var supported = m.supported_actions || [];
    var actSel = $("fp-param-action");
    if (actSel) {
      Array.prototype.forEach.call(actSel.options, function (o) {
        // Find the DJI actuator that this option represents
        var actuator = null;
        for (var k in actionMap) if (actionMap[k] === o.value) { actuator = k; break; }
        if (o.value === "none") {
          o.disabled = false;
        } else if (actuator) {
          o.disabled = supported.indexOf(actuator) === -1;
        }
      });
      // If current selection is unsupported, fall back to "none"
      if (actSel.selectedIndex >= 0 && actSel.options[actSel.selectedIndex].disabled) {
        actSel.value = "none";
      }
    }

    // Enable / disable lens options based on model capability
    // Heuristic: only multi-lens models allow lens index > 0
    var isMultilens = (m.series === "mavic" || m.series === "matrice" || m.model_id === "AVATA_2");
    var lensSel = $("fp-wpml-lens");
    if (lensSel) {
      Array.prototype.forEach.call(lensSel.options, function (o) {
        if (o.value === "") { o.disabled = false; return; }
        o.disabled = !isMultilens;
      });
      if (lensSel.selectedIndex >= 0 && lensSel.options[lensSel.selectedIndex].disabled) {
        lensSel.value = "";
      }
    }

    // Disable payload-position override except for M300/M350 (dual-mount)
    var ppiSel = $("fp-wpml-payload-idx");
    if (ppiSel) {
      var dualMount = (m.model_id === "M300" || m.model_id === "M350");
      Array.prototype.forEach.call(ppiSel.options, function (o) {
        if (o.value === "") { o.disabled = false; return; }
        o.disabled = !dualMount;
      });
    }
  }

  function createProject() {
    // APP_HTML doesn't include dedicated project-name/description input
    // fields — they're rare edits. Prompt the user inline.
    var model = $("fp-drone-model").value;
    if (!model) { toast("✗ 请先选择机型", true); return Promise.resolve(null); }
    var name = window.prompt("新建项目名称：", "Mission " + new Date().toISOString().slice(0, 16).replace("T", " "));
    if (name === null) return Promise.resolve(null);    // user cancelled
    name = (name || "").trim();
    if (!name) { toast("✗ 项目名不能为空", true); return Promise.resolve(null); }
    var desc = window.prompt("项目描述（可选，可直接点确定跳过）：", "") || "";
    return fetch(realApi("projects/"), {
      method: "POST",
      headers: apiHeaders(),
      credentials: "same-origin",
      body: JSON.stringify({ name: name, drone_model: model, description: desc.trim() }),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || r.statusText); });
        return r.json();
      })
      .then(function (p) {
        state.currentProject = p;
        renderProjectInfo();
        toast("✓ 项目已创建: " + p.name);
        return p;
      })
      .catch(function (e) { toast("✗ " + e.message, true); return null; });
  }

  function renderProjectInfo() {
    var p = state.currentProject;
    var info = $("fp-project-info");
    if (!info) return;
    function safe(id) { return document.getElementById(id); }
    function show(id, on) { var e = safe(id); if (e) e.style.display = on ? "" : "none"; }
    if (!p) {
      info.innerHTML = "<em>未选择项目 — 在下方项目库中选择或新建</em>";
      show("fp-project-section", false);
      show("fp-dl-kmz", false);
      show("fp-dl-kml", false);
      show("fp-btn-export-kmz", false);
      show("fp-btn-export-kml", false);
      return;
    }
    var missionCount = p.mission_count != null ? p.mission_count
                      : (p.mission_ids ? p.mission_ids.length : 0);
    info.innerHTML =
      "<div class='fp-pi-row'>" +
        "<span class='fp-pi-label'>项目</span>" +
        "<strong>✓ " + escapeHtml(p.name) + "</strong>" +
      "</div>" +
      "<div class='fp-pi-row'>" +
        "<span class='fp-pi-label'>机型</span>" +
        "<span class='fp-pi-badge'>" + escapeHtml(p.drone_model) + "</span>" +
      "</div>" +
      "<div class='fp-pi-row'>" +
        "<span class='fp-pi-label'>航线</span>" +
        "<span>" + missionCount + " 条</span>" +
      "</div>" +
      (p.description ? "<div class='fp-pi-row fp-pi-desc'>" + escapeHtml(p.description) + "</div>" : "") +
      "<div class='fp-pi-row fp-pi-mission-list' id='fp-pi-mission-list'></div>";
    show("fp-project-section", true);
    show("fp-dl-kmz", true);
    show("fp-dl-kml", true);
    var hasMissions = missionCount > 0;
    show("fp-btn-export-kmz", hasMissions);
    show("fp-btn-export-kml", hasMissions);

    // Sync the drone model selector to the project's model
    var sel = safe("fp-drone-model");
    if (sel && p.drone_model && sel.value !== p.drone_model) {
      // Only set if the option exists (drone_models endpoint populates this)
      var exists = false;
      for (var i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === p.drone_model) { exists = true; break; }
      }
      if (exists) sel.value = p.drone_model;
    }

    // Load the mission list for this project (if there are any)
    if (hasMissions) {
      loadProjectMissionList(p.id);
    } else {
      var ms = safe("fp-pi-mission-list");
      if (ms) ms.innerHTML = "<em class='fp-empty-hint'>尚无航线，点下方按钮或在地图上生成</em>";
    }
  }

  // -----------------------------------------------------------------
  // Project list — fetches /projects/ and renders rows in the sidebar.
  // Each row click selects the project, the X button deletes it.
  // -----------------------------------------------------------------
  function loadProjectList() {
    var list = $("fp-project-list");
    if (!list) return;
    fetch(realApi("projects/"), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        state.allProjects = d.projects || [];
        renderProjectList();
      })
      .catch(function (e) {
        if (list) list.innerHTML = "<div class='fp-list-empty'>✗ 加载失败：" + escapeHtml(String(e)) + "</div>";
      });
  }

  function renderProjectList() {
    var list = $("fp-project-list");
    var badge = $("fp-project-count");
    if (!list) return;
    var projects = state.allProjects || [];
    if (badge) badge.textContent = projects.length;
    if (projects.length === 0) {
      list.innerHTML = "<div class='fp-list-empty'>尚无项目，点上方「+ 新项目」创建</div>";
      return;
    }
    var html = "";
    for (var i = 0; i < projects.length; i++) {
      var p = projects[i];
      var active = state.currentProject && state.currentProject.id === p.id;
      var ts = p.updated_at || p.created_at || "";
      if (ts && ts.length > 16) ts = ts.slice(0, 16).replace("T", " ");
      html +=
        "<div class='fp-project-row" + (active ? " active" : "") + "' data-pid='" + p.id + "'>" +
          "<div class='fp-project-main'>" +
            "<div class='fp-project-name'>" + escapeHtml(p.name) + "</div>" +
            "<div class='fp-project-meta'>" +
              "<span class='fp-pi-badge'>" + escapeHtml(p.drone_model) + "</span>" +
              "<span>· " + (p.mission_count || 0) + " 航线</span>" +
              (ts ? "<span>· " + escapeHtml(ts) + "</span>" : "") +
            "</div>" +
          "</div>" +
          "<button class='fp-project-del' data-del='" + p.id + "' title='删除项目'>×</button>" +
        "</div>";
    }
    list.innerHTML = html;
  }

  function selectProject(pid) {
    fetch(realApi("projects/" + pid + "/"), { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (p) {
        state.currentProject = p;
        renderProjectInfo();
        renderProjectList();
        toast("✓ 已选择项目: " + p.name);
      })
      .catch(function (e) { toast("✗ 加载项目失败: " + e.message, true); });
  }

  function deleteProject(pid, name) {
    if (!window.confirm("确定要删除项目 \"" + name + "\" 吗？\n该项目下的所有航线将一并删除。")) return;
    var csrf = getCookie("csrftoken");
    fetch(realApi("projects/" + pid + "/"), {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf, "Referer": window.location.origin },
    })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        if (state.currentProject && state.currentProject.id === pid) {
          state.currentProject = null;
          renderProjectInfo();
        }
        toast("✓ 项目已删除");
        loadProjectList();
      })
      .catch(function (e) { toast("✗ 删除失败: " + e.message, true); });
  }

  // -----------------------------------------------------------------
  // Project mission list — when a project is selected, fetch its missions
  // and render inline rows with a "load to map" button.
  // -----------------------------------------------------------------
  function loadProjectMissionList(pid) {
    var box = $("fp-pi-mission-list");
    if (!box) return;
    fetch(realApi("missions/?project=" + encodeURIComponent(pid)), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var ms = d.missions || [];
        if (ms.length === 0) {
          box.innerHTML = "<em class='fp-empty-hint'>尚无航线</em>";
          return;
        }
        var html = "<div class='fp-pi-mlist-title'>已添加航线：</div>";
        for (var i = 0; i < ms.length; i++) {
          var m = ms[i];
          html +=
            "<div class='fp-mission-row' data-mid='" + m.id + "'>" +
              "<div class='fp-mission-main'>" +
                "<div class='fp-mission-name'>" + escapeHtml(m.name) + "</div>" +
                "<div class='fp-mission-meta'>" +
                  "<span class='fp-pi-badge fp-pi-badge-kind'>" + escapeHtml(m.kind) + "</span>" +
                  "<span>" + (m.waypoints || 0) + " 航点</span>" +
                "</div>" +
              "</div>" +
              "<div class='fp-mission-actions'>" +
                "<button class='fp-btn fp-btn-sm fp-mission-load' data-load='" + m.id + "' title='加载到地图查看'>查看</button>" +
                "<button class='fp-btn fp-btn-sm fp-mission-del' data-mdel='" + m.id + "' title='从项目中移除'>×</button>" +
              "</div>" +
            "</div>";
        }
        box.innerHTML = html;
      })
      .catch(function (e) {
        box.innerHTML = "<em class='fp-empty-hint'>✗ 加载航线失败: " + escapeHtml(String(e)) + "</em>";
      });
  }

  function loadMissionOnMap(mid) {
    log("[loadMissionOnMap] ENTRY, mid=" + mid + " state.map=" + !!state.map);
    fetch(realApi("mission/" + mid + "/"), { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (m) {
        if (!state.map) { toast("✗ 地图未就绪", true); return; }
        // Clear current drawing + push the mission's waypoints back to the map.
        // OLMap.addMarker takes a payload {id, lat, lng, label, ...} — not
        // (lat, lng, opts) like the local addPoint().
        if (state.map.clearOverlays) state.map.clearOverlays();
        state.points = [];
        state.markers = [];
        // We're now editing a server-stored mission — track it so the
        // waypoint editor exposes a "保存到服务器" button.
        state.editingMissionId = m.id;
        state.editingMissionDirty = false;
        if (Array.isArray(m.waypoints)) {
          for (var i = 0; i < m.waypoints.length; i++) {
            var w = m.waypoints[i];
            var payload = {
              id: w.id || ("load_" + i),
              lat: w.lat, lng: w.lng,
              label: "#" + (i + 1),
              color: "#4ade80",
              // Snapshot of the DB row at load time — used as fallback in
              // wpEditSave if the user didn't touch a field.
              wp: {
                alt: w.alt, speed: w.speed, gimbal_pitch: w.gimbal_pitch,
                heading: w.heading, heading_mode: w.heading_mode,
                action: w.action, hold_time: w.hold_time,
                action_pitch: w.action_pitch, focal_length: w.focal_length,
                focus_x: w.focus_x, focus_y: w.focus_y,
                hyperlateral: w.hyperlateral, hypervertical: w.hypervertical,
                curve_radius: w.curve_radius, rotate_time: w.rotate_time,
              },
            };
            state.map.addMarker(payload);
            state.markers.push(payload);
            state.points.push([w.lat, w.lng]);
          }
          log("[loadMissionOnMap] pushed " + state.markers.length + " markers, mid=" + m.id);
          var lineCoords = m.waypoints.map(function (w) { return [w.lng, w.lat]; });
          if (state.map.upsertLine) {
            state.map.upsertLine("loaded-mission", { coords: lineCoords, color: "#4ade80", weight: 2, dash: "4 4" });
          }
        }
        // Render the editor's save-state (button visible now, dirty hint hidden)
        updateEditorSaveState();
        toast("✓ 航线已加载 (" + (m.waypoints ? m.waypoints.length : 0) + " 航点) — 可点击航点编辑");
        // Fly to bounds if available. fitBounds expects [{lat, lng}, ...]
        if (Array.isArray(m.bounds) && m.bounds.length === 4 && state.map.fitBounds) {
          state.map.fitBounds([
            { lat: m.bounds[0], lng: m.bounds[1] },
            { lat: m.bounds[2], lng: m.bounds[3] },
          ], 40);
        }
      })
      .catch(function (e) { toast("✗ 加载失败: " + e.message, true); });
  }

  function removeMissionFromProject(mid) {
    if (!state.currentProject) return;
    var csrf = getCookie("csrftoken");
    var body = { mission_ids: [] };
    // Build list of remaining mission_ids
    fetch(realApi("projects/" + state.currentProject.id + "/"), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (p) {
        var remaining = (p.mission_ids || []).filter(function (x) { return x !== mid; });
        body.mission_ids = remaining;
        return fetch(realApi("projects/" + state.currentProject.id + "/"), {
          method: "PUT",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, "Referer": window.location.origin },
          body: JSON.stringify(body),
        });
      })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function () {
        toast("✓ 已从项目中移除");
        selectProject(state.currentProject.id);
        loadProjectList();
      })
      .catch(function (e) { toast("✗ 移除失败: " + e.message, true); });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  // -----------------------------------------------------------------
  // Waypoint editor — populates the side panel from a selected marker
  // payload and applies changes back to the marker + state.points.
  // -----------------------------------------------------------------
  function wpEditSelect(payload) {
    if (!payload) {
      state.selectedWp = null;
      wpEditClose();
      return;
    }
    // The payload passed in is the OL feature's __payload snapshot
    // (a *copy* of the original marker object, not the same reference).
    // We need to write back edits to the actual state.markers entry,
    // otherwise wpEditSave sees the original values. Look up the live
    // marker by id and use that as state.selectedWp.
    var live = null;
    if (state.markers && state.markers.length) {
      for (var i = 0; i < state.markers.length; i++) {
        if (state.markers[i] && state.markers[i].id === payload.id) {
          live = state.markers[i];
          break;
        }
      }
    }
    // Fall back to the snapshot if no live marker is found (shouldn't
    // happen for loaded missions or freshly drawn points, but keeps
    // things robust).
    state.selectedWp = live || payload;
    var editor = $("fp-waypoint-editor");
    if (!editor) return;
    editor.style.display = "";
    $("fp-wp-editor-label").textContent = state.selectedWp.label || "POI";
    $("fp-wp-alt").value     = state.selectedWp.alt != null ? state.selectedWp.alt : 60;
    $("fp-wp-speed").value   = state.selectedWp.speed != null ? state.selectedWp.speed : 5;
    $("fp-wp-gimbal").value  = state.selectedWp.gimbal_pitch != null ? state.selectedWp.gimbal_pitch : -90;
    $("fp-wp-heading").value = state.selectedWp.heading != null ? state.selectedWp.heading : "";
    $("fp-wp-headmode").value = state.selectedWp.heading_mode || "";
    $("fp-wp-action").value  = state.selectedWp.action || "photo";
    $("fp-wp-hold").value    = state.selectedWp.hold_time || 0;
    $("fp-wp-curve").value   = state.selectedWp.curve_radius || 0;
    $("fp-wp-actionpitch").value = state.selectedWp.action_pitch != null ? state.selectedWp.action_pitch : "";
    $("fp-wp-rotatetime").value  = state.selectedWp.rotate_time || 2;
    $("fp-wp-focal").value       = state.selectedWp.focal_length || 24;
    $("fp-wp-focusx").value      = state.selectedWp.focus_x != null ? state.selectedWp.focus_x : 0.5;
    $("fp-wp-focusy").value      = state.selectedWp.focus_y != null ? state.selectedWp.focus_y : 0.5;
    $("fp-wp-hyperlat").checked  = !!state.selectedWp.hyperlateral;
    $("fp-wp-hypervert").checked = !!state.selectedWp.hypervertical;
    $("fp-wp-coord").textContent =
      "lat " + state.selectedWp.lat.toFixed(6) + " · lon " + state.selectedWp.lng.toFixed(6);
  }

  function wpEditApply() {
    var p = state.selectedWp;
    if (!p) return;
    p.alt          = parseFloat($("fp-wp-alt").value);
    p.speed        = parseFloat($("fp-wp-speed").value);
    p.gimbal_pitch = parseInt($("fp-wp-gimbal").value, 10);
    var h = $("fp-wp-heading").value;
    p.heading      = (h === "" || h == null) ? null : parseFloat(h);
    var hm = $("fp-wp-headmode").value;
    p.heading_mode = (hm === "" || hm == null) ? null : hm;
    p.action       = $("fp-wp-action").value;
    p.hold_time    = parseFloat($("fp-wp-hold").value) || 0;
    p.curve_radius = parseFloat($("fp-wp-curve").value) || 0;
    var ap = $("fp-wp-actionpitch").value;
    p.action_pitch = (ap === "" || ap == null) ? null : parseFloat(ap);
    p.rotate_time  = parseFloat($("fp-wp-rotatetime").value) || 2;
    p.focal_length = parseFloat($("fp-wp-focal").value) || 24;
    p.focus_x      = parseFloat($("fp-wp-focusx").value);
    p.focus_y      = parseFloat($("fp-wp-focusy").value);
    p.hyperlateral   = $("fp-wp-hyperlat").checked  ? 1 : 0;
    p.hypervertical  = $("fp-wp-hypervert").checked ? 1 : 0;
    if (state.map) state.map.updateMarker(p);
    // If we're editing a loaded (server-stored) mission, mark dirty so
    // the "保存到服务器" button becomes live.
    if (state.editingMissionId) {
      state.editingMissionDirty = true;
      updateEditorSaveState();
    }
    toast("✓ 航点参数已更新");
  }

  // Bulk apply the form values (except lat/lng) to every waypoint in
  // state.markers. Useful for "set speed=8 m/s on all 100 survey points"
  // style edits after a mission is loaded.
  function wpEditApplyAll() {
    if (!state.selectedWp) { toast("✗ 请先选中一个航点", true); return; }
    // First, run the normal apply so the form values are on state.selectedWp
    wpEditApply();
    var src = state.selectedWp;
    if (!state.markers || !state.markers.length) return;
    var n = 0;
    for (var i = 0; i < state.markers.length; i++) {
      var m = state.markers[i];
      if (!m || m === src) continue;
      m.alt          = src.alt;
      m.speed        = src.speed;
      m.gimbal_pitch = src.gimbal_pitch;
      m.heading      = src.heading;
      m.heading_mode = src.heading_mode;
      m.action       = src.action;
      m.hold_time    = src.hold_time;
      m.curve_radius = src.curve_radius;
      m.action_pitch = src.action_pitch;
      m.rotate_time  = src.rotate_time;
      m.focal_length = src.focal_length;
      m.focus_x      = src.focus_x;
      m.focus_y      = src.focus_y;
      m.hyperlateral  = src.hyperlateral;
      m.hypervertical = src.hypervertical;
      if (state.map) state.map.updateMarker(m);
      n++;
    }
    if (state.editingMissionId) {
      state.editingMissionDirty = true;
      updateEditorSaveState();
    }
    toast("✓ 已应用到全部 " + n + " 个航点");
  }

  // Show / hide the "保存到服务器" button + dirty hint based on state.
  // Visible when: editingMissionId is set AND editingMissionDirty is true.
  function updateEditorSaveState() {
    var saveBtn = $("fp-wp-save-server");
    var hint = $("fp-wp-dirty-hint");
    if (!saveBtn) return;
    var visible = !!state.editingMissionId;
    saveBtn.style.display = visible ? "" : "none";
    if (hint) hint.style.display = (visible && state.editingMissionDirty) ? "" : "none";
  }

  // Push all current state.markers (with their updated lat/lng/alt/...) up
  // to the server as the new waypoints list for the loaded mission.
  function wpEditSave() {
    if (!state.editingMissionId) {
      toast("✗ 没有正在编辑的航线", true);
      return;
    }
    if (!state.editingMissionDirty) {
      toast("✓ 没有修改，无需保存");
      return;
    }
    var mid = state.editingMissionId;
    log("[wpEditSave] state.markers.length=" + state.markers.length + " dirty=" + state.editingMissionDirty + " mid=" + mid);
    // Build the new waypoints array in the same shape the algorithm
    // produces. state.markers holds the OLMap payload objects; each has
    // id, lat, lng, label, wp (original), and mutated fields.
    var wps = state.markers
      .filter(function (m) { return m && typeof m.lat === "number" && typeof m.lng === "number"; })
      .map(function (m, idx) {
        var src = m.wp || {};
        function pick(k, fallback) {
          if (m[k] != null) return m[k];
          if (src[k] != null) return src[k];
          return fallback;
        }
        return {
          index: idx,
          lat: m.lat,
          lng: m.lng,
          alt:          pick("alt", 60),
          speed:        pick("speed", 5),
          gimbal_pitch: pick("gimbal_pitch", -90),
          heading:      pick("heading", null),
          heading_mode: pick("heading_mode", null),
          action:       m.action || src.action || "photo",
          hold_time:    pick("hold_time", 0),
          curve_radius: pick("curve_radius", 0),
          action_pitch: m.action_pitch != null ? m.action_pitch : (src.action_pitch != null ? src.action_pitch : null),
          rotate_time:  pick("rotate_time", 2),
          focal_length: pick("focal_length", 24),
          focus_x:      pick("focus_x", 0.5),
          focus_y:      pick("focus_y", 0.5),
          hyperlateral:  m.hyperlateral  != null ? m.hyperlateral  : (src.hyperlateral  != null ? src.hyperlateral  : 0),
          hypervertical: m.hypervertical != null ? m.hypervertical : (src.hypervertical != null ? src.hypervertical : 0),
        };
      });

    if (wps.length === 0) {
      toast("✗ 没有航点可保存", true);
      return;
    }

    var saveBtn = $("fp-wp-save-server");
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = "保存中…";
    }
    var csrf = getCookie("csrftoken");
    fetch(realApi("mission/" + mid + "/"), {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, "Referer": window.location.origin },
      body: JSON.stringify({ waypoints: wps }),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || ("HTTP " + r.status)); });
        return r.json();
      })
      .then(function (m) {
        state.editingMissionDirty = false;
        updateEditorSaveState();
        // Refresh the connected project's mission list so other places
        // (e.g. project info) reflect the new state.
        if (state.currentProject) loadProjectMissionList(state.currentProject.id);
        toast("✓ 航线已保存到服务器 (" + wps.length + " 航点)");
      })
      .catch(function (e) {
        toast("✗ 保存失败: " + e.message, true);
      })
      .then(function () {
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.textContent = "保存到服务器";
        }
      });
  }

  function wpEditDelete() {
    var p = state.selectedWp;
    if (!p) return;
    // Remove from state.points / state.markers, then from the map.
    var idx = state.points.findIndex(function (pt) {
      // Match by closest lat/lng (since state.points is [lat, lng] pairs)
      return Math.abs(pt[0] - p.lat) < 1e-7 && Math.abs(pt[1] - p.lng) < 1e-7;
    });
    if (idx >= 0) state.points.splice(idx, 1);
    var mi = state.markers.findIndex(function (m) { return m.id === p.id; });
    if (mi >= 0) state.markers.splice(mi, 1);
    if (state.map) state.map.removeMarker(p.id);
    // If we're editing a server-stored mission, deleting a waypoint is
    // a modification — mark dirty.
    if (state.editingMissionId) {
      state.editingMissionDirty = true;
      updateEditorSaveState();
    }
    wpEditClose();
    redrawDrawingLines();
    checkGenerateReady();
    toast("✓ 航点已删除");
  }

  function wpEditClose() {
    state.selectedWp = null;
    var editor = $("fp-waypoint-editor");
    if (editor) editor.style.display = "none";
    if (state.map && state.map._select) state.map._select.getFeatures().clear();
  }

  // After deleting a waypoint, redraw the polyline (drawing line) using
  // the remaining state.points.
  function redrawDrawingLines() {
    if (!state.map) return;
    // Remove any existing drawing lines (those that aren't the flight path)
    state.map._polylineFeats = (state.map._polylineFeats || []).filter(function (feat) {
      var id = feat.get("__id") || "";
      if (id.indexOf("fp-line-draw") === 0) {
        state.map._vectorSource.removeFeature(feat);
        return false;
      }
      return true;
    });
    if (state.points.length < 2) return;
    var isPOI = (state.mode === "orbit" || state.mode === "spiral" || state.mode === "corkscrew");
    if (isPOI) return;
    var coords = state.points.map(function (p) { return [p[1], p[0]]; });
    var lineFeat = new ol.Feature({ geometry: new ol.geom.LineString(coords) });
    lineFeat.set("__id", "fp-line-draw");
    lineFeat.set("__style", new ol.style.Style({
      stroke: new ol.style.Stroke({ color: "#4ade80", width: 2, lineDash: [4, 4] }),
    }));
    state.map._vectorSource.addFeature(lineFeat);
    state.map._polylineFeats.push(lineFeat);
  }

  function addMissionToCurrentProject() {
    if (!state.currentProject) {
      toast("✗ 请先创建项目", true);
      return;
    }
    if (!state.lastMission) {
      toast("✗ 请先生成航线", true);
      return;
    }
    var pid = state.currentProject.id;
    var mid = state.lastMission.id;
    fetch(realApi("projects/" + pid + "/add-mission/"), {
      method: "POST",
      headers: apiHeaders(),
      credentials: "same-origin",
      body: JSON.stringify({ mission_id: mid }),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || r.statusText); });
        return r.json();
      })
      .then(function (p) {
        state.currentProject = p;
        renderProjectInfo();
        toast("✓ 已加入项目 (" + p.mission_ids.length + " 条)");
      })
      .catch(function (e) { toast("✗ " + e.message, true); });
  }

  function exportProjectKmz() {
    if (!state.currentProject || !state.currentProject.id) {
      toast("✗ 请先创建项目", true); return;
    }
    if (!state.currentProject.mission_ids || state.currentProject.mission_ids.length === 0) {
      toast("✗ 项目内还没有航线", true); return;
    }
    var url = realApi("projects/" + state.currentProject.id + "/export.kmz");
    window.location.href = url;
    toast("✓ 开始下载 KMZ (大疆 " + state.currentProject.drone_model + " 格式)");
  }

  function exportProjectKml() {
    if (!state.currentProject || !state.currentProject.id) return;
    var url = realApi("projects/" + state.currentProject.id + "/export.kml");
    window.location.href = url;
    toast("✓ 开始下载 KML (通用格式)");
  }

  // -------------------------------------------------------------------------
  // Map navigation (go-to-coords, fit-world, fit-bounds)
  // -------------------------------------------------------------------------

  function gotoCoords() {
    if (!state.map) return;
    var lat = parseFloat($("fp-nav-lat").value);
    var lng = parseFloat($("fp-nav-lng").value);
    if (isNaN(lat) || isNaN(lng)) { toast("✗ 经纬度格式错误", true); return; }
    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) { toast("✗ 经纬度超出范围", true); return; }
    state.map.setView(lat, lng, 16);
    setStatus("✓ 跳转到 (" + lat.toFixed(6) + ", " + lng.toFixed(6) + ")", "");
  }

  function fitWorld() {
    if (!state.map) return;
    state.map.setView(20, 0, 1);
    setStatus("已切换到全球视图", "");
  }

  function fitLastMission() {
    if (!state.map) return;
    if (!state.lastMission || !state.lastMission.waypoints || !state.lastMission.waypoints.length) {
      toast("✗ 还没有航线可以定位", true);
      return;
    }
    var latLngs = state.lastMission.waypoints.map(function (w) { return { lat: w.lat, lng: w.lon }; });
    state.map.fitBounds(latLngs, 40);
    setStatus("✓ 已定位到当前航线", "");
  }

  function drawFlightPath(m) {
    if (!state.map) return;
    clearDrawing();
    var latlngs = m.waypoints.map(function (w) { return [w.lat, w.lon]; });
    if (!latlngs.length) return;

    // Connecting line
    var lineId = "fp-line-flight";
    state.map.upsertLine(lineId, {
      coords: latlngs,
      color: "#4ade80",
      width: 2,
      dash: [3, 3],
    });
    state.polylines.push(lineId);

    // Direction arrows along the route
    if (latlngs.length >= 2) {
      var arrowStep = Math.max(1, Math.floor(latlngs.length / 8));
      for (var i = 0; i + 1 < latlngs.length; i += arrowStep) {
        var p = latlngs[i], q = latlngs[i + 1];
        var mid = { lat: (p[0] + q[0]) / 2, lng: (p[1] + q[1]) / 2 };
        var m1 = { lat: mid.lat, lng: mid.lng, color: "#fbbf24", radius: 5, weight: 2, label: "" };
        state.map.addMarker(m1);
        state.markers.push(m1);
      }
    }

    // Plot waypoints
    var labelStep = Math.max(1, Math.floor(latlngs.length / 30));
    latlngs.forEach(function (p, i) {
      var isFirst = i === 0;
      var isLast = i === latlngs.length - 1;
      var color = isFirst ? "#fbbf24" : (isLast ? "#f87171" : "#4ade80");
      var radius = isFirst || isLast ? 7 : 4;
      var lbl = "";
      if (i % labelStep === 0 || isFirst || isLast) {
        lbl = isFirst ? "起点" : (isLast ? "终点" : ("#" + (i + 1)));
      }
      var m2 = { lat: p[0], lng: p[1], color: color, radius: radius, weight: 2, label: lbl };
      state.map.addMarker(m2);
      state.markers.push(m2);
    });

    // Fit to bounds
    setTimeout(function () {
      if (!state.map) return;
      var ll = latlngs.map(function (p) { return { lat: p[0], lng: p[1] }; });
      state.map.fitBounds(ll, 50);
      if (state.updateScaleBar) state.updateScaleBar();
    }, 50);
  }

  // Tile sources — pure XYZ raster tiles. No API key needed.
  // Each source has: id, name, url (with {x}/{y}/{z}/{s} placeholders), maxZoom, attribution.
  function buildSources() {
    return [
      {
        id: "gaode_img",
        name: "高德卫星影像 (国内)",
        url: "https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
        subdomains: ["1", "2", "3", "4"],
        maxZoom: 18,
        attribution: "© 高德地图",
      },
      {
        id: "gaode_vec",
        name: "高德矢量 (国内)",
        url: "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
        subdomains: ["1", "2", "3", "4"],
        maxZoom: 18,
        attribution: "© 高德地图",
      },
      {
        id: "esri_img",
        name: "Esri 卫星 (全球)",
        url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        subdomains: [],
        maxZoom: 19,
        attribution: "© Esri",
      },
      {
        id: "osm",
        name: "OpenStreetMap (全球)",
        url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        subdomains: [],
        maxZoom: 19,
        attribution: "© OpenStreetMap",
      },
    ];
  }

  function changeBasemap() {
    if (!state.map) return;
    var sel = $("fp-basemap-sel");
    if (!sel) return;
    var name = sel.value;
    if (!name) return;
    var sources = buildSources();
    var spec = null;
    for (var i = 0; i < sources.length; i++) { if (sources[i].name === name) { spec = sources[i]; break; } }
    if (!spec) return;
    state.map.setSource(name, spec);
    state.activeBasemap = name;
    setStatus("✓ 已切换到 " + name, "");
  }

  // Force a complete re-tile.
  function refreshMap() {
    if (!state.map) return;
    setStatus("⟳ 重新加载瓦片...", "warn");
    if (state.map.updateSize) state.map.updateSize();
    setStatus("✓ 瓦片已重新加载", "");
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("Failed to load " + src)); };
      document.head.appendChild(s);
    });
  }

  function loadCss(href) {
    var l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    document.head.appendChild(l);
  }

  // Try CDN first, fall back to local copy. We ship a local copy of ol.js
  // and ol.css so the plugin works on networks that block jsDelivr.
  function loadOL() {
    if (window.ol) return Promise.resolve();
    loadCss(PLUGIN_BASE + "ol.css");
    return loadScript("https://cdn.jsdelivr.net/npm/ol@9.2.4/dist/ol.js")
      .catch(function () { return loadScript(PLUGIN_BASE + "ol.js"); });
  }

  // Public entry: WebODM's React wrapper calls this once the React tree
  // has been mounted (via build/app.js → componentDidMount). We also call
  // ourselves on DOMContentLoaded as a fallback for direct page loads.
  function init(opts) {
    opts = opts || {};
    function log(msg, err) {
      // Always surface init progress to the page so blank-page bugs are
      // easy to diagnose. The mount element is set after this in opts;
      // before that, fall back to body.
      try {
        var el = document.createElement("div");
        el.id = "fp-debug-log";
        el.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:99999;background:#1a1d24;color:#fbbf24;font:11px monospace;padding:6px 10px;border-bottom:1px solid #fbbf24;max-height:200px;overflow:auto;";
        (opts.mountEl || document.body).appendChild(el);
        var line = document.createElement("div");
        line.textContent = "[fp " + new Date().toISOString().slice(11, 19) + "] " + msg + (err ? " — " + (err.message || err) : "");
        if (err) line.style.color = "#f87171";
        el.appendChild(line);
        console.log("[fp]", msg, err || "");
      } catch (e) {}
    }
    log("init() called, mountEl=" + (opts.mountEl ? (opts.mountEl.id || "(no-id)") : "none"));
    // Inject our app stylesheet exactly once. CSS lives alongside main.js
    // so we can ship the whole UI without relying on WebODM's
    // include_css_files() (which loads at body-bottom, sometimes too late).
    if (!document.getElementById("fp-app-css")) {
      var l = document.createElement("link");
      l.rel = "stylesheet";
      l.href = PLUGIN_BASE + "app.css";
      l.id = "fp-app-css";
      document.head.appendChild(l);
      log("app.css injected");
    }
    log("loading OL...");
    loadOL().then(function () {
      log("OL loaded");
      // Mount container: either a provided element (from React wrapper)
      // or our default #fp-map div.
      var mountEl = opts.mountEl || $("fp-map");
      // If the container is the React wrapper mount div, it lives inside
      // a parent with no fixed height, so its own height:100% resolves to
      // 0. Force a viewport-relative size for the entire flight-planner
      // shell so the sidebar + map can lay out.
      if (mountEl && mountEl.id === "fp-app-mount") {
        mountEl.style.position = "relative";
        mountEl.style.width = "100%";
        mountEl.style.height = "calc(100vh - 60px)"; // leave room for the navbar
        mountEl.style.minHeight = "500px";
      }
      function waitForContainer(attempts) {
        if (!mountEl) mountEl = (opts.mountEl) || $("fp-map") || document.getElementById("fp-map");
        if (!mountEl) {
          if (attempts <= 0) return Promise.reject("no #fp-map and no mountEl");
          return new Promise(function (resolve) {
            setTimeout(function () { resolve(waitForContainer(attempts - 1)); }, 100);
          });
        }
        var w = mountEl.offsetWidth || mountEl.clientWidth, h = mountEl.offsetHeight || mountEl.clientHeight;
        log("mountEl " + mountEl.id + " = " + w + "x" + h);
        if (w > 100 && h > 100) return Promise.resolve();
        if (attempts <= 0) return Promise.reject("container never got size");
        return new Promise(function (resolve) {
          setTimeout(function () { resolve(waitForContainer(attempts - 1)); }, 100);
        });
      }
      waitForContainer(40).then(function () { log("container ready, initMap()"); return initMap(mountEl); })
        .catch(function (err) {
          log("init failed", err);
          // Don't blow up the page if there's no container — WebODM
          // may simply not have loaded the React wrapper yet.
        });
    }).catch(function (err) {
      log("OL load failed", err);
    });
  }
  // Expose for the React wrapper to call.
  window.flightPlannerInit = init;

  function initMap(mountEl) {
    // mountEl is the container that should hold our full UI. When called
    // from the React wrapper, it's the #fp-app-mount div that React
    // rendered. We render the complete app shell (sidebar + map) into it.
    var outer = mountEl || $("fp-map");
    if (!outer) { console.error("no mount element"); return; }
    // If the React wrapper rendered a <div id="fp-app-mount"> with no
    // children, replace it with our full UI. If outer IS the legacy
    // #fp-map, leave it (no sidebar — caller will see the same as before).
    if (outer.id !== "fp-map") {
      outer.innerHTML = APP_HTML;
      outer.classList.add("fp-app");
      // Bind DOM listeners that don't depend on the OLMap instance.
      bindUIEvents();
    }

    var mapEl = $("fp-map");
    if (!mapEl) { console.error("no #fp-map after UI hydration"); return; }
    var startName = ($("fp-basemap-sel") || {}).value || "高德卫星影像 (国内)";
    state.activeBasemap = startName;
    state.failedTiles = 0;

    var sources = buildSources();
    var startSpec = sources[0];
    for (var i = 0; i < sources.length; i++) { if (sources[i].name === startName) { startSpec = sources[i]; break; } }

    state.map = new OLMap(mapEl);
    state.map.setSource(startName, startSpec);
    state.map.setView(22.5, 113.9, 10);
    // Now that state.map exists, register map-dependent listeners
    // (waypoint:select / waypoint:move / etc.).
    if (state.map && state.map.on) {
      state.map.on("waypoint:select", function (payload) { wpEditSelect(payload); });
      state.map.on("waypoint:deselect", function () { wpEditSelect(null); });
      state.map.on("waypoint:move", function (payload) {
        if (!payload) return;
        // Mirror the moved position into state.points (for new-drawing flow)
        // and state.markers (for both flows; loaded-mission markers also
        // live there).
        var idx = state.points.findIndex(function (pt) {
          return Math.abs(pt[0] - payload.lat) < 1e-7 && Math.abs(pt[1] - payload.lng) < 1e-7;
        });
        if (idx >= 0) state.points[idx] = [payload.lat, payload.lng];
        var mi = state.markers.findIndex(function (m) { return m.id === payload.id; });
        if (mi >= 0) {
          state.markers[mi].lat = payload.lat;
          state.markers[mi].lng = payload.lng;
        }
        // Side-panel lat/lng display should follow if it's the
        // currently-selected waypoint.
        if (state.selectedWp && state.selectedWp.id === payload.id) {
          var coord = $("fp-wp-coord");
          if (coord) coord.textContent =
            "lat " + payload.lat.toFixed(6) + " · lon " + payload.lng.toFixed(6);
        }
        // Mark the loaded mission dirty so the save button lights up.
        if (state.editingMissionId) {
          state.editingMissionDirty = true;
          updateEditorSaveState();
        }
        redrawDrawingLines();
      });
    }
    // Defer one tick so OL has a chance to measure the container.
    setTimeout(function () { state.map.updateSize(); }, 0);

    // ----------------------------------------------------------------
    // Custom floating scale bar. Uses OL's view.getResolution() to
    // convert pixels to ground meters.
    // ----------------------------------------------------------------
    function updateScaleBar() {
      if (!state.map) return;
      var bar = $("fp-scale");
      if (!bar) return;
      var olMap = state.map._map;
      var view = olMap.getView();
      var res = view.getResolution();   // meters per pixel at center
      if (!res || !isFinite(res)) return;
      var distM = 60 * res;             // 60px wide
      var niceMeters = niceScale(distM);
      var label = formatScale(niceMeters);
      var lblEl = bar.querySelector(".fp-scale-label");
      if (lblEl) lblEl.textContent = label;
      var barDiv = bar.querySelector(".fp-scale-bar");
      if (barDiv) barDiv.style.width = (60 * (niceMeters / distM)) + "px";
    }
    state.updateScaleBar = updateScaleBar;
    var scaleDiv = document.createElement("div");
    scaleDiv.id = "fp-scale";
    scaleDiv.className = "fp-scale";
    scaleDiv.innerHTML = '<div class="fp-scale-label">—</div><div class="fp-scale-bar"></div>';
    var mapWrap = document.querySelector(".fp-map-wrap");
    if (mapWrap) mapWrap.appendChild(scaleDiv);

    // Custom attribution
    var attrDiv = document.createElement("div");
    attrDiv.id = "fp-attribution";
    attrDiv.className = "fp-attribution";
    attrDiv.innerHTML =
      '底图: <a href="https://www.amap.com/" target="_blank" rel="noopener">高德</a> · ' +
      '<a href="https://www.esri.com/" target="_blank" rel="noopener">Esri</a> · ' +
      '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OSM</a>';
    if (mapWrap) mapWrap.appendChild(attrDiv);

    // Update scale on every move (OL fires "moveend")
    state.map.on("move", updateScaleBar);
    setTimeout(updateScaleBar, 300);

    // Click → addPoint (only when in drawing mode)
    state.map.on("click", function (e) {
      if (!state.drawing) return;
      addPoint(e.latLng.lat, e.latLng.lng);
    });

    // Double click → finish polygon/cable
    state.map.on("dblclick", function (e) {
      if (e && e.originalEvent) {
        try { e.originalEvent.preventDefault(); } catch (ex) {}
      }
      if ((state.mode === "polygon" || state.mode === "cable") && state.points.length >= 2) {
        state.drawing = false;
        toast("✓ 绘制完成，可点击「生成航线」");
        setCursor(false);
      }
    });

    // Window resize
    window.addEventListener("resize", function () {
      if (state.map) {
        if (state.map.updateSize) state.map.updateSize();
        updateScaleBar();
      }
    });

    // Mark drawing-ready
    setTimeout(function () {
      setCursor(true);
      updateScaleBar();
      setStatus("✓ 地图就绪 · 点击地图开始绘制", "");
    }, 400);
  }

  // Tab/button/select event listeners — extracted so we can re-bind
  // them when UI is hydrated from the APP_HTML template string.
  function bindUIEvents() {
    // Helper: confirm-discard if there are unsaved edits to a loaded mission.
    function confirmDiscardIfDirty() {
      if (state.editingMissionId && state.editingMissionDirty) {
        return window.confirm("当前航线有未保存的修改，确定要放弃吗？");
      }
      return true;
    }
    // Helper: clear loaded-mission editing state (when starting a new drawing).
    function clearEditingMission() {
      if (state.editingMissionId) {
        state.editingMissionId = null;
        state.editingMissionDirty = false;
        updateEditorSaveState();
        wpEditClose();
      }
    }

    document.querySelectorAll(".fp-tabs button").forEach(function (b) {
      b.addEventListener("click", function () {
        if (!confirmDiscardIfDirty()) return;
        setMode(b.dataset.mode);
        clearEditingMission();
      });
    });
    $("fp-btn-generate").addEventListener("click", function () {
      // Generating a brand-new flight discards any loaded-mission edits
      // (the new flight replaces the map state entirely).
      if (!confirmDiscardIfDirty()) return;
      clearEditingMission();
      generate();
    });
    $("fp-wpml-trigger").addEventListener("change", function () {
      var row = $("fp-wpml-interval-row");
      if (row) row.style.display = (this.value === "multipleTiming") ? "" : "none";
    });
    $("fp-btn-clear").addEventListener("click", function () {
      if (!confirmDiscardIfDirty()) return;
      state.points = [];
      clearDrawing();
      state.drawing = true;
      $("fp-result-section").style.display = "none";
      state.lastMission = null;
      clearEditingMission();
      checkGenerateReady();
      setStatus("已清空", "");
    });
    $("fp-btn-new-project").addEventListener("click", function () {
      createProject().then(function (p) { if (p) loadProjectList(); });
    });
    $("fp-drone-model").addEventListener("change", onModelChange);
    $("fp-btn-add-to-project").addEventListener("click", addMissionToCurrentProject);
    $("fp-btn-export-kmz").addEventListener("click", exportProjectKmz);
    $("fp-btn-export-kml").addEventListener("click", exportProjectKml);
    $("fp-btn-goto").addEventListener("click", gotoCoords);
    $("fp-btn-fit-world").addEventListener("click", fitWorld);
    $("fp-btn-fit-bounds").addEventListener("click", fitLastMission);
    $("fp-btn-zoom-in").addEventListener("click", function () { state.map && state.map.zoomIn(); });
    $("fp-btn-zoom-out").addEventListener("click", function () { state.map && state.map.zoomOut(); });
    // (no secondary zoom buttons in the current UI)
    $("fp-btn-refresh").addEventListener("click", refreshMap);
    $("fp-basemap-sel").addEventListener("change", changeBasemap);

    // Waypoint editor: button handlers
    $("fp-wp-apply").addEventListener("click", wpEditApply);
    $("fp-wp-apply-all").addEventListener("click", wpEditApplyAll);
    $("fp-wp-save-server").addEventListener("click", wpEditSave);
    $("fp-wp-delete").addEventListener("click", wpEditDelete);
    $("fp-wp-close").addEventListener("click", wpEditClose);

    // Project list — event delegation on the dynamic list
    var projList = $("fp-project-list");
    if (projList) {
      projList.addEventListener("click", function (ev) {
        var t = ev.target;
        if (!t) return;
        // Delete button: find row, get id+name, call deleteProject
        if (t.classList && t.classList.contains("fp-project-del")) {
          var pid = t.getAttribute("data-del");
          var row = t.closest(".fp-project-row");
          var name = row ? row.querySelector(".fp-project-name").textContent : pid;
          deleteProject(pid, name);
          return;
        }
        // Click on the row body (not the × button) selects the project
        var row = t.closest(".fp-project-row");
        if (row) {
          var pid = row.getAttribute("data-pid");
          if (pid) selectProject(pid);
        }
      });
    }

    // Project mission list — event delegation (missions rendered dynamically)
    document.body.addEventListener("click", function (ev) {
      log("[body click] target=" + (ev.target && ev.target.tagName) + " cls=" + (ev.target && ev.target.className));
      var t = ev.target;
      if (!t) return;
      if (t.classList && t.classList.contains("fp-mission-load")) {
        var mid = t.getAttribute("data-load");
        log("[body click] loadMissionOnMap(" + mid + ")");
        if (mid) loadMissionOnMap(mid);
        return;
      }
      if (t.classList && t.classList.contains("fp-mission-del")) {
        var mid2 = t.getAttribute("data-mdel");
        if (mid2) removeMissionFromProject(mid2);
        return;
      }
    });

    // Map event listeners (waypoint:select/deselect/move) are registered
    // in initMap() AFTER state.map is created, because OLMap's select/
    // translate interactions need the map instance to exist.
    $("fp-nav-lat").addEventListener("keydown", function (e) { if (e.key === "Enter") gotoCoords(); });
    $("fp-nav-lng").addEventListener("keydown", function (e) { if (e.key === "Enter") gotoCoords(); });
    setMode("polygon");
    renderProjectInfo();
    loadProjectList();   // populate the sidebar list on first paint
    loadDroneModels();

    // Health check
    fetch(realApi("health"), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (j) { console.log("[flight-planner] API OK:", j); })
      .catch(function (e) { console.warn("[flight-planner] API unreachable:", e); });
  }

  // We do NOT auto-init on DOMContentLoaded: WebODM's React wrapper
  // (build/app.js) calls window.flightPlannerInit() once the React tree
  // is mounted. Auto-init here would race the React mount and double-
  // render. The React wrapper is the single source of truth.
})();
