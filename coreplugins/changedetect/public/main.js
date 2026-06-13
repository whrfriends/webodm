/*
 * Changedetect plugin — main entry.
 *
 * 1. Map controls: kept (unchanged). When the project map page is open
 *    we mount the changedetect control on the Leaflet map.
 * 2. Project list: we DOM-inject a "变化检测" button next to each
 *    project's "View Map" link so the user can run change detection
 *    without going into the map view first. The button opens a
 *    Bootstrap modal where the user picks two tasks (before / after)
 *    and a threshold, then submits. The modal polls pair status and
 *    offers "查看" to jump to /map/task/<afterId>/ with the change
 *    overlay enabled.
 */

// main.js is loaded directly by WebODM (not via webpack). SCSS is
// compiled by webpack into build/Changedetect.css and served via
// include_css_files() in plugin.py. jQuery is a global.
var $ = window.jQuery;

// 1) Map controls -------------------------------------------------------
if (window.PluginsAPI && window.PluginsAPI.Map){
    PluginsAPI.Map.willAddControls([
        'changedetect/build/Changedetect.js',
        'changedetect/build/Changedetect.css'
    ], function(args, Changedetect){
        var tasks = [];
        var ids = {};
        for (var i = 0; i < args.tiles.length; i++){
            var task = args.tiles[i].meta.task;
            if (!ids[task.id]){
                tasks.push(task);
                ids[task.id] = true;
            }
        }
        if (tasks.length >= 1){
            args.map.addControl(new Changedetect({map: args.map, tasks: tasks}));
        }
    });
}

// 2) Project list injection -------------------------------------------
function getCookie(name){
    var m = document.cookie.match('(^|;)\\s*' + name + '=([^;]+)');
    return m ? decodeURIComponent(m.pop()) : null;
}

function getCSRFToken(){
    return getCookie('csrftoken');
}

// Top-right toast notification. Used by both the project-list modal
// (download done, etc.) and ChangedetectPanel (overlay loaded). Stays
// on screen for 4s, then fades. Multiple toasts stack vertically.
window.CDToast = function(message, kind){
    kind = kind || 'info';
    if ($('#cd-toast-container').length === 0){
        $('body').append(
            '<div id="cd-toast-container" style="' +
            'position:fixed;top:70px;right:20px;z-index:10000;' +
            'display:flex;flex-direction:column;gap:8px;align-items:flex-end;' +
            'pointer-events:none;"></div>'
        );
    }
    var colors = {
        'success': { bg: '#27ae60', icon: '✓' },
        'warn':    { bg: '#e67e22', icon: '⚠' },
        'error':   { bg: '#c0392b', icon: '✕' },
        'info':    { bg: '#2980b9', icon: 'ℹ' }
    };
    var c = colors[kind] || colors.info;
    var $t = $(
        '<div class="cd-toast cd-toast-' + kind + '" style="' +
        'background:' + c.bg + ';color:#fff;padding:10px 16px;' +
        'border-radius:4px;box-shadow:0 4px 12px rgba(0,0,0,0.2);' +
        'max-width:380px;font-size:13px;line-height:1.4;' +
        'display:flex;align-items:center;gap:8px;pointer-events:auto;' +
        'opacity:0;transform:translateX(20px);transition:opacity .25s,transform .25s;">' +
        '<span style="font-size:16px;font-weight:bold;">' + c.icon + '</span>' +
        '<span>' + message + '</span>' +
        '<button style="background:none;border:none;color:#fff;opacity:.7;cursor:pointer;margin-left:8px;padding:0 4px;font-size:16px;line-height:1;">×</button>' +
        '</div>'
    );
    $t.find('button').on('click', function(){ $t.remove(); });
    $('#cd-toast-container').append($t);
    setTimeout(function(){ $t.css({opacity: 1, transform: 'translateX(0)'}); }, 10);
    setTimeout(function(){
        $t.css({opacity: 0, transform: 'translateX(20px)'});
        setTimeout(function(){ $t.remove(); }, 300);
    }, 4500);
};

function fetchJSON(url, opts, raw){
    opts = opts || {};
    opts.headers = opts.headers || {};
    // Always ask for JSON. WebODM DRF returns HTML for browser
    // navigation on the same URL, which would break r.json().
    opts.headers['Accept'] = opts.headers['Accept'] || 'application/json';
    opts.headers['X-Requested-With'] = opts.headers['X-Requested-With'] || 'XMLHttpRequest';
    if (opts.method && opts.method !== 'GET'){
        opts.headers['X-CSRFToken'] = getCSRFToken();
    }
    return fetch(url, {credentials: 'same-origin', ...opts}).then(function(r){
        if (!r.ok) throw new Error('HTTP ' + r.status);
        if (raw) return r;  // caller wants the raw Response (e.g. for blob download)
        return r.json();
    });
}

// Generic info modal. Used for "show saved AI insight", "show error",
// etc. — a small, self-contained Bootstrap dialog with customisable
// title, body HTML, and footer buttons.  Separate from the main
// `cd-modal` (which hosts the T1/T2 form) so it can be opened from
// inside the table or after the form is closed.
function showCDModal(title, bodyHtml, footerButtons){
    if ($('#cd-modal-info').length === 0){
        $('body').append([
            '<div class="modal fade" id="cd-modal-info" tabindex="-1" role="dialog" style="z-index:11000;">',
            '  <div class="modal-dialog modal-lg" role="document">',
            '    <div class="modal-content">',
            '      <div class="modal-header"><button type="button" class="close" data-dismiss="modal">&times;</button>',
            '        <h4 class="modal-title"></h4></div>',
            '      <div class="modal-body"></div>',
            '      <div class="modal-footer"></div>',
            '    </div>',
            '  </div>',
            '</div>'
        ].join('\n'));
    }
    var $m = $('#cd-modal-info');
    $m.find('.modal-title').text(title || '');
    $m.find('.modal-body').html(bodyHtml || '');
    var $f = $m.find('.modal-footer').empty();
    (footerButtons || [{label: '关闭', cls: 'btn-default', close: true}]).forEach(function(b){
        var $b = $('<button type="button" class="btn ' + (b.cls || 'btn-default') + '">' + (b.label || 'OK') + '</button>');
        if (b.close !== false){
            $b.attr('data-dismiss', 'modal');
        }
        $b.on('click', b.onClick || function(){});
        $f.append($b);
    });
    $m.modal('show');
}

function openChangeDetectModal(projectId){
    // Bootstrap modal markup
    if ($('#cd-modal').length === 0){
        $('body').append([
            '<div class="modal fade" id="cd-modal" tabindex="-1" role="dialog">',
            '  <div class="modal-dialog modal-lg" role="document">',
            '    <div class="modal-content">',
            '      <div class="modal-header"><button type="button" class="close" data-dismiss="modal">&times;</button>',
            '        <h4 class="modal-title">变化检测</h4></div>',
            '      <div class="modal-body">',
            // AI Recommendations block — hidden until the user clicks
            // "AI 推荐 pair". When the LLM responds we render a small
            // list of (task_a, task_b, reason) cards the user can click
            // to pre-fill the T1/T2 selectors below.
            '        <div class="cd-modal-ai-recs" id="cd-ai-recs" style="display:none; margin-bottom: 12px; padding: 10px; background: #fef9e7; border-left: 3px solid #f39c12; border-radius: 3px;">',
            '          <strong>🤖 AI 推荐 pair</strong>',
            '          <div id="cd-ai-recs-list" style="margin-top: 6px;"></div>',
            '        </div>',
            '        <div class="cd-modal-step" id="cd-step-config">',
            '          <div class="form-group"><label>基准任务 (T1)</label><select class="form-control" id="cd-t1"></select></div>',
            '          <div class="form-group"><label>对比任务 (T2)</label><select class="form-control" id="cd-t2"></select></div>',
            '          <div class="form-group"><label>像素差分阈值</label><input type="number" class="form-control" id="cd-threshold" value="0.15" step="0.01" min="0.01" max="1.0"/></div>',
            '          <div class="form-group"><label><input type="checkbox" id="cd-vectorize" checked/> 矢量化输出 GeoJSON</label></div>',
            '        </div>',
            '        <div class="cd-modal-step" id="cd-step-running" style="display:none">',
            '          <p>正在处理 pair <span id="cd-pair-id"></span>… <span id="cd-pair-status"></span></p>',
            '          <div class="progress"><div class="progress-bar progress-bar-striped active" id="cd-progress-bar" style="width:5%"></div></div>',
            '        </div>',
            '        <div class="cd-modal-step" id="cd-step-done" style="display:none">',
            '          <p>完成 — pair <span id="cd-done-pair-id"></span></p>',
            '          <div id="cd-done-stats"></div>',
            '        </div>',
            '        <div class="cd-modal-step" id="cd-step-list">',
            '          <h5>本项目历史 pair</h5>',
            '          <table class="table table-condensed"><thead><tr><th>ID</th><th>T1 → T2</th><th>状态</th><th>结果</th><th></th></tr></thead><tbody id="cd-pairs-tbody"></tbody></table>',
            '        </div>',
            '      </div>',
            '      <div class="modal-footer">',
            '        <button type="button" class="btn btn-default" data-dismiss="modal">关闭</button>',
            '        <button type="button" class="btn btn-primary" id="cd-btn-submit">提交</button>',
            '        <button type="button" class="btn btn-primary" id="cd-btn-view" style="display:none">查看</button>',
            '      </div>',
            '    </div>',
            '  </div>',
            '</div>'
        ].join('\n'));
    }
    var $modal = $('#cd-modal');
    $modal.data('projectId', projectId);
    // load tasks
    fetchJSON('/api/projects/' + projectId + '/tasks/').then(function(json){
        var opts = '<option value="">— 选择任务 —</option>';
        var tasks = json || [];
        tasks.sort(function(a, b){ return new Date(a.created_at) - new Date(b.created_at); });
        tasks.forEach(function(t){
            var lbl = (t.name || t.id) + '  (' + (t.created_at || '') + ')';
            opts += '<option value="' + t.id + '">' + lbl + '</option>';
        });
        $('#cd-t1, #cd-t2').html(opts);
    }).catch(function(e){
        $('#cd-t1, #cd-t2').html('<option value="">(加载任务失败: ' + e.message + ')</option>');
    });
    // show all relevant steps at once
    $('#cd-step-config').show();
    $('#cd-step-running, #cd-step-done').hide();
    $('#cd-step-list').show();
    $('#cd-btn-submit').show().prop('disabled', false).text('提交');
    $('#cd-btn-view').hide();
    // "AI 推荐" 按钮注入到 modal footer (提交按钮旁)
    if ($('#cd-btn-ai-recs').length === 0){
        $('#cd-btn-submit').after(
            ' <button type="button" class="btn btn-warning" id="cd-btn-ai-recs" title="调用 LLM 推荐最值得做变化检测的 pair 组合">🤖 AI 推荐</button>'
        );
    }
    // load pair history
    refreshPairsTable(projectId);
    // 同时加载已缓存的 AI 推荐
    refreshAIRecs(projectId);
    $modal.modal('show');
}

function refreshAIRecs(projectId){
    fetchJSON('/api/plugins/changedetect/project/' + projectId + '/ai/recommend-pairs').then(function(json){
        var recs = (json && json.recommendations) || [];
        if (recs.length === 0){
            $('#cd-ai-recs').hide();
            return;
        }
        // Build a compact list. Each entry: rank + reason + click-to-fill.
        var html = recs.map(function(r){
            var a = (r.task_a_id || '').slice(0, 8);
            var b = (r.task_b_id || '').slice(0, 8);
            return '<div class="cd-ai-rec-item" data-a="' + r.task_a_id + '" data-b="' + r.task_b_id + '" style="padding: 4px 0; cursor: pointer;">' +
                '<span class="label label-warning" style="margin-right:6px">#' + r.rank + '</span>' +
                '<code>' + a + '… → ' + b + '…</code> ' +
                '<small class="text-muted">' + $('<div>').text(r.reason || '').html() + '</small>' +
                '</div>';
        }).join('');
        $('#cd-ai-recs-list').html(html);
        $('#cd-ai-recs').show();
    }).catch(function(){
        $('#cd-ai-recs').hide();
    });
}

function refreshPairsTable(projectId){
    fetchJSON('/api/plugins/changedetect/project/' + projectId + '/changedetect/list').then(function(json){
        // Server returns {"pairs": [...]}; tolerate older {"results": [...]}
        // and bare arrays.
        var pairs = (json && (json.pairs || json.results)) || json || [];
        if (!Array.isArray(pairs)) pairs = [];
        var $tb = $('#cd-pairs-tbody');
        $tb.empty();
        if (!pairs.length){
            // Empty-state hint: tell the user how to make a pair, so
            // they're not stuck wondering why the table is empty.
            $tb.append(
                '<tr><td colspan="5" class="text-muted" style="padding:18px 10px;">' +
                '本项目还没有变化检测 pair。<br>' +
                '请在上方选 <b>基准任务 (T1)</b> 和 <b>对比任务 (T2)</b>，点「提交」创建第一个。' +
                '</td></tr>'
            );
            return;
        }
        // For each DONE pair, also fetch AI insights so the row can show
        // "📝 解读 (12s)" — that way an analysis done in a previous modal
        // session isn't lost when the user closes & reopens the dialog.
        // We fan out in parallel and update the row once each comes back.
        var insightCache = {};  // pid -> [{kind, text, ...}]
        var inflight = pairs.filter(function(p){ return p.status === 'DONE'; });
        var done = inflight.length;
        if (done === 0) {
            renderPairRows(projectId, pairs, insightCache);
            return;
        }
        inflight.forEach(function(p){
            fetchJSON('/api/plugins/changedetect/changedetect/pair/' + p.id + '/ai/insights')
                .then(function(j){
                    insightCache[p.id] = j && j.insights ? j.insights : [];
                })
                .catch(function(){
                    insightCache[p.id] = [];
                })
                .then(function(){
                    done--;
                    if (done === 0) renderPairRows(projectId, pairs, insightCache);
                });
        });
    }).catch(function(e){
        $('#cd-pairs-tbody').html('<tr><td colspan="5" class="text-danger">列表加载失败: ' + e.message + '</td></tr>');
    });
}

function renderPairRows(projectId, pairs, insightCache){
    var $tb = $('#cd-pairs-tbody');
    pairs.forEach(function(p){
        var statusBadge = {
            'QUEUED':  '<span class="label label-default">排队</span>',
            'RUNNING': '<span class="label label-info">运行中</span>',
            'DONE':    '<span class="label label-success">完成</span>',
            'FAILED':  '<span class="label label-danger">失败</span>'
        }[p.status] || '<span class="label label-default">' + (p.status || '?') + '</span>';
        var resultCell = '';
        if (p.status === 'DONE' && p.results && p.results.length){
            p.results.forEach(function(r){
                resultCell += '<a class="btn btn-xs btn-default cd-dl-btn" data-pid="' + p.id + '" data-rid="' + r.id + '">' + (r.kind || 'json') + '</a> ';
            });
        }
        // AI badge: shows when this pair has at least one saved insight,
        // so a previously-generated analysis isn't lost across modal
        // close/reopen. Click the badge to re-open the insight.
        var insights = insightCache[p.id] || [];
        var insightBadge = '';
        if (p.status === 'DONE' && insights.length){
            var analyze = insights.filter(function(x){ return x.kind === 'analyze' && x.text; })[0];
            if (analyze){
                var s = Math.round((analyze.elapsed_ms || 0) / 1000);
                insightBadge = ' <a class="label label-success cd-ai-show-insight" ' +
                    'data-pid="' + p.id + '" data-kind="analyze" ' +
                    'title="已生成 AI 解读，点此查看">' +
                    '📝 解读 ' + (s > 0 ? '(' + s + 's)' : '') + '</a>';
            }
        }
        var viewBtn = p.status === 'DONE'
            ? '<button class="btn btn-xs btn-primary cd-view-btn" data-pid="' + p.id + '" data-project="' + projectId + '">查看</button>'
            : '';
        var reportBtn = p.status === 'DONE'
            ? ' <button class="btn btn-xs btn-success cd-report-btn" data-pid="' + p.id + '" data-project="' + projectId + '" data-name="' + (p.name || ('pair_' + p.id)) + '">下载报告</button>'
            : '';
        // AI buttons: classify zones (geodeep + LLM) and produce a
        // Chinese narrative. The analyze handler now first checks the
        // /ai/insights cache — if an insight already exists we re-open
        // it without re-spending LLM tokens.
        var aiBtns = p.status === 'DONE'
            ? ' <button class="btn btn-xs btn-warning cd-ai-classify-btn" data-pid="' + p.id + '" data-project="' + projectId + '" title="AI 视觉识别每个变化区域是什么">AI 识别</button>' +
              ' <button class="btn btn-xs btn-info cd-ai-analyze-btn" data-pid="' + p.id + '" data-project="' + projectId + '" title="LLM 生成变化原因中文解读（已生成会直接显示）">AI 分析</button>'
            : '';
        $tb.append(
            '<tr>' +
            '<td>' + p.id + '</td>' +
            '<td><code>' + $('<div>').text((p.task_before_name || p.task_a || '').slice(0, 18)).html() + '</code> → ' +
            '<code>' + $('<div>').text((p.task_after_name || p.task_b || '').slice(0, 18)).html() + '</code></td>' +
            '<td>' + statusBadge + '</td>' +
            '<td>' + resultCell + insightBadge + '</td>' +
            '<td style="white-space:nowrap">' + viewBtn + reportBtn + aiBtns + '</td>' +
            '</tr>'
        );
    });
}

function submitPair(projectId){
    var t1 = $('#cd-t1').val();
    var t2 = $('#cd-t2').val();
    if (!t1 || !t2){ alert('请选择 T1 和 T2'); return; }
    if (t1 === t2){ alert('T1 和 T2 不能相同'); return; }
    var threshold = parseFloat($('#cd-threshold').val()) || 0.15;
    var vectorize = $('#cd-vectorize').is(':checked');
    var body = JSON.stringify({
        task_a: t1,
        task_b: t2,
        threshold: threshold,
        vectorize: vectorize
    });
    $('#cd-btn-submit').prop('disabled', true).text('提交中…');
    fetchJSON('/api/plugins/changedetect/project/' + projectId + '/changedetect/create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: body
    }).then(function(json){
        if (window.CDToast){
            window.CDToast(`变化检测任务已提交 (pair #${json.pair_id})，后台处理中…`, 'info');
        }
        $('#cd-step-config').hide();
        $('#cd-step-running').show();
        $('#cd-pair-id').text(json.pair_id || '?');
        pollPairStatus(projectId, json.pair_id, json.celery_task_id);
    }).catch(function(e){
        alert('提交失败: ' + e.message);
        $('#cd-btn-submit').prop('disabled', false).text('提交');
    });
}

function pollPairStatus(projectId, pairId, celeryId){
    var tries = 0;
    function tick(){
        tries++;
        fetchJSON('/api/plugins/changedetect/changedetect/pair/' + pairId + '/status').then(function(p){
            var pct = 5;
            var label = p.status;
            if (p.status === 'QUEUED'){ pct = 5; label = '排队…'; }
            else if (p.status === 'RUNNING'){ pct = 50; label = '运行中…'; }
            else if (p.status === 'DONE'){ pct = 100; label = '完成'; }
            else if (p.status === 'FAILED'){ pct = 100; label = '失败: ' + (p.error || ''); }
            $('#cd-pair-status').text(label);
            $('#cd-progress-bar').css('width', pct + '%');
            if (p.status === 'DONE'){
                if (window.CDToast){
                    window.CDToast(`pair #${pairId} 处理完成!`, 'success');
                }
                $('#cd-step-running').hide();
                $('#cd-step-done').show();
                $('#cd-done-pair-id').text(pairId);
                var stats = p.stats || {};
                $('#cd-done-stats').html(
                    '<ul>' +
                    '<li>变化像素数: ' + (stats.changed_pixels != null ? stats.changed_pixels : '-') + '</li>' +
                    '<li>变化面积 (m²): ' + (stats.changed_area_m2 != null ? stats.changed_area_m2.toFixed(1) : '-') + '</li>' +
                    '<li>特征数: ' + (stats.feature_count != null ? stats.feature_count : '-') + '</li>' +
                    '</ul>'
                );
                $('#cd-btn-submit').hide();
                $('#cd-btn-view').show().data('t2', p.task_b).data('pid', pairId).data('project', projectId);
                refreshPairsTable(projectId);
            } else if (p.status === 'FAILED'){
                if (window.CDToast){
                    window.CDToast(`pair #${pairId} 处理失败: ` + (p.error || ''), 'error');
                }
                $('#cd-step-running').hide();
                $('#cd-step-done').show();
                $('#cd-done-stats').html('<div class="text-danger">处理失败: ' + (p.error || '') + '</div>');
                $('#cd-btn-submit').prop('disabled', false).text('重试');
                $('#cd-step-done').show();
            } else {
                setTimeout(tick, 2000);
            }
        }).catch(function(e){
            if (tries > 60){ return; }
            setTimeout(tick, 3000);
        });
    }
    tick();
}

// Delegated click handlers inside modal
$(document).on('click', '#cd-btn-submit', function(){
    var pid = $('#cd-modal').data('projectId');
    if ($('#cd-step-running').is(':visible')){
        // already running; ignore
        return;
    }
    if ($('#cd-step-done').is(':visible')){
        // retry from done step — show config again
        $('#cd-step-done').hide();
        $('#cd-step-config').show();
        $('#cd-btn-submit').prop('disabled', false).text('提交');
        return;
    }
    submitPair(pid);
});
$(document).on('click', '#cd-btn-view', function(){
    var pid = $(this).data('pid');
    var projectId = $(this).data('project');
    if (pid && projectId){
        window.location.href = '/map/project/' + projectId + '/?cd_pair=' + pid;
    } else if (pid){
        window.location.href = '/map/project/?cd_pair=' + pid;
    }
});
$(document).on('click', '.cd-view-btn', function(){
    var pid = $(this).data('pid');
    var projectId = $(this).data('project');
    if (pid && projectId){
        window.location.href = '/map/project/' + projectId + '/?cd_pair=' + pid;
    }
});
$(document).on('click', '.cd-dl-btn', function(){
    var pid = $(this).data('pid');
    var rid = $(this).data('rid');
    window.location.href = '/api/plugins/changedetect/changedetect/pair/' + pid + '/result/' + rid + '/download';
});

// AI 推荐 pair — calls LLM to suggest the most useful pair
// combinations, then re-renders the #cd-ai-recs block with the
// results. Subsequent calls within 1 h are served from cache unless
// the user passes ?force=1 (we don't surface that for now).
$(document).on('click', '#cd-btn-ai-recs', function(){
    var $btn = $(this).prop('disabled', true).text('🤖 AI 推理中…');
    var projectId = $(this).data('project') || $('#cd-btn-ai-recs').closest('.modal').data('project-id');
    if (!projectId){
        // Fallback: pull from URL (we're inside a project)
        var m = (location.pathname || '').match(/\/project\/(\d+)/);
        if (m) projectId = m[1];
    }
    if (!projectId){ $btn.prop('disabled', false).text('🤖 AI 推荐'); return; }
    fetch('/api/plugins/changedetect/project/' + projectId + '/ai/recommend-pairs/', {
        method: 'POST', credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json', 'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCSRFToken(),
        },
        body: JSON.stringify({k: 3}),
    }).then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j}; }); })
      .then(function(res){
          if (!res.ok){
              showToast('error', 'AI 推荐失败: ' + (res.j.error || res.j.detail || '?'));
              return;
          }
          var recs = res.j.recommendations || [];
          if (recs.length === 0){
              showToast('warn', res.j.note || '没有可推荐的 pair');
              $('#cd-ai-recs').hide();
              return;
          }
          showToast('success', 'AI 推荐 ' + recs.length + ' 对 pair');
          refreshAIRecs(projectId);
      }).catch(function(err){
          showToast('error', 'AI 推荐异常: ' + (err && err.message || err));
      }).then(function(){
          $btn.prop('disabled', false).text('🤖 AI 推荐');
      });
});

// Click on a recommendation → pre-fill the T1/T2 selectors and
// highlight the row. The user still has to click "提交" to actually
// kick off the change-detection worker.
$(document).on('click', '.cd-ai-rec-item', function(){
    var a = $(this).data('a'), b = $(this).data('b');
    if (a) $('#cd-t1').val(a);
    if (b) $('#cd-t2').val(b);
    showToast('info', '已填入 AI 推荐的任务对，请点 "提交" 开始检测');
    $(this).css('background', '#d5f5e3').delay(800).queue(function(n){ $(this).css('background', ''); n(); });
});

// AI 识别 — POST /ai/classify, get back annotations (sync) or a
// celery_task_id (async). We poll the status endpoint if async.
$(document).on('click', '.cd-ai-classify-btn', function(){
    var $btn = $(this);
    var pid = $btn.data('pid');
    if (!pid) return;
    $btn.prop('disabled', true).text('AI 识别中…');
    fetch('/api/plugins/changedetect/changedetect/pair/' + pid + '/ai/classify/', {
        method: 'POST', credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json', 'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCSRFToken(),
        },
        body: JSON.stringify({}),
    }).then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j}; }); })
      .then(function(res){
          if (!res.ok){
              showToast('error', 'AI 识别失败: ' + (res.j.error || '?'));
              return;
          }
          if (res.j.async && res.j.celery_task_id){
              showToast('info', 'AI 识别已在后台启动（任务多），稍候刷新页面');
              pollCeleryStatus(res.j.celery_task_id, 'AI 识别', function(){
                  $btn.prop('disabled', false).text('AI 识别');
                  showToast('success', 'AI 识别完成');
              });
          } else {
              showToast('success', 'AI 识别完成，共 ' + (res.j.annotations || []).length + ' 个区域');
              $btn.prop('disabled', false).text('AI 识别');
          }
      }).catch(function(err){
          showToast('error', 'AI 识别异常: ' + (err && err.message || err));
          $btn.prop('disabled', false).text('AI 识别');
      });
});

// AI 分析 — generate Chinese narrative. Always returns synchronously
// (the LLM call is a few seconds, but we're OK waiting inline).
//
// First checks the /ai/insights cache: if an "analyze" insight already
// exists we re-open it without re-spending LLM tokens. This way an
// analysis done in a previous modal session isn't lost when the user
// closes & reopens the dialog.
$(document).on('click', '.cd-ai-analyze-btn', function(){
    var $btn = $(this);
    var pid = $btn.data('pid');
    if (!pid) return;

    // Find the row so we can re-enable the button even if the modal
    // is closed while the request is in flight.
    var $row = $btn.closest('tr');

    function showInsight(text, kind, model, elapsedMs){
        var ttl = kind === 'summary' ? 'AI 摘要' : 'AI 解读';
        var md = (elapsedMs ? '（耗时 ' + Math.round(elapsedMs/1000) + 's · ' + (model || 'LLM') + '）' : '');
        var body = $('<div>').text(text || '(空)').html().replace(/\n/g, '<br>');
        showCDModal(
            ttl + ' ' + md,
            '<div style="white-space:normal;line-height:1.7;font-size:14px;">' + body + '</div>',
            [{label: '关闭', cls: 'btn-default', close: true}]
        );
    }

    // 1) Try cache first
    fetchJSON('/api/plugins/changedetect/changedetect/pair/' + pid + '/ai/insights').then(function(j){
        var existing = insights.filter(function(x){ return x.kind === 'analyze'; })[0];
        if (existing && existing.text && !existing.error){
            showInsight(existing.text, 'analyze', existing.model, existing.elapsed_ms);
            return;
        }
        // 2) No cache — run the LLM
        $btn.prop('disabled', true).text('AI 分析中…');
        return fetch('/api/plugins/changedetect/changedetect/pair/' + pid + '/ai/analyze/', {
            method: 'POST', credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json', 'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCSRFToken(),
            },
            body: JSON.stringify({}),
        }).then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j}; }); })
          .then(function(res){
              // Re-resolve $btn because the row may have been re-rendered
              // while we were waiting.
              var $btn2 = $('.cd-ai-analyze-btn[data-pid="' + pid + '"]');
              if (res.ok && res.j.text){
                  showToast('success', 'AI 解读已生成 (耗时 ' + (res.j.elapsed_ms || 0) + ' ms)');
                  // If the main modal is still open, show the result inline.
                  // If the user already closed it, the saved insight will
                  // surface via the "📝 解读" badge on next open.
                  if ($('#cd-modal').is(':visible')){
                      showInsight(res.j.text, 'analyze', res.j.model, res.j.elapsed_ms);
                  } else {
                      // Append a "查看" affordance to the toast so the
                      // user can re-open the insight without hunting
                      // for the row in the (closed) modal.
                      var $toast = $('#cd-toast-container .cd-toast').last();
                      $toast.append(' <a href="#" class="cd-toast-view-insight" data-pid="' + pid + '" style="color:#fff;text-decoration:underline;margin-left:8px;">查看</a>');
                  }
              } else {
                  showToast('error', 'AI 分析失败: ' + (res.j.error || '?'));
              }
              $btn2.prop('disabled', false).text('AI 分析');
              // Refresh the row so the "📝 解读" badge shows up.
              $btn2.closest('tr').find('.cd-ai-show-insight').remove();
          }).catch(function(err){
              var $btn2 = $('.cd-ai-analyze-btn[data-pid="' + pid + '"]');
              showToast('error', 'AI 分析异常: ' + (err && err.message || err));
              $btn2.prop('disabled', false).text('AI 分析');
          });
    }).catch(function(){
        // If even the cache check failed, fall back to a direct POST so
        // the user isn't stuck.
        $btn.prop('disabled', true).text('AI 分析中…');
        fetch('/api/plugins/changedetect/changedetect/pair/' + pid + '/ai/analyze/', {
            method: 'POST', credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json', 'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCSRFToken(),
            },
            body: JSON.stringify({}),
        }).then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j}; }); })
          .then(function(res){
              var $btn2 = $('.cd-ai-analyze-btn[data-pid="' + pid + '"]');
              if (res.ok && res.j.text){
                  showInsight(res.j.text, 'analyze', res.j.model, res.j.elapsed_ms);
              } else {
                  showToast('error', 'AI 分析失败: ' + (res.j.error || '?'));
              }
              $btn2.prop('disabled', false).text('AI 分析');
          }).catch(function(err){
              showToast('error', 'AI 分析异常: ' + (err && err.message || err));
          });
    });
});

// Click the "📝 解读" badge to re-open the saved insight.
$(document).on('click', '.cd-ai-show-insight, .cd-toast-view-insight', function(e){
    e.preventDefault();
    var pid = $(this).data('pid');
    var kind = $(this).data('kind') || 'analyze';
    fetchJSON('/api/plugins/changedetect/changedetect/pair/' + pid + '/ai/insights').then(function(j){
        var insights = (j && j.insights) || [];
        var it = insights.filter(function(x){ return x.kind === kind; })[0];
        if (!it) return;
        var ttl = kind === 'summary' ? 'AI 摘要' : 'AI 解读';
        var md = it.elapsed_ms ? '（耗时 ' + Math.round(it.elapsed_ms/1000) + 's · ' + (it.model || 'LLM') + '）' : '';
        var body = $('<div>').text(it.text || it.error || '(空)').html().replace(/\n/g, '<br>');
        showCDModal(
            ttl + ' ' + md,
            '<div style="white-space:normal;line-height:1.7;font-size:14px;">' + body + '</div>',
            [{label: '关闭', cls: 'btn-default', close: true}]
        );
    });
});

// Lightweight celery status poller. We use the same /status endpoint
// that changedetect already exposes for the main worker. The Celery
// task we run is registered with with_progress=True so its result is
// persisted in the standard way.
function pollCeleryStatus(taskId, label, doneCb){
    var attempts = 0, maxAttempts = 60;  // 60 * 2s = 2 min
    var poll = setInterval(function(){
        attempts++;
        if (attempts > maxAttempts){
            clearInterval(poll);
            showToast('error', label + ' 超时');
            return;
        }
        // WebODM exposes /api/workers/get/<task_id> for celery status
        // (see app/api/urls.py in the core repo). We poll it to know
        // when the background classification finishes.
        fetch('/api/workers/get/' + encodeURIComponent(taskId), {
            credentials: 'same-origin',
            headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
        }).then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j}; }); })
          .catch(function(){ return {ok: false, j: {status: 'PENDING'}}; })
          .then(function(res){
              if (!res.ok) return;
              var st = res.j.status || res.j.state || 'PENDING';
              if (st === 'SUCCESS' || st === 'DONE'){
                  clearInterval(poll);
                  doneCb && doneCb(res.j.result);
              } else if (st === 'FAILURE' || st === 'FAILED'){
                  clearInterval(poll);
                  showToast('error', label + ' 失败: ' + (res.j.error || '?'));
              }
          });
    }, 2000);
}

// Download PDF report for a finished pair.
//
// Two-stage flow:
//   1. From the project list: this handler is a "launch" — it navigates
//      to the project map view with `cd_pair=<pid>&cd_report=1` in the
//      URL. The screenshot *has* to happen on the map page because the
//      change-detection GeoJSON overlay is only rendered there.
//   2. On the map page: when main.js sees `cd_report=1` in the URL, it
//      waits for the ChangedetectPanel's autoLoadFromUrl → viewPair →
//      renderResultLayers chain to finish (Leaflet drawing the
//      overlay), then captures the leaflet container via html2canvas
//      and POSTs to the report endpoint. The `cd_report` flag is then
//      stripped from the URL so the user can keep interacting.
$(document).on('click', '.cd-report-btn', function(e){
    e.preventDefault();
    var pid = $(this).data('pid');
    var projectId = $(this).data('project');
    var name = $(this).data('name') || ('pair_' + pid);
    if (!pid || !projectId) return;
    // Navigate to the project map. The map-side handler below picks
    // up `cd_report=1` and runs the actual capture.
    var url = '/map/project/' + projectId + '/?cd_pair=' + pid + '&cd_report=1&cd_name=' + encodeURIComponent(name);
    window.location.href = url;
});

// Capture the report screenshot on the map page when ?cd_report=1.
function maybeAutoCaptureReport(){
    var params;
    try { params = new URLSearchParams(window.location.search); }
    catch(e) { return; }
    if (!params.get('cd_report')) return;
    var pid = params.get('cd_pair');
    var name = params.get('cd_name') || ('pair_' + pid);
    if (!pid) return;
    if (typeof window.html2canvas !== 'function'){
        if (window.showToast) showToast('error', 'html2canvas 未加载，无法生成报告截图');
        return;
    }
    // Strip cd_report from URL early so reloads don't re-trigger
    params.delete('cd_report');
    var q = params.toString();
    var newUrl = window.location.pathname + (q ? '?' + q : '');
    window.history.replaceState({}, '', newUrl);

    // Toast to tell the user what's happening
    if (window.showToast) showToast('info', '正在生成 PDF 报告…');

    // Wait until: (a) the leaflet container exists, (b) the
    // ChangedetectPanel banner shows "已叠加" (i.e. renderResultLayers
    // finished) AND (c) leaflet tiles have settled (no in-flight loads).
    // Leaflet sets .leaflet-tile-loading on tile images while they
    // fetch; we wait until that's gone, then sleep a bit more to let
    // the GPU composite the new frame.
    var attempts = 0, maxAttempts = 60;  // 60 * 500ms = 30s
    var poll = setInterval(function(){
        attempts++;
        var mapEl = document.querySelector('.leaflet-container');
        var banner = document.querySelector('.cd-overlay-loaded');
        var errBanner = document.querySelector('.cd-overlay-loading');
        var tilesLoading = document.querySelectorAll('.leaflet-tile-loading').length;
        if (!mapEl){
            if (attempts >= maxAttempts){ clearInterval(poll); finishCapture(); }
            return;
        }
        if (banner && tilesLoading === 0 && attempts > 6){
            clearInterval(poll);
            // Give Leaflet + GPU two more ticks to finish drawing
            setTimeout(finishCapture, 2500);
            return;
        }
        if (attempts >= maxAttempts){
            clearInterval(poll);
            finishCapture();
        }
    }, 500);

    function finishCapture(){
        var mapEl = document.querySelector('.leaflet-container');
        if (!mapEl){
            if (window.showToast) showToast('error', '未找到地图容器，报告生成失败');
            return;
        }
        if (window.showToast) showToast('info', '截取地图叠加…');
        // Inject capture-mode CSS the first time we need it. We
        // dynamically build a <style> element with rules that hide
        // every piece of Leaflet chrome (zoom buttons, attribution,
        // plugin controls like layers / measure / fullscreen / our
        // own changedetect button) so the screenshot is just the
        // orthophoto + change-detection overlay.
        if (!document.getElementById('cd-capture-style')){
            var s = document.createElement('style');
            s.id = 'cd-capture-style';
            s.textContent =
                'body.cd-capture-mode .leaflet-control-container,' +
                'body.cd-capture-mode .leaflet-control,' +
                'body.cd-capture-mode .leaflet-control-attribution,' +
                'body.cd-capture-mode .leaflet-popup-pane,' +
                'body.cd-capture-mode .leaflet-tooltip-pane {' +
                '  display: none !important; visibility: hidden !important;' +
                '}' +
                // Also make sure no element outside the map is captured
                'body.cd-capture-mode .navbar,' +
                'body.cd-capture-mode .app-sidebar,' +
                'body.cd-capture-mode .cd-overlay-banner,' +
                'body.cd-capture-mode .changedetect-panel,' +
                'body.cd-capture-mode #cd-toast-container {' +
                '  display: none !important;' +
                '}' +
                'body.cd-capture-mode .leaflet-container {' +
                '  box-shadow: none !important;' +
                '}';
            document.head.appendChild(s);
        }
        // Toggle the class so CSS hides the chrome
        document.body.classList.add('cd-capture-mode');
        // One frame for CSS to apply + Leaflet to repaint
        var captureEl = mapEl;
        var origWidth = mapEl.style.width, origHeight = mapEl.style.height;
        var w = mapEl.scrollWidth || mapEl.clientWidth;
        var h = mapEl.scrollHeight || mapEl.clientHeight;
        var release = function(){
            document.body.classList.remove('cd-capture-mode');
            if (origWidth) mapEl.style.width = origWidth;
            if (origHeight) mapEl.style.height = origHeight;
        };
        window.html2canvas(captureEl, {
            backgroundColor: '#ffffff',
            scale: 1,
            useCORS: true,
            logging: false,
            width: w,
            height: h,
            windowWidth: w,
            windowHeight: h,
        }).then(function(canvas){
            var dataUrl = canvas.toDataURL('image/png');
            return fetch('/api/plugins/changedetect/changedetect/pair/' + pid + '/report/', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCSRFToken(),
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({screenshot: dataUrl, title_suffix: name}),
            });
        }).then(function(resp){
            if (!resp || !resp.ok){
                return resp.text().then(function(t){ throw new Error('HTTP ' + resp.status + ': ' + t.slice(0, 200)); });
            }
            return resp.blob();
        }).then(function(blob){
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = 'changedetect_' + pid + '_' + String(name).replace(/[^\w\u4e00-\u9fa5-]/g, '_') + '.pdf';
            document.body.appendChild(a);
            a.click();
            setTimeout(function(){
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }, 200);
            if (window.showToast) showToast('success', 'PDF 报告已下载');
        }).catch(function(err){
            console.error('PDF report failed', err);
            if (window.showToast) showToast('error', 'PDF 报告生成失败: ' + (err && err.message || err));
        }).then(release, release);
    }
}

// Hook into the existing startObserver chain so the auto-capture runs
// on every page that includes the changedetect plugin's JS — i.e. the
// project map view. startObserver is called after jQuery + DOM are
// ready; calling it again here is safe because the underlying
// functions are idempotent.
if (document.readyState === 'complete' || document.readyState === 'interactive'){
    setTimeout(maybeAutoCaptureReport, 0);
} else {
    document.addEventListener('DOMContentLoaded', function(){
        setTimeout(maybeAutoCaptureReport, 0);
    });
}

// Inject button into project list rows. WebODM / ufly's project
// list items have:
//   <li class="project-list-item list-group-item ">
//     <div class="row project-links">
//       <a>1个任务</a>   <a>查看地图</a>   <a>编辑</a>
//     </div>
//   </li>
//
// The row has NO data-id attribute and the links have href="javascript:void(0);".
// We pull the project id from React's internal fiber attached to the <li>:
//   __reactInternalInstance$<key> → walk up the .return chain looking for
//   memoizedProps.data.id (or stateNode.state.data.id). The project name
//   comes from the same props.data object.
//
// The trigger link text is "查看地图" (Chinese) in ufly embedded builds,
// or "View Map" (English) in upstream. We try both.
function getProjectIdFromRow(li){
  try {
    const key = Object.keys(li).find(k => k.startsWith('__reactInternalInstance'));
    if (!key) return null;
    let fiber = li[key];
    let depth = 0;
    while (fiber && depth < 60){
      const p = fiber.memoizedProps || fiber.pendingProps;
      if (p && p.data && typeof p.data.id !== 'undefined'){
        return { id: p.data.id, name: p.data.name || null };
      }
      if (fiber.stateNode && fiber.stateNode.state && fiber.stateNode.state.data && typeof fiber.stateNode.state.data.id !== 'undefined'){
        return { id: fiber.stateNode.state.data.id, name: fiber.stateNode.state.data.name || null };
      }
      fiber = fiber.return;
      depth++;
    }
  } catch(e){ /* fiber may have been GC'd or shape changed */ }
  return null;
}

function injectIntoProjectList(){
    // Find "View Map" / "查看地图" links. The trigger text varies by
    // locale (English upstream, Chinese ufly). We accept either.
    $('a').filter(function(){
        return /^[\s]*View Map[\s]*$/.test($(this).text()) ||
               /^[\s]*查看地图[\s]*$/.test($(this).text());
    }).each(function(){
        var $a = $(this);
        if ($a.data('cd-injected')) return;
        $a.data('cd-injected', true);

        // Find the parent project row (a <li> in the project list) and
        // pull the project id from its React fiber.
        var $row = $a.closest('.project-list-item');
        if (!$row.length) return;

        var info = getProjectIdFromRow($row.get(0));
        if (!info || info.id == null) {
            // Last resort: count items and pull from /api/projects/ by index
            return;
        }
        var pid = info.id;

        // Inject "变化检测" link right after "查看地图"
        var $btn = $(
            '<span class="cd-project-action">' +
            '<i class="fa fa-clone fa-fw"></i>' +
            '<a href="javascript:void(0);" class="cd-open-btn" title="变化检测">变化检测</a>' +
            '</span>'
        );
        $btn.find('.cd-open-btn').on('click', function(e){
            e.stopPropagation();
            openChangeDetectModal(pid);
        });
        $a.after($btn);
    });
}

// Wait for React to mount the project list, then inject.
function startObserver(){
    if (!document.body){ setTimeout(startObserver, 100); return; }
    injectIntoProjectList();
    var obs = new MutationObserver(function(){ injectIntoProjectList(); });
    obs.observe(document.body, {childList: true, subtree: true});
}

if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', startObserver);
} else {
    startObserver();
}
