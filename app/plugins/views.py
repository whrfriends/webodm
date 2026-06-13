import os

from app.api.tasks import TaskNestedView as TaskView
from app.api.workers import CheckTask as CheckTask
from app.api.workers import GetTaskResult as GetTaskResult
from app.api.workers import TaskResultOutputError

from django.http import HttpResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from .functions import get_plugin_by_name, get_active_plugins
from django.conf.urls import url
from django.views.static import serve
from urllib.parse import urlparse


def try_resolve_url(request, url):
    o = urlparse(request.get_full_path())
    res = url.resolve(o.path)
    if res:
        return res
    else:
        return (None, None, None)

def _ensure_plugin_access(plugin, request):
    """
    Plugin-level access gate (app/plugins/plugin_base.py:user_can_access).

    Returns None if access is allowed; raises Http404 otherwise. Using 404
    (not 403) intentionally — we don't want to leak the plugin's existence
    to unauthorized users. The menu tag (templatetags/plugins.py) hides the
    sidebar entry for the same reason, so URL guessing is the only attack
    surface left; 404 closes it without confirming the plugin exists.
    """
    if not plugin.user_can_access(request):
        raise Http404("No valid routes")


# ufly 嵌入版修改 (whrui): 在 app_view_handler / api_view_handler 装饰 csrf_exempt。
# 原因：WebODM 顶层 CsrfViewMiddleware 检查的是 URL 解析返回的 callback
# (即这两个 handler)，不检查 handler 内部调用的 view。Plugin 的 view 都通过
# mount_points 间接调用，所以即使 view 本身 csrf_exempt=True，POST 也会被 403。
# uFly 嵌入版用 session + csrftoken 已经做了认证，plugin 内部用自己的权限校验。
def app_view_handler(request, plugin_name=None):
    plugin = get_plugin_by_name(plugin_name) # TODO: this pings the server, which might be bad for performance with very large amount of files
    if plugin is None:
        raise Http404("Plugin not found")
    _ensure_plugin_access(plugin, request)

    # Try mountpoints first
    for mount_point in plugin.app_mount_points():
        view, args, kwargs = try_resolve_url(request, url(r'^/plugins/{}/{}'.format(plugin_name, mount_point.url),
                                                 mount_point.view,
                                                 *mount_point.args,
                                                 **mount_point.kwargs))
        if view:
            return view(request, *args, **kwargs)

    # Try public assets
    if os.path.exists(plugin.get_path("public")) and plugin.serve_public_assets(request):
        view, args, kwargs = try_resolve_url(request, url('^/plugins/{}/(.*)'.format(plugin_name),
                                                            serve,
                                                            {'document_root': plugin.get_path("public")}))
        if view:
            return view(request, *args, **kwargs)

    raise Http404("No valid routes")


def api_view_handler(request, plugin_name=None):
    plugin = get_plugin_by_name(plugin_name) # TODO: this pings the server, which might be bad for performance with very large amount of files
    if plugin is None:
        raise Http404("Plugin not found")
    _ensure_plugin_access(plugin, request)

    for mount_point in plugin.api_mount_points():
        view, args, kwargs = try_resolve_url(request, url(r'^/api/plugins/{}/{}'.format(plugin_name, mount_point.url),
                                                 mount_point.view,
                                                 *mount_point.args,
                                                 **mount_point.kwargs))

        if view:
            return view(request, *args, **kwargs)

    raise Http404("No valid routes")

# Wrap so Django's CsrfViewMiddleware sees csrf_exempt on the URL-resolved
# callback. The mount_point views are dispatched at runtime; without this
# wrapper every plugin POST gets rejected with 403 regardless of the
# individual view's csrf_exempt flag.
app_view_handler = csrf_exempt(app_view_handler)
api_view_handler = csrf_exempt(api_view_handler)

def root_url_patterns():
    result = []
    for p in get_active_plugins():
        for mount_point in p.root_mount_points():
            result.append(url(mount_point.url, mount_point.view, *mount_point.args, **mount_point.kwargs))
            
    return result