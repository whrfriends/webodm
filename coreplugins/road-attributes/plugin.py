"""
Road Attributes plugin - MountPoints.

The page (registered under the historic "road-attributes" URL) is now a
"桥梁数据库" (bridge database) UI: it reads/writes the existing
`bridge.bridge_cards` PostgreSQL table and 7 sub-tables, plus a placeholder
view for the 4 other tabs that don't have underlying tables yet.

Routes:
  /plugins/road-attributes/            → templates/index.html (main page)
  /plugins/road-attributes/health      → small JSON liveness ping

API mount points (/api/plugins/road-attributes/<path>):
  bridges list / detail / subtable / stats / export
  meta (filter dropdowns), photos upload/delete
  placeholders for tunnels/culverts/slopes/road-segments
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from app.plugins import Menu, MountPoint, PluginBase

import importlib

_api = importlib.import_module("coreplugins.road-attributes.api")

# 这个插件的权限通过 WebODM admin UI 配置：
# /admin/app/pluginaccess/ → 添加一行 plugin_name="road-attributes"
# 然后选 access_mode=restricted 并勾选允许的组。
# 这里不需要硬编码的 user_can_access override，默认实现 (PluginBase) 会
# 自动查 PluginAccess 表。


class Plugin(PluginBase):
    def main_menu(self):
        return [Menu(_("Bridge Database"), self.public_url(""), "fa fa-database fa-fw")]

    def user_can_access(self, request):
        """
        委托给默认实现 (PluginBase.user_can_access)，从 PluginAccess 表读取。
        保留这个方法仅为文档目的——可删除（行为不变）。
        """
        return super().user_can_access(request)

    def include_js_files(self):
        return ["main.js"]

    def app_mount_points(self):
        @login_required
        def index(request):
            return render(request, self.template_path("index.html"), {
                "title": _("Bridge Database"),
            })

        @login_required
        def health(request):
            return JsonResponse({
                "status": "ok",
                "plugin": "road-attributes (bridge database)",
            })

        # Only simple url() patterns here. The app_view_handler in
        # app/plugins/views.py does NOT catch Resolver404 from include()-style
        # patterns, so any single non-matching include aborts the whole view.
        return [
            MountPoint("$", index),
            MountPoint("health$", health),
        ]

    def api_mount_points(self):
        """API routes mounted at /api/plugins/road-attributes/<path>.

        Each route is its OWN MountPoint — Django 2.2's url() interprets a
        list/tuple view as include() args (3-tuple unpack), which fails on
        DRF router's router.urls (N-length list). See app/plugins/views.py:54.
        """
        mp = []

        # Bridges CRUD. Every regex MUST end with `$` because WebODM's
        # api_view_handler (app/plugins/views.py:54) builds the URL pattern as
        # `^/api/plugins/{name}/{mount_point.url}` WITHOUT a trailing `$` — so
        # any unanchored mount like `bridges/?` will swallow all sub-paths
        # (`bridges/stats/`, `bridges/export/`, `bridges/<uuid>/`, …) as a
        # prefix match against the FIRST registered mount.
        mp += [
            MountPoint(r"bridges/?$",                          _api.bridges_list,        name="bridge-list"),
            MountPoint(r"bridges/export/?$",                   _api.bridges_export,      name="bridge-export"),
            MountPoint(r"bridges/stats/?$",                    _api.bridges_stats,       name="bridge-stats"),
            MountPoint(r"bridges/(?P<bridge_id>[0-9a-fA-F-]{36})/?$",         _api.bridge_detail,    name="bridge-detail"),
            MountPoint(r"bridges/(?P<bridge_id>[0-9a-fA-F-]{36})/(?P<kind>evaluations|piers|bearings|main-beams|expansion-joints|diseases|archives)/?$",
                       _api.bridge_subtable, name="bridge-subtable"),
            MountPoint(r"bridges/(?P<bridge_id>[0-9a-fA-F-]{36})/photos/?$",  _api.photo_upload,      name="bridge-photo-upload"),
            MountPoint(r"bridges/(?P<bridge_id>[0-9a-fA-F-]{36})/photos/(?P<kind>general|front)/?$",
                       _api.photo_delete, name="bridge-photo-delete"),
        ]

        # Meta + placeholders + health
        mp += [
            MountPoint(r"meta/?$", _api.meta, name="bridge-meta"),
            MountPoint(r"placeholders/(?P<tab>tunnels|culverts|slopes|road-segments)/?$",
                       _api.placeholder_tab, name="bridge-placeholder"),
            MountPoint(r"health/?$", _api.health, name="bridge-health"),
        ]

        return mp
