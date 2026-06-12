"""
Flight Planner plugin for WebODM.

Adds a side-menu entry "Flight Planner" that opens a Leaflet-based mission
planner. The planner supports 6 mission types (polygon survey, spiral, orbit,
cable cam, corkscrew, panel grid) and exports standard KML 2.2 (no DJI/Litchi
proprietary schema).

REST API (under /api/plugins/flight-planner/...):
  POST   /polygon/      boustrophedon survey of arbitrary polygon
  POST   /spiral/       Archimedean spiral
  POST   /orbit/        circle around POI
  POST   /cable/        cable cam along polyline
  POST   /corkscrew/    helical climb
  POST   /grid/         axis-aligned rectangle survey
  GET    /mission/<id>/ JSON mission detail
  GET    /export/<id>.kml
  GET    /export/<id>.geojson
  GET    /health
"""

from app.plugins import PluginBase, Menu, MountPoint
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext_lazy as _

from .api import (
    PolygonView, SpiralView, OrbitView, CableView,
    CorkscrewView, GridView,
    MissionDetailView, MissionListView,
    ExportKmlView, ExportGeoJsonView,
    HealthView,
    DroneModelsView, DroneModelDetailView, DroneModelValidateView,
    ProjectListCreateView, ProjectDetailView, ProjectAddMissionView,
    ProjectExportKmzView, ProjectExportKmlView,
)


class Plugin(PluginBase):
    def main_menu(self):
        return [Menu(_("Flight Planner"), self.public_url(""), "fa fa-plane fa-fw")]

    def app_mount_points(self):
        @login_required
        def planner_view(request):
            return render(request, self.template_path("planner.html"), {})

        return [
            MountPoint('$', planner_view),
        ]

    def api_mount_points(self):
        return [
            MountPoint('health$', HealthView.as_view()),
            MountPoint('polygon/$', PolygonView.as_view()),
            MountPoint('spiral/$', SpiralView.as_view()),
            MountPoint('orbit/$', OrbitView.as_view()),
            MountPoint('cable/$', CableView.as_view()),
            MountPoint('corkscrew/$', CorkscrewView.as_view()),
            MountPoint('grid/$', GridView.as_view()),
            MountPoint('missions/$', MissionListView.as_view()),
            MountPoint(r'mission/(?P<mid>[A-Za-z0-9]+)/$', MissionDetailView.as_view()),
            MountPoint(r'export/(?P<mid>[A-Za-z0-9]+)\.kml$', ExportKmlView.as_view()),
            MountPoint(r'export/(?P<mid>[A-Za-z0-9]+)\.geojson$', ExportGeoJsonView.as_view()),
            # Drone model registry
            MountPoint(r'drone-models/$', DroneModelsView.as_view()),
            MountPoint(r'drone-models/(?P<model_id>[A-Za-z0-9_]+)/$', DroneModelDetailView.as_view()),
            MountPoint(r'drone-models/(?P<model_id>[A-Za-z0-9_]+)/validate/$', DroneModelValidateView.as_view()),
            # Projects
            MountPoint(r'projects/$', ProjectListCreateView.as_view()),
            MountPoint(r'projects/(?P<pid>[A-Za-z0-9]+)/$', ProjectDetailView.as_view()),
            MountPoint(r'projects/(?P<pid>[A-Za-z0-9]+)/add-mission/$', ProjectAddMissionView.as_view()),
            MountPoint(r'projects/(?P<pid>[A-Za-z0-9]+)/export\.kmz$', ProjectExportKmzView.as_view()),
            MountPoint(r'projects/(?P<pid>[A-Za-z0-9]+)/export\.kml$', ProjectExportKmlView.as_view()),
        ]

    def include_js_files(self):
        # main.js dynamically loads ol.js via loadOL() (CDN → local fallback),
        # so we don't need to register it here.
        return ['main.js']

    def include_css_files(self):
        # ol.css is also loaded by main.js (loadOL) so it loads in the right
        # order after ol.js resolves.
        return []
