import React from 'react';
import PropTypes from 'prop-types';
import Storage from 'webodm/classes/Storage';
import L from 'leaflet';
import './ChangedetectPanel.scss';
import ErrorMessage from 'webodm/components/ErrorMessage';
import { _ } from 'webodm/classes/gettext';

/**
 * Change detection panel.
 *
 * Lives inside the map's Changedetect control. Compares the currently
 * shown task (task_after) with a user-selected earlier task (task_before)
 * in the same project.
 *
 * Flow:
 *   1. On mount, fetch the project tasks list (excludes the current one)
 *      AND the project's existing change-pairs list, so users see history.
 *   2. For any QUEUED/RUNNING pair, auto-resume polling — this means
 *      switching pages and coming back never loses track of in-flight work.
 *   3. User picks task_before + thresholds, clicks "Run".
 *   4. POST /api/plugins/changedetect/project/<id>/changedetect/create
 *   5. Poll  /api/plugins/changedetect/changedetect/pair/<id>/status
 *   6. On DONE, GET /api/plugins/changedetect/changedetect/pair/<id>/result/<result_id>/download
 *      for each result layer and overlay as L.geoJSON.
 *   7. User can also click "View" on any past DONE pair to re-render it.
 */
export default class ChangedetectPanel extends React.Component {
  static propTypes = {
    onClose: PropTypes.func.isRequired,
    tasks: PropTypes.array.isRequired,  // all tasks on the current map
    isShowed: PropTypes.bool.isRequired,
    map: PropTypes.object.isRequired,
  }

  constructor(props){
    super(props);

    this.state = {
      // The task currently shown on the map = the "after" task
      currentTask: (props.tasks && props.tasks[0]) || null,
      projectId: null,
      projectTasks: [],  // all tasks in the project, except currentTask
      loadingTasks: true,

      // History: all pairs in this project (newest first)
      pairs: [],
      loadingPairs: true,
      // pairId currently being polled (null if none in flight)
      pollingPairId: null,

      // Form
      taskBefore: '',
      name: '',
      pixelThreshold: parseFloat(Storage.getItem("last_cd_pixel_threshold")) || 0.15,
      pixelMinArea: parseFloat(Storage.getItem("last_cd_pixel_min_area")) || 10,
      dsmMinH: parseFloat(Storage.getItem("last_cd_dsm_min_h")) || 0.5,
      dsmMinArea: parseFloat(Storage.getItem("last_cd_dsm_min_area")) || 25,
      enablePixel: Storage.getItem("last_cd_enable_pixel") !== "false",
      enableDsm: Storage.getItem("last_cd_enable_dsm") !== "false",

      // Run state (for the in-progress run from the form)
      submitting: false,
      pairId: null,
      status: null,
      progress: 0,
      progressStatus: '',
      error: '',
      resultLayers: [],     // [{ layer_type, geojson, layer }, ...]
    };
  }

  componentDidMount(){
    this.loadProjectTasks();
    this.loadPairs();
  }

  componentWillUnmount(){
    if (this.tasksReq) this.tasksReq.abort();
    if (this.pairsReq) this.pairsReq.abort();
    if (this.submitReq) this.submitReq.abort();
    if (this.pollReq) clearTimeout(this.pollReq);
    this.removeAllOverlays();
  }

  loadProjectTasks = () => {
    const { currentTask } = this.state;
    if (!currentTask || !currentTask.project){
      this.setState({ loadingTasks: false, permanentError: _("No project context.") });
      return;
    }
    const projectId = currentTask.project;
    this.setState({ projectId, loadingTasks: true });

    this.tasksReq = $.getJSON(`/api/projects/${projectId}/tasks/`)
      .done(res => {
        // res is paginated; take all results
        const all = (res && res.results) || res || [];
        const others = all
          .filter(t => t.id !== currentTask.id)
          .filter(t => (t.status === 40 || t.status === 30))  // COMPLETED/FAILED ok
          .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        this.setState({ projectTasks: others, loadingTasks: false });
      })
      .fail(() => {
        this.setState({ loadingTasks: false, error: _("Failed to load project tasks.") });
      });
  }

  /**
   * Fetch all change-pairs for the current project. Used to:
   *   - show a history list in the panel
   *   - detect QUEUED/RUNNING pairs (so we can resume polling on mount)
   */
  loadPairs = () => {
    const { projectId, currentTask } = this.state;
    const pid = projectId || (currentTask && currentTask.project);
    if (!pid){
      this.setState({ loadingPairs: false });
      return;
    }
    this.setState({ loadingPairs: true });
    this.pairsReq = $.getJSON(`/api/plugins/changedetect/project/${pid}/changedetect/list`)
      .done(res => {
        const pairs = (res && res.pairs) || [];
        this.setState({ pairs, loadingPairs: false });
        // Resume polling for any in-flight pair
        this.resumePollingIfNeeded(pairs);
        // If the URL has ?cd_pair=<id>, auto-load that pair onto the map
        this.autoLoadFromUrl(pairs);
      })
      .fail(() => {
        this.setState({ loadingPairs: false });
      });
  }

  /**
   * If the page was opened with ?cd_pair=<pairId> (typically after
   * clicking "View" on a project list modal), find that pair and load
   * its result overlays. This is the click-through path:
   *   project list → "变化检测" modal → "查看" button
   *   → /map/project/<id>/?cd_pair=<pid>
   *   → ChangedetectPanel mounts → reads URL → renders overlays.
   * If the pair is still running we just start polling it; if it's
   * DONE we render its result layers right away.
   */
  autoLoadFromUrl = (pairs) => {
    if (this._urlHandled) return;  // run once per mount
    let qp = null;
    try { qp = new URLSearchParams(window.location.search); } catch(e){}
    if (!qp) return;
    const targetId = parseInt(qp.get('cd_pair'), 10);
    if (!targetId) return;
    this._urlHandled = true;
    const target = pairs.find(p => p.id === targetId);
    if (!target){
      // pair not found in current project's list (maybe wrong project)
      return;
    }
    if (target.status === 'DONE'){
      this.viewPair(target);
    } else if (target.status === 'QUEUED' || target.status === 'RUNNING'){
      this.setState({
        pollingPairId: target.id,
        pairId: target.id,
        status: target.status,
        submitting: true,
        progressStatus: _('Resuming...'),
      });
      this.pollStatus(target.id);
    }
  }

  /**
   * Look through the pairs list. If any are QUEUED or RUNNING, start
   * (or resume) polling. This is the "switch pages and come back"
   * guarantee: when the panel remounts after a page change, we re-fetch
   * pairs from the server and automatically reconnect to in-flight work.
   */
  resumePollingIfNeeded = (pairs) => {
    if (this.state.pollingPairId) return; // already polling
    const inflight = pairs.find(p => p.status === 'QUEUED' || p.status === 'RUNNING');
    if (!inflight) return;
    this.setState({
      pollingPairId: inflight.id,
      pairId: inflight.id,
      status: inflight.status,
      submitting: true,
      progressStatus: inflight.status === 'QUEUED' ? _('Queued...') : _('Running...'),
    });
    this.pollStatus(inflight.id);
  }

  saveOptions = () => {
    Storage.setItem("last_cd_pixel_threshold", this.state.pixelThreshold);
    Storage.setItem("last_cd_pixel_min_area", this.state.pixelMinArea);
    Storage.setItem("last_cd_dsm_min_h", this.state.dsmMinH);
    Storage.setItem("last_cd_dsm_min_area", this.state.dsmMinArea);
    Storage.setItem("last_cd_enable_pixel", this.state.enablePixel);
    Storage.setItem("last_cd_enable_dsm", this.state.enableDsm);
  }

  handleChange = (key) => (e) => this.setState({ [key]: e.target.value });
  handleCheck = (key) => (e) => this.setState({ [key]: e.target.checked });

  handleRun = () => {
    const { taskBefore, pixelThreshold, pixelMinArea, dsmMinH, dsmMinArea,
            enablePixel, enableDsm, name, projectId, currentTask } = this.state;
    if (!taskBefore){
      this.setState({ error: _("Pick a task to compare with.") });
      return;
    }
    this.saveOptions();
    this.removeAllOverlays();
    this.setState({ submitting: true, error: '', status: 'QUEUED', progress: 0,
                    progressStatus: _('Submitting...'), resultLayers: [] });

    this.submitReq = $.ajax({
      type: 'POST',
      url: `/api/plugins/changedetect/project/${projectId}/changedetect/create`,
      contentType: 'application/json',
      // WebODM's app_view_handler is NOT csrf_exempt at the URL layer, so
      // POSTs hit Django's CsrfViewMiddleware. jQuery's $.ajax only adds
      // X-CSRFToken for form-urlencoded by default — for application/json
      // we have to set it ourselves. The csrftoken cookie is set by Django
      // on first GET; we read it via the standard helpers.
      beforeSend: (xhr) => {
        const m = document.cookie.match(/csrftoken=([^;]+)/);
        if (m) xhr.setRequestHeader('X-CSRFToken', m[1]);
      },
      data: JSON.stringify({
        task_before: taskBefore,
        task_after: currentTask.id,
        name: name,
        options: {
          pixel_threshold: parseFloat(pixelThreshold),
          pixel_min_area_m2: parseFloat(pixelMinArea),
          dsm_min_h_m: parseFloat(dsmMinH),
          dsm_min_area_m2: parseFloat(dsmMinArea),
          enable_pixel: enablePixel,
          enable_dsm: enableDsm,
        },
      }),
    }).done(result => {
      if (result.error){
        this.setState({ submitting: false, status: 'FAILED', error: result.error });
        return;
      }
      this.setState({
        pairId: result.id,
        pollingPairId: result.id,
        status: 'QUEUED',
        progressStatus: _('Queued...'),
      });
      this.pollStatus(result.id);
      // Refresh the history list so the new row shows up immediately
      this.loadPairs();
    }).fail((xhr) => {
      this.setState({ submitting: false, status: 'FAILED',
                      error: _("Server error: ") + (xhr.responseText || xhr.statusText) });
    });
  }

  /**
   * Poll a specific pair's status. Defaults to whatever pairId is in
   * state. Backs off 1.5s between calls; on DONE it stops and refreshes
   * the history list.
   */
  pollStatus = (pairId) => {
    const pid = pairId || this.state.pollingPairId || this.state.pairId;
    if (!pid) return;
    this.pollReq = setTimeout(() => {
      $.getJSON(`/api/plugins/changedetect/changedetect/pair/${pid}/status`)
        .done(res => {
          this.setState({
            status: res.status,
            progress: res.progress || 0,
            progressStatus: res.progress_status || '',
            error: res.error_message || '',
            resultLayers_meta: res.results || [],
          });
          if (res.status === 'DONE'){
            this.setState({ submitting: false, pollingPairId: null });
            this.fetchResultLayers(pid);
            this.loadPairs();   // refresh history so status badge updates
          } else if (res.status === 'FAILED'){
            this.setState({ submitting: false, pollingPairId: null,
                            error: res.error_message || _("Failed.") });
            this.loadPairs();
          } else {
            this.pollStatus(pid);
          }
        })
        .fail(() => {
          // transient; retry
          this.pollStatus(pid);
        });
    }, 1500);
  }

  fetchResultLayers = (pairId) => {
    const { resultLayers_meta } = this.state;
    if (!resultLayers_meta) return;
    const layers = [];
    let pending = resultLayers_meta.length;
    if (pending === 0) return;
    resultLayers_meta.forEach(meta => {
      $.getJSON(`/api/plugins/changedetect/changedetect/pair/${pairId}/result/${meta.id}/download`)
        .done(geojson => {
          layers.push({ layer_type: meta.layer_type, geojson, stats: meta.stats });
          pending -= 1;
          if (pending === 0) this.renderResultLayers(layers);
        })
        .fail(() => {
          pending -= 1;
          if (pending === 0) this.renderResultLayers(layers);
        });
    });
  }

  /**
   * Re-render the result overlays of a past DONE pair when user clicks
   * "View" on a history row. We don't poll — we just fetch the GeoJSON
   * for each result layer and add it to the map.
   */
  viewPair = (pair) => {
    if (!pair.results || pair.results.length === 0){
      this.setState({ error: _("This pair has no result layers.") });
      return;
    }
    // Remove any previous overlays
    this.removeAllOverlays();
    // Set loading state — user sees the panel show "叠加中..."
    this.setState({
      loadingOverlays: true,
      error: '',
      overlaySummary: null,
      progressStatus: _(`加载 pair #${pair.id} 变化数据…`),
    });
    const layers = [];
    let pending = pair.results.length;
    let failed = 0;
    pair.results.forEach(meta => {
      $.getJSON(`/api/plugins/changedetect/changedetect/pair/${pair.id}/result/${meta.id}/download`)
        .done(geojson => {
          layers.push({ layer_type: meta.layer_type, geojson, stats: meta.stats });
        })
        .fail(() => {
          failed += 1;
        })
        .always(() => {
          pending -= 1;
          if (pending === 0){
            this.renderResultLayers(layers, failed, pair);
          }
        });
    });
  }

  renderResultLayers = (layers, failed = 0, pair = null) => {
    // Remove any previous overlays (we already did removeAllOverlays before)
    const map = this.props.map;
    let totalFeatures = 0;
    let totalArea = 0;
    const newOverlays = layers.map(l => {
      const featCount = (l.geojson && l.geojson.features) ? l.geojson.features.length : 0;
      totalFeatures += featCount;
      // Sum area from feature properties if present
      if (l.geojson && l.geojson.features){
        l.geojson.features.forEach(f => {
          if (f.properties && typeof f.properties.area_m2 === 'number'){
            totalArea += f.properties.area_m2;
          }
        });
      }
      const layer = L.geoJSON(l.geojson, {
        style: () => ({
          color: this.colorForLayer(l.layer_type, 1),
          weight: 2,
          fillColor: this.colorForLayer(l.layer_type, 2),
          fillOpacity: 0.35,
        }),
      });
      layer.addTo(map);
      return { ...l, layer, featCount };
    });
    // If any overlay actually carries features, fit the map to the
    // union of their bounds so the user can see them — and so the
    // PDF screenshot has the change polygons inside the visible area
    // instead of off-screen. Skip if the map is currently being
    // interacted with (e.g. user is panning around).
    //
    // We use a conservative maxZoom: leaflet's fitBounds otherwise zooms
    // all the way in to make the (often small) features fill the view,
    // which makes the underlying orthophoto occupy a tiny corner — not
    // useful in a report. Capping at 19 keeps the orthophoto large and
    // visible while still framing the change polygons.
    try {
      const allBounds = newOverlays.reduce((acc, ov) => {
        if (ov.layer && typeof ov.layer.getBounds === 'function'){
          const b = ov.layer.getBounds();
          if (b && b.isValid()) return acc ? acc.extend(b) : b;
        }
        return acc;
      }, null);
      if (allBounds && allBounds.isValid() && !this._userInteracting){
        map.fitBounds(allBounds, { padding: [40, 40], maxZoom: 19, animate: false });
      }
    } catch(e) { /* non-fatal */ }
    // Build a summary the user can see
    const summary = {
      pairId: pair ? pair.id : null,
      layerCount: newOverlays.length,
      featureCount: totalFeatures,
      totalArea: totalArea,
      failed: failed,
      loadedAt: new Date(),
    };
    this.setState({
      resultLayers: newOverlays,
      loadingOverlays: false,
      overlaySummary: summary,
      progressStatus: '',
    });
    // Fire a top-right toast so the user knows the overlay is on the map
    if (window.CDToast){
      if (failed > 0){
        window.CDToast(`已叠加 pair #${summary.pairId} 变化数据 (${totalFeatures} 个变化区域, ${failed} 个图层失败)`, 'warn');
      } else {
        window.CDToast(`已叠加 pair #${summary.pairId} 变化数据 (${totalFeatures} 个变化区域)`, 'success');
      }
    }
  }

  removeAllOverlays = () => {
    const { resultLayers } = this.state;
    if (!resultLayers) return;
    resultLayers.forEach(l => {
      try { this.props.map.removeLayer(l.layer); } catch(e){}
    });
    this.setState({ resultLayers: [] });
  }

  colorForLayer = (type, shade) => {
    // shade 1 = stroke, 2 = fill
    // Models store layer_type as "pixel" / "dsm" / "dtm" (see ChangeResult
    // model LAYER_* constants). Earlier versions of this method expected
    // "pixel_diff" / "dsm_diff" suffixes, so anything else fell back to
    // the gray default and overlays rendered invisible. We accept both
    // spellings here so old and new pair results both colour correctly.
    const colors = { 'pixel':      shade === 1 ? '#e74c3c' : '#ff6b5b',
                     'pixel_diff': shade === 1 ? '#e74c3c' : '#ff6b5b',
                     'dsm':        shade === 1 ? '#3498db' : '#5dade2',
                     'dsm_diff':   shade === 1 ? '#3498db' : '#5dade2',
                     'dtm':        shade === 1 ? '#2ecc71' : '#58d68d',
                     'dtm_diff':   shade === 1 ? '#2ecc71' : '#58d68d' };
    return colors[type] || (shade === 1 ? '#95a5a6' : '#bdc3c7');
  }

  fmtArea = (m2) => {
    if (m2 == null) return '';
    if (m2 >= 10000) return (m2/10000).toFixed(2) + ' ha';
    return m2.toFixed(1) + ' m²';
  }

  fmtTime = (iso) => {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString(); } catch(e) { return iso; }
  }

  /**
   * Render the history list. Each row shows:
   *   - status badge (color-coded)
   *   - task_before → task_after names
   *   - updated time
   *   - View button (DONE only) / Re-run button (FAILED only)
   */
  renderHistory = () => {
    const { pairs, loadingPairs, pollingPairId } = this.state;
    if (loadingPairs){
      return <div className="cd-history-loading">
        <i className="fa fa-circle-notch fa-spin"/> {_("Loading comparisons...")}
      </div>;
    }
    if (!pairs || pairs.length === 0){
      return <div className="cd-history-empty text-muted">
        <small>{_("No comparisons yet. Pick a task below and click Run.")}</small>
      </div>;
    }
    return <div className="cd-history">
      <div className="cd-history-title">
        <b>{_("Comparisons in this project:")}</b>{' '}
        <span className="badge">{pairs.length}</span>
      </div>
      {pairs.map(p => {
        const statusClass = `cd-status cd-status-${(p.status||'').toLowerCase()}`;
        const isPolling = p.id === pollingPairId;
        return <div key={p.id} className={`cd-history-row ${isPolling ? 'active' : ''}`}>
          <div className="cd-history-row-main">
            <span className={statusClass}>{p.status || '?'}</span>
            <span className="cd-history-name" title={p.name || p.id}>
              {p.name || `Pair #${p.id}`}
            </span>
          </div>
          <div className="cd-history-row-sub">
            <small>
              {p.task_before_name ? p.task_before_name.slice(0,18) : '?'}
              {' → '}
              {p.task_after_name ? p.task_after_name.slice(0,18) : '?'}
              {' · '}
              {this.fmtTime(p.updated_at)}
            </small>
          </div>
          <div className="cd-history-row-actions">
            {p.status === 'DONE' ? <button className="btn btn-xs btn-default"
                onClick={() => this.viewPair(p)} title={_("Show this comparison on the map")}>
              <i className="fa fa-eye"/> {_("View")}
            </button> : null}
            {p.status === 'FAILED' ? <button className="btn btn-xs btn-warning"
                onClick={() => this.rerunPair(p)} title={_("Try again")}>
              <i className="fa fa-refresh"/> {_("Retry")}
            </button> : null}
            {(p.status === 'QUEUED' || p.status === 'RUNNING') ? <span className="text-muted">
              <i className="fa fa-circle-notch fa-spin"/> {_("Running")}
            </span> : null}
          </div>
        </div>;
      })}
    </div>;
  }

  /**
   * Re-run a FAILED pair (or any pair) via the /pair/<id>/run/ endpoint.
   * This preserves the pair's task_before/task_after/options, so the user
   * doesn't have to re-pick tasks. Updates state and resumes polling.
   */
  rerunPair = (pair) => {
    this.removeAllOverlays();
    this.setState({
      submitting: true, error: '',
      status: 'QUEUED', progressStatus: _('Re-running...'),
      pairId: pair.id, pollingPairId: pair.id,
    });
    $.ajax({
      type: 'POST',
      url: `/api/plugins/changedetect/changedetect/pair/${pair.id}/run/`,
      contentType: 'application/json',
      beforeSend: (xhr) => {
        const m = document.cookie.match(/csrftoken=([^;]+)/);
        if (m) xhr.setRequestHeader('X-CSRFToken', m[1]);
      },
      data: JSON.stringify({}),
    }).done(res => {
      if (res.error){
        this.setState({ submitting: false, status: 'FAILED', error: res.error });
        return;
      }
      this.pollStatus(pair.id);
      this.loadPairs();
    }).fail((xhr) => {
      this.setState({ submitting: false, status: 'FAILED',
                      error: _("Server error: ") + (xhr.responseText || xhr.statusText) });
    });
  }

  render(){
    const { loadingTasks, projectTasks, currentTask, taskBefore, name,
            pixelThreshold, pixelMinArea, dsmMinH, dsmMinArea,
            enablePixel, enableDsm, submitting, status, progress, progressStatus,
            error, resultLayers, pairId, loadingOverlays, overlaySummary } = this.state;

    // Overlay banner — visible both when loading and when finished.
    // This is the in-panel answer to "is the change data actually on the map?".
    let overlayBanner = null;
    if (loadingOverlays){
      overlayBanner = <div className="cd-overlay-banner cd-overlay-loading">
        <i className="fa fa-circle-notch fa-spin"/> {_("叠加变化数据中…")}
      </div>;
    } else if (overlaySummary){
      const s = overlaySummary;
      const areaTxt = s.totalArea > 0 ? ` · ${this.fmtArea(s.totalArea)}` : '';
      const failTxt = s.failed > 0 ? ` · ${s.failed} 个图层失败` : '';
      overlayBanner = <div className="cd-overlay-banner cd-overlay-loaded">
        <i className="fa fa-check-circle"/> {`已叠加 pair #${s.pairId} 变化数据 — ${s.featureCount} 个变化区域${areaTxt}${failTxt}`}
        <button className="btn btn-xs btn-link cd-overlay-clear"
                onClick={this.handleRemoveOverlays}
                title={_("Clear overlays from map")}>
          <i className="fa fa-times"/> {_("清除")}
        </button>
      </div>;
    }

    let formContent;
    if (loadingTasks){
      formContent = <div><i className="fa fa-circle-notch fa-spin"/> {_("Loading tasks...")}</div>;
    } else if (projectTasks.length === 0){
      formContent = <div className="alert alert-warning">
        {_("No other completed tasks in this project to compare with. Upload a second task first.")}
      </div>;
    } else {
      const totalArea = resultLayers.reduce((s, l) => s + ((l.stats && l.stats.total_area_m2) || 0), 0);
      const polyCount = resultLayers.reduce((s, l) => s + ((l.stats && l.stats.polygon_count) || 0), 0);

      formContent = <div>
        <ErrorMessage bind={[this, 'error']} />

        <div className="form-group">
          <label>{_("Compare current task against:")}</label>
          <select className="form-control" value={taskBefore} onChange={this.handleChange('taskBefore')}>
            <option value="">{_("-- select earlier task --")}</option>
            {projectTasks.map(t => <option key={t.id} value={t.id}>
              {new Date(t.created_at).toISOString().slice(0,10)} — {(t.name || t.id).slice(0,40)}
            </option>)}
          </select>
        </div>

        <div className="form-group">
          <label>{_("Label (optional):")}</label>
          <input type="text" className="form-control" value={name}
                 placeholder={_("e.g. Q1 vs Q3")}
                 onChange={this.handleChange('name')}/>
        </div>

        <div className="checkbox">
          <label>
            <input type="checkbox" checked={enablePixel} onChange={this.handleCheck('enablePixel')}/>
            {_(" Pixel difference (orthophoto)")}
          </label>
        </div>
        {enablePixel ? <div className="threshold-row">
          <label>{_("Threshold:")}</label>
          <input type="number" step="0.01" min="0" max="1" className="form-control"
                 value={pixelThreshold} onChange={this.handleChange('pixelThreshold')}/>
          <label>{_("Min area (m²):")}</label>
          <input type="number" step="1" min="0" className="form-control"
                 value={pixelMinArea} onChange={this.handleChange('pixelMinArea')}/>
        </div> : null}

        <div className="checkbox">
          <label>
            <input type="checkbox" checked={enableDsm} onChange={this.handleCheck('enableDsm')}/>
            {_(" Height difference (DSM)")}
          </label>
        </div>
        {enableDsm ? <div className="threshold-row">
          <label>{_("Min |Δh| (m):")}</label>
          <input type="number" step="0.1" min="0" className="form-control"
                 value={dsmMinH} onChange={this.handleChange('dsmMinH')}/>
          <label>{_("Min area (m²):")}</label>
          <input type="number" step="1" min="0" className="form-control"
                 value={dsmMinArea} onChange={this.handleChange('dsmMinArea')}/>
        </div> : null}

        <div className="row action-buttons">
          <div className="col-xs-12 text-right">
            {submitting ? <span className="progress-label">
              <i className="fa fa-spin fa-circle-notch"/> {progressStatus || status}
              {progress > 0 ? ` (${progress.toFixed(0)}%)` : ''}
            </span> :
            <button className="btn btn-sm btn-primary" disabled={!taskBefore} onClick={this.handleRun}>
              <i className="fa fa-search fa-fw"/> {_("Run comparison")}
            </button>}
          </div>
        </div>

        {resultLayers.length > 0 ? <div className="result-summary">
          <hr/>
          <div><b>{_("Result:")}</b> {polyCount} {_("polygons, total ")} {this.fmtArea(totalArea)}</div>
          <div className="result-layers">
            {resultLayers.map((l, i) => <div key={i} className="result-layer">
              <span>
                <span className="layer-swatch" style={{background: this.colorForLayer(l.layer_type, 2)}}></span>
                <b>{l.layer_type}</b>: {this.fmtArea(l.stats && l.stats.total_area_m2)}
                ({l.stats && l.stats.polygon_count} {_("polys")})
              </span>
              <button className="btn btn-xs btn-default" onClick={this.handleDownloadLayer(i)}>
                <i className="fa fa-download"/>
              </button>
            </div>)}
          </div>
          <button className="btn btn-xs btn-default" onClick={this.handleRemoveOverlays}>
            <i className="fa fa-trash"/> {_("Remove overlays")}
          </button>
        </div> : null}

        {pairId ? <div className="pair-id">
          <small>{_("Pair ID:")} <code>{pairId}</code></small>
        </div> : null}
      </div>;
    }

    return (<div className="changedetect-panel">
      <span className="close-button" onClick={this.props.onClose}/>
      <div className="title">{_("Change Detection")}</div>
      {currentTask ? <div className="subtitle">
        <small>{_("Current task:")} {(currentTask.name || currentTask.id).slice(0,40)}</small>
      </div> : null}
      {overlayBanner}
      <hr/>
      {this.renderHistory()}
      <hr/>
      {formContent}
    </div>);
  }

  // placeholder methods kept to preserve old behaviour / noop in new flow
  handleDownloadLayer = (i) => () => {
    const l = this.state.resultLayers[i];
    if (!l || !l.geojson) return;
    const blob = new Blob([JSON.stringify(l.geojson, null, 2)], {type: 'application/geo+json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `changedetect_pair_${this.state.pairId}_${l.layer_type}.geojson`;
    a.click();
    URL.revokeObjectURL(url);
  }

  handleRemoveOverlays = () => this.removeAllOverlays();
}
