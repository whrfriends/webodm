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

function fetchJSON(url, opts){
    opts = opts || {};
    opts.headers = opts.headers || {};
    if (opts.method && opts.method !== 'GET'){
        opts.headers['X-CSRFToken'] = getCSRFToken();
    }
    return fetch(url, opts).then(function(r){
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    });
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
    // show all 4 steps
    $('#cd-step-config, #cd-step-running, #cd-step-done').hide();
    $('#cd-step-list').show();
    $('#cd-btn-submit').show().text('提交');
    $('#cd-btn-view').hide();
    // load pair history
    refreshPairsTable(projectId);
    $modal.modal('show');
}

function refreshPairsTable(projectId){
    fetchJSON('/api/plugins/changedetect/project/' + projectId + '/changedetect/list').then(function(json){
        var pairs = json.results || json || [];
        var $tb = $('#cd-pairs-tbody');
        $tb.empty();
        if (!pairs.length){
            $tb.append('<tr><td colspan="5" class="text-muted">暂无 pair</td></tr>');
            return;
        }
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
            var viewBtn = p.status === 'DONE'
                ? '<button class="btn btn-xs btn-primary cd-view-btn" data-pid="' + p.id + '" data-project="' + projectId + '">查看</button>'
                : '';
            $tb.append(
                '<tr>' +
                '<td>' + p.id + '</td>' +
                '<td><code>' + (p.task_a || '').slice(0,8) + '</code> → <code>' + (p.task_b || '').slice(0,8) + '</code></td>' +
                '<td>' + statusBadge + '</td>' +
                '<td>' + resultCell + '</td>' +
                '<td>' + viewBtn + '</td>' +
                '</tr>'
            );
        });
    }).catch(function(e){
        $('#cd-pairs-tbody').html('<tr><td colspan="5" class="text-danger">列表加载失败: ' + e.message + '</td></tr>');
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

// Inject button into project list rows
function injectIntoProjectList(){
    // Find each "View Map" link. The link has no class, but we can
    // match the text. Each link is followed by Edit/Delete in a
    // div with class "project-actions" or similar. We append our
    // button immediately after the link in DOM.
    $('a:contains("View Map")').each(function(){
        var $a = $(this);
        if ($a.data('cd-injected')) return;
        $a.data('cd-injected', true);
        // climb to the parent row that has a data-id-ish attribute
        var $row = $a.closest('[class*="project"], [class*="list-item"], li');
        // Find project id: look for an id pattern in a sibling / parent
        var $projectEl = $a.closest('.project-list-item, .project');
        var pid = null;
        if ($projectEl.length){
            pid = $projectEl.data('id') || $projectEl.attr('data-project-id');
        }
        if (!pid){
            // Walk up to find data-id
            var $p = $a.parent();
            while ($p.length && !pid){
                pid = $p.data('id') || $p.attr('data-id');
                $p = $p.parent();
            }
        }
        if (!pid){
            // Fallback: parse the project list store. React keeps it in
            // its own state, but the page has <a href="/projects/<id>/...">
            // links. Find the closest project id from those.
            var $a2 = $a.closest('div, li').find('a[href*="/projects/"]').first();
            if ($a2.length){
                var m = ($a2.attr('href') || '').match(/\/projects\/(\d+)/);
                if (m) pid = m[1];
            }
        }
        if (!pid){ return; }
        // Inject a clone of the <i>+<a> pair
        var $btn = $(
            '<span class="cd-project-action">' +
            '<i class="fa fa-clone fa-fw"></i>' +
            '<a href="javascript:void(0);" class="cd-open-btn">变化检测</a>' +
            '</span>'
        );
        $btn.find('.cd-open-btn').on('click', function(){
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
