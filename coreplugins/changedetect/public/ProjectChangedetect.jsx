import React from 'react';
import PropTypes from 'prop-types';
import { _ } from 'webodm/classes/gettext';

/**
 * Standalone Project-level Change Detection page.
 *
 * Mounts at /plugins/changedetect/ via app_mount_points. Lets the user:
 *   1. Pick a project
 *   2. Pick task_before + task_after (within that project)
 *   3. Configure thresholds
 *   4. Run a comparison
 *   5. See all pairs (history) for that project with live status
 *   6. Download result GeoJSONs (no map overlay, just file download)
 *
 * This is for users who want to run change detection without opening
 * the map view. The same Celery worker is used, so background tasks
 * persist across page navigation.
 */
export default class ProjectChangedetect extends React.Component {
  static propTypes = {
    initialProjectId: PropTypes.string,
  }

  constructor(props){
    super(props);
    this.state = {
      // Bootstrap with initialProjectId if provided via URL ?project=<id>
      projectId: props.initialProjectId || '',
      projects: [],
      loadingProjects: false,
      tasks: [],
      loadingTasks: false,
      taskBefore: '',
      taskAfter: '',
      name: '',
      enablePixel: true,
      pixelThreshold: 0.15,
      pixelMinArea: 10,
      enableDsm: true,
      dsmMinH: 0.5,
      dsmMinArea: 25,

      // Run state
      submitting: false,
      pairId: null,
      status: null,
      progress: 0,
      error: '',

      // History
      pairs: [],
      loadingPairs: false,
      pollingPairId: null,
    };
  }

  componentDidMount(){
    this.loadProjects();
    // If launched with ?project=ID, load its pairs right away
    if (this.props.initialProjectId) this.loadPairs();
  }

  componentWillUnmount(){
    if (this.pairsReq) this.pairsReq.abort();
    if (this.tasksReq) this.tasksReq.abort();
    if (this.projectsReq) this.projectsReq.abort();
    if (this.submitReq) this.submitReq.abort();
    if (this.pollReq) clearTimeout(this.pollReq);
  }

  // ---------- Loaders ----------

  loadProjects = () => {
    this.setState({ loadingProjects: true });
    this.projectsReq = $.getJSON('/api/projects/')
      .done(res => {
        const all = (res && res.results) || res || [];
        // Only show projects the user can see (non-public filter is server-side)
        this.setState({ projects: all, loadingProjects: false });
      })
      .fail(() => this.setState({ loadingProjects: false, error: _("Failed to load projects.") }));
  }

  loadTasks = (projectId) => {
    if (!projectId){ this.setState({ tasks: [] }); return; }
    this.setState({ loadingTasks: true });
    this.tasksReq = $.getJSON(`/api/projects/${projectId}/tasks/`)
      .done(res => {
        const all = (res && res.results) || res || [];
        // Only completed tasks
        const completed = all
          .filter(t => t.status === 40)  // COMPLETED
          .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        this.setState({ tasks: completed, loadingTasks: false, taskBefore: '', taskAfter: '' });
      })
      .fail(() => this.setState({ loadingTasks: false, error: _("Failed to load tasks.") }));
  }

  loadPairs = () => {
    const { projectId } = this.state;
    if (!projectId) return;
    this.setState({ loadingPairs: true });
    this.pairsReq = $.getJSON(`/api/plugins/changedetect/project/${projectId}/changedetect/list`)
      .done(res => {
        const pairs = (res && res.pairs) || [];
        this.setState({ pairs, loadingPairs: false });
        this.resumePollingIfNeeded(pairs);
      })
      .fail(() => this.setState({ loadingPairs: false }));
  }

  resumePollingIfNeeded = (pairs) => {
    if (this.state.pollingPairId) return;
    const inflight = pairs.find(p => p.status === 'QUEUED' || p.status === 'RUNNING');
    if (!inflight) return;
    this.setState({
      pollingPairId: inflight.id,
      pairId: inflight.id,
      status: inflight.status,
      submitting: true,
    });
    this.pollStatus(inflight.id);
  }

  // ---------- Form ----------

  handleChange = (key) => (e) => this.setState({ [key]: e.target.value });
  handleCheck = (key) => (e) => this.setState({ [key]: e.target.checked });

  handleProjectChange = (e) => {
    const projectId = e.target.value;
    this.setState({ projectId, taskBefore: '', taskAfter: '', pairs: [], error: '' });
    this.loadTasks(projectId);
    // We need to fetch pairs for the new project — wait for state to settle
    setTimeout(() => this.loadPairs(), 0);
  }

  handleRun = () => {
    const { projectId, taskBefore, taskAfter, name, enablePixel, enableDsm,
            pixelThreshold, pixelMinArea, dsmMinH, dsmMinArea } = this.state;
    if (!projectId || !taskBefore || !taskAfter){
      this.setState({ error: _("Pick a project, a 'before' task, and an 'after' task.") });
      return;
    }
    if (taskBefore === taskAfter){
      this.setState({ error: _("'Before' and 'after' must be different tasks.") });
      return;
    }
    this.setState({ submitting: true, error: '', status: 'QUEUED',
                    progress: 0, progressStatus: _('Submitting...') });

    this.submitReq = $.ajax({
      type: 'POST',
      url: `/api/plugins/changedetect/project/${projectId}/changedetect/create`,
      contentType: 'application/json',
      beforeSend: (xhr) => {
        const m = document.cookie.match(/csrftoken=([^;]+)/);
        if (m) xhr.setRequestHeader('X-CSRFToken', m[1]);
      },
      data: JSON.stringify({
        task_before: taskBefore,
        task_after: taskAfter,
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
      this.loadPairs();
    }).fail((xhr) => {
      this.setState({ submitting: false, status: 'FAILED',
                      error: _("Server error: ") + (xhr.responseText || xhr.statusText) });
    });
  }

  // ---------- Polling ----------

  pollStatus = (pairId) => {
    const pid = pairId || this.state.pollingPairId || this.state.pairId;
    if (!pid) return;
    this.pollReq = setTimeout(() => {
      $.getJSON(`/api/plugins/changedetect/changedetect/pair/${pid}/status`)
        .done(res => {
          this.setState({
            status: res.status,
            error: res.error_message || '',
          });
          if (res.status === 'DONE'){
            this.setState({ submitting: false, pollingPairId: null });
            this.loadPairs();
          } else if (res.status === 'FAILED'){
            this.setState({ submitting: false, pollingPairId: null,
                            error: res.error_message || _("Failed.") });
            this.loadPairs();
          } else {
            this.pollStatus(pid);
          }
        })
        .fail(() => this.pollStatus(pid));
    }, 1500);
  }

  handleRerun = (pair) => {
    this.setState({
      submitting: true, error: '',
      status: 'QUEUED',
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

  handleDownload = (pair) => {
    // Trigger downloads of every result layer as a separate file
    if (!pair.results || pair.results.length === 0) return;
    pair.results.forEach(meta => {
      const url = `/api/plugins/changedetect/changedetect/pair/${pair.id}/result/${meta.id}/download`;
      // Use a hidden iframe trick so multiple downloads work in sequence
      const a = document.createElement('a');
      a.href = url;
      a.target = '_blank';
      a.download = `changedetect_pair_${pair.id}_${meta.layer_type}.geojson`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    });
  }

  // ---------- Helpers ----------

  fmtTime = (iso) => {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString(); } catch(e) { return iso; }
  }

  // ---------- Render ----------

  renderProjectPicker = () => {
    const { projects, loadingProjects, projectId } = this.state;
    return <div className="form-group">
      <label>{_("Project:")}</label>
      {loadingProjects ? <div><i className="fa fa-circle-notch fa-spin"/> {_("Loading projects...")}</div> :
        <select className="form-control" value={projectId} onChange={this.handleProjectChange}>
          <option value="">{_("-- pick a project --")}</option>
          {projects.map(p => <option key={p.id} value={p.id}>
            {p.name || p.id} ({p.task_count || 0} tasks)
          </option>)}
        </select>}
    </div>;
  }

  renderTaskPicker = () => {
    const { tasks, loadingTasks, taskBefore, taskAfter } = this.state;
    if (!this.state.projectId) return null;
    if (loadingTasks) return <div><i className="fa fa-circle-notch fa-spin"/> {_("Loading tasks...")}</div>;
    if (tasks.length < 2) return <div className="alert alert-warning">
      {_("This project needs at least two completed tasks to compare.")}
    </div>;
    return <div>
      <div className="form-group">
        <label>{_("Task A (before):")}</label>
        <select className="form-control" value={taskBefore} onChange={this.handleChange('taskBefore')}>
          <option value="">{_("-- pick earlier task --")}</option>
          {tasks.map(t => <option key={t.id} value={t.id}>
            {new Date(t.created_at).toISOString().slice(0,10)} — {(t.name || t.id).slice(0,50)}
          </option>)}
        </select>
      </div>
      <div className="form-group">
        <label>{_("Task B (after):")}</label>
        <select className="form-control" value={taskAfter} onChange={this.handleChange('taskAfter')}>
          <option value="">{_("-- pick later task --")}</option>
          {tasks.filter(t => t.id !== taskBefore).map(t => <option key={t.id} value={t.id}>
            {new Date(t.created_at).toISOString().slice(0,10)} — {(t.name || t.id).slice(0,50)}
          </option>)}
        </select>
      </div>
    </div>;
  }

  renderThresholds = () => {
    const { enablePixel, pixelThreshold, pixelMinArea,
            enableDsm, dsmMinH, dsmMinArea, name } = this.state;
    return <div>
      <div className="form-group">
        <label>{_("Label (optional):")}</label>
        <input type="text" className="form-control" value={name}
               placeholder={_("e.g. Q1 vs Q3")} onChange={this.handleChange('name')}/>
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
    </div>;
  }

  renderHistory = () => {
    const { pairs, loadingPairs, pollingPairId, projectId } = this.state;
    if (!projectId) return null;
    if (loadingPairs){
      return <div className="cd-standalone-loading">
        <i className="fa fa-circle-notch fa-spin"/> {_("Loading comparisons...")}
      </div>;
    }
    if (!pairs || pairs.length === 0){
      return <div className="cd-standalone-empty text-muted">
        <small>{_("No comparisons in this project yet. Pick two tasks above to start.")}</small>
      </div>;
    }
    return <div>
      <div className="cd-standalone-section-title">
        <b>{_("Comparisons:")}</b> <span className="badge">{pairs.length}</span>
      </div>
      <table className="table table-condensed table-striped cd-standalone-table">
        <thead>
          <tr>
            <th>{_("Status")}</th>
            <th>{_("Label")}</th>
            <th>{_("A → B")}</th>
            <th>{_("Updated")}</th>
            <th>{_("Results")}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {pairs.map(p => {
            const statusClass = `cd-status cd-status-${(p.status||'').toLowerCase()}`;
            const isPolling = p.id === pollingPairId;
            return <tr key={p.id} className={isPolling ? 'active' : ''}>
              <td><span className={statusClass}>{p.status || '?'}</span></td>
              <td title={p.name || p.id}><b>{p.name || `Pair #${p.id}`}</b></td>
              <td>
                <small>
                  {(p.task_before_name || '?').slice(0,20)}
                  {' → '}
                  {(p.task_after_name || '?').slice(0,20)}
                </small>
              </td>
              <td><small>{this.fmtTime(p.updated_at)}</small></td>
              <td><span className="badge">{p.results ? p.results.length : 0}</span></td>
              <td>
                {p.status === 'DONE' ? <button className="btn btn-xs btn-primary"
                    onClick={() => this.handleDownload(p)} title={_("Download GeoJSON")}>
                  <i className="fa fa-download"/> {_("Download")}
                </button> : null}
                {p.status === 'FAILED' ? <button className="btn btn-xs btn-warning"
                    onClick={() => this.handleRerun(p)} title={_("Try again")}>
                  <i className="fa fa-refresh"/> {_("Retry")}
                </button> : null}
                {(p.status === 'QUEUED' || p.status === 'RUNNING') ? <span className="text-muted">
                  <i className="fa fa-circle-notch fa-spin"/>
                </span> : null}
              </td>
            </tr>;
          })}
        </tbody>
      </table>
    </div>;
  }

  render(){
    const { submitting, status, error, projectId, taskBefore, taskAfter } = this.state;
    const canRun = projectId && taskBefore && taskAfter && !submitting;

    return (<div className="cd-standalone">
      <h3><i className="fa fa-clone"/> {_("Change Detection")}</h3>
      <p className="text-muted">
        {_("Compare two completed tasks from the same project. The result will list the areas of change. Runs in the background; you can leave this page and come back later.")}
      </p>

      <div className="row">
        <div className="col-md-5">
          <div className="panel panel-default">
            <div className="panel-heading"><b>{_("New comparison")}</b></div>
            <div className="panel-body">
              {error ? <div className="alert alert-danger"><b>{_("Error:")}</b> {error}</div> : null}
              {this.renderProjectPicker()}
              {this.renderTaskPicker()}
              {this.renderThresholds()}
              <div className="text-right">
                {submitting ? <span className="text-info">
                  <i className="fa fa-circle-notch fa-spin"/> {status}
                </span> :
                <button className="btn btn-primary" disabled={!canRun} onClick={this.handleRun}>
                  <i className="fa fa-search fa-fw"/> {_("Run comparison")}
                </button>}
              </div>
            </div>
          </div>
        </div>
        <div className="col-md-7">
          <div className="panel panel-default">
            <div className="panel-heading"><b>{_("Project history")}</b></div>
            <div className="panel-body">
              {this.renderHistory()}
            </div>
          </div>
        </div>
      </div>
    </div>);
  }
}
