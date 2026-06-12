"""
REST API for the Flight Planner plugin.

Mounts under /api/plugins/flight-planner/...

Persistence: PostgreSQL via Django ORM (FlightProject / FlightMission in
coreplugins.flight-planner.models). Replaces the previous disk-based JSON
files at ${MEDIA_ROOT}/plugins/flight-planner/<id>/mission.json. The DB
approach is multi-worker safe — gunicorn shares the same PostgreSQL
connection pool across all worker processes.

Endpoints (POST except where noted):
  /api/plugins/flight-planner/polygon/      boustrophedon survey of arbitrary polygon
  /api/plugins/flight-planner/spiral/       Archimedean spiral
  /api/plugins/flight-planner/orbit/        circle around POI
  /api/plugins/flight-planner/cable/        cable cam along polyline
  /api/plugins/flight-planner/corkscrew/    helical climb
  /api/plugins/flight-planner/grid/         axis-aligned rectangle survey
  /api/plugins/flight-planner/mission/<id>/        GET  mission detail
  /api/plugins/flight-planner/missions/             GET  list all missions
  /api/plugins/flight-planner/export/<id>.kml       GET  KML file (regenerated)
  /api/plugins/flight-planner/export/<id>.geojson   GET  GeoJSON file (regenerated)
  /api/plugins/flight-planner/projects/             GET / POST  list / create
  /api/plugins/flight-planner/projects/<id>/        GET / PUT / DELETE
  /api/plugins/flight-planner/projects/<id>/add-mission/        POST
  /api/plugins/flight-planner/projects/<id>/export.kmz           GET
  /api/plugins/flight-planner/projects/<id>/export.kml           GET
  /api/plugins/flight-planner/drone-models/         GET
  /api/plugins/flight-planner/drone-models/<id>/    GET / validate
  /api/plugins/flight-planner/health               GET
"""

from __future__ import annotations

import importlib
import json
import os
import uuid
from typing import List, Optional

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers, status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

# Plugin models live in a dash-named package, so the regular `import`
# statement can't reach them. We use importlib, which handles dashes fine.
# This is also how WebODM's plugin loader does it
# (see app/plugins/functions.py:get_plugins).
_fp_models = importlib.import_module("coreplugins.flight-planner.models")
FlightProject = _fp_models.FlightProject
FlightMission = _fp_models.FlightMission


# -----------------------------------------------------------------------------
# CSRF + auth
# -----------------------------------------------------------------------------

class CsrfExemptSessionAuthentication(SessionAuthentication):
    """Session auth that does NOT enforce CSRF.

    We override enforce_csrf to a no-op (the right way to disable CSRF in
    DRF). Setting `enforce_csrf = False` directly would replace the method
    with a bool and break calls.
    """

    def enforce_csrf(self, request):
        return  # CSRF already disabled by the @csrf_exempt on dispatch()


# -----------------------------------------------------------------------------
# Algorithm imports (no Django dependency)
# -----------------------------------------------------------------------------

from .algorithms import (  # noqa: E402
    Waypoint, polygon_survey, spiral, orbit, cable_cam,
    corkscrew, panel_grid, mission_stats, waypoints_bounds,
)
from .kml_export import waypoints_to_kml, waypoints_to_geojson  # noqa: E402


# -----------------------------------------------------------------------------
# WPML field mixin — adds the 14 user-tunable WPML mission-level parameters
# to every generate-endpoint serializer. Stored under params['wpml'].
# -----------------------------------------------------------------------------

WPML_SERIALIZER_FIELDS = {
    # Mission-level
    "fly_to_wayline_mode":    serializers.ChoiceField(
        default="safely", choices=["safely", "directly"], required=False),
    "finish_action":          serializers.ChoiceField(
        default="", choices=["", "goHome", "land", "hover", "backToFirst"], required=False, allow_blank=True),
    "exit_on_rc_low":         serializers.ChoiceField(
        default="", choices=["", "goHome", "land", "hover"], required=False, allow_blank=True),
    "exit_on_signal_lost":    serializers.ChoiceField(
        default="", choices=["", "goHome", "land", "hover", "continue"], required=False, allow_blank=True),
    "takeoff_security_height": serializers.IntegerField(
        default=20, min_value=5, max_value=150, required=False),
    "global_speed":           serializers.FloatField(
        required=False, allow_null=True, min_value=0.5, max_value=30),
    "cali_flight_enable":     serializers.IntegerField(
        default=0, min_value=0, max_value=1, required=False),

    # Wayline-level
    "height_mode":            serializers.ChoiceField(
        default="relativeToStartPoint",
        choices=["relativeToStartPoint", "WGS84", "AGL"], required=False),
    "ellipsoid_height":       serializers.FloatField(default=0, required=False),
    "heading_mode":           serializers.ChoiceField(
        default="auto", choices=["auto", "fixed", "manual"], required=False),
    "gimbal_mode":            serializers.ChoiceField(
        default="useRouteSetting",
        choices=["useRouteSetting", "manual", "fixed"], required=False),
    "auto_flight_speed":      serializers.IntegerField(
        default=0, min_value=0, max_value=20, required=False),
    "turn_mode_override":     serializers.ChoiceField(
        default="",
        choices=["", "toPoint", "toPointAndPassWithContinuityCurvature"],
        required=False, allow_blank=True),

    # Camera / payload
    "payload_position_index": serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=5),
    "camera_type_override":   serializers.CharField(
        default="", required=False, allow_blank=True, max_length=64),
    "lens_index":             serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=4),

    # Action / trigger (controls photo capture cadence along the route)
    "action_trigger_type":    serializers.ChoiceField(
        default="reachPoint",
        choices=["reachPoint", "multipleTiming", "betweenAdjacentPoints", "reachEnd"],
        required=False),
    "photo_interval":         serializers.FloatField(
        required=False, allow_null=True, min_value=0.1, max_value=60),
    "action_group_mode":      serializers.ChoiceField(
        default="sequence", choices=["sequence", "parallel"], required=False),
    "file_suffix_prefix":     serializers.CharField(
        default="DJI", required=False, max_length=32),
}


class WPMLParamsMixin:
    """Adds the WPML_SERIALIZER_FIELDS to a serializer subclass."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Don't use base_fields — it's a binding-time dict that
        # __init_subclass__ runs before the metaclass has fully built it.
        existing = getattr(cls, "_declared_fields", {}) or {}
        for name, field in WPML_SERIALIZER_FIELDS.items():
            if name in existing:
                continue
            # Bind the field to the class so validators resolve correctly.
            field._bind() if hasattr(field, "_bind") else None
            field.parent = cls
            existing[name] = field
        cls._declared_fields = existing


# -----------------------------------------------------------------------------
# Persistence helpers — Django ORM
# -----------------------------------------------------------------------------

def _mission_to_dict(m: FlightMission) -> dict:
    """Serialise a FlightMission row to the same shape the old disk JSON had.

    Keeps the front-end / KMZ / KML consumers working without changes.
    """
    return {
        "id": m.id,
        "name": m.name,
        "kind": m.kind,
        "params": m.params or {},
        "waypoints": m.waypoints or [],
        "bounds": m.bounds or [],
        "stats": m.stats or {},
        "project_id": m.project_id,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _project_to_dict(p: FlightProject) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "drone_model": p.drone_model,
        "description": p.description or "",
        "mission_ids": [m.id for m in p.missions.all()],
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


# -----------------------------------------------------------------------------
# Serializers
# -----------------------------------------------------------------------------

class LatLonSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lon = serializers.FloatField()


class PolygonRequestSerializer(WPMLParamsMixin, serializers.Serializer):
    polygon = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2),
        min_length=3,
    )
    altitude = serializers.FloatField(default=50.0, min_value=1, max_value=500)
    speed = serializers.FloatField(default=5.0, min_value=0.1, max_value=20)
    line_spacing = serializers.FloatField(default=30.0, min_value=0.5, max_value=500)
    angle_deg = serializers.FloatField(default=0.0, min_value=0, max_value=180)
    overlap = serializers.FloatField(default=0.7, min_value=0, max_value=1)
    front_overlap = serializers.FloatField(default=0.8, min_value=0, max_value=1)
    gimbal_pitch = serializers.IntegerField(default=-90, min_value=-90, max_value=30)
    action = serializers.ChoiceField(
        default="photo",
        choices=["none", "photo", "video_start", "video_stop", "hover",
                 "gimbal_rotate", "rotate_yaw", "zoom", "focus"],
    )
    margin = serializers.FloatField(default=0.0, min_value=0, max_value=200)
    name = serializers.CharField(default="Polygon survey", max_length=128)


class SpiralRequestSerializer(WPMLParamsMixin, serializers.Serializer):
    center = LatLonSerializer()
    start_radius = serializers.FloatField(default=10.0, min_value=1, max_value=2000)
    end_radius = serializers.FloatField(default=100.0, min_value=1, max_value=5000)
    turns = serializers.FloatField(default=5.0, min_value=0.5, max_value=50)
    start_alt = serializers.FloatField(default=30.0, min_value=1, max_value=500)
    end_alt = serializers.FloatField(default=80.0, min_value=1, max_value=500)
    speed = serializers.FloatField(default=4.0, min_value=0.1, max_value=20)
    gimbal_pitch = serializers.IntegerField(default=-90, min_value=-90, max_value=30)
    points_per_turn = serializers.IntegerField(default=36, min_value=6, max_value=360)
    inward = serializers.BooleanField(default=False)
    heading_mode = serializers.ChoiceField(
        default="auto", choices=["auto", "center", "tangent"]
    )
    name = serializers.CharField(default="Spiral", max_length=128)


class OrbitRequestSerializer(WPMLParamsMixin, serializers.Serializer):
    center = LatLonSerializer()
    radius = serializers.FloatField(default=50.0, min_value=5, max_value=2000)
    altitude = serializers.FloatField(default=40.0, min_value=1, max_value=500)
    speed = serializers.FloatField(default=3.0, min_value=0.1, max_value=20)
    points = serializers.IntegerField(default=24, min_value=6, max_value=360)
    gimbal_pitch = serializers.IntegerField(default=-30, min_value=-90, max_value=30)
    clockwise = serializers.BooleanField(default=True)
    start_angle_deg = serializers.FloatField(default=0.0)
    name = serializers.CharField(default="Orbit", max_length=128)


class CableRequestSerializer(WPMLParamsMixin, serializers.Serializer):
    path = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2),
        min_length=2,
    )
    samples = serializers.IntegerField(default=20, min_value=2, max_value=2000)
    altitude = serializers.FloatField(default=50.0, min_value=1, max_value=500)
    start_alt = serializers.FloatField(required=False, allow_null=True)
    end_alt = serializers.FloatField(required=False, allow_null=True)
    speed = serializers.FloatField(default=4.0, min_value=0.1, max_value=20)
    gimbal_pitch = serializers.IntegerField(default=-90, min_value=-90, max_value=30)
    repeat = serializers.IntegerField(default=1, min_value=1, max_value=20)
    name = serializers.CharField(default="Cable cam", max_length=128)


class CorkscrewRequestSerializer(WPMLParamsMixin, serializers.Serializer):
    center = LatLonSerializer()
    radius = serializers.FloatField(default=30.0, min_value=1, max_value=500)
    start_alt = serializers.FloatField(default=20.0, min_value=1, max_value=500)
    end_alt = serializers.FloatField(default=100.0, min_value=1, max_value=500)
    turns = serializers.FloatField(default=6.0, min_value=0.5, max_value=50)
    speed = serializers.FloatField(default=3.0, min_value=0.1, max_value=20)
    points_per_turn = serializers.IntegerField(default=24, min_value=6, max_value=360)
    gimbal_pitch = serializers.IntegerField(default=-30, min_value=-90, max_value=30)
    name = serializers.CharField(default="Corkscrew", max_length=128)


class GridRequestSerializer(WPMLParamsMixin, serializers.Serializer):
    center = LatLonSerializer()
    width = serializers.FloatField(default=200.0, min_value=10, max_value=10000)
    height = serializers.FloatField(default=200.0, min_value=10, max_value=10000)
    altitude = serializers.FloatField(default=50.0, min_value=1, max_value=500)
    speed = serializers.FloatField(default=5.0, min_value=0.1, max_value=20)
    line_spacing = serializers.FloatField(default=30.0, min_value=0.5, max_value=500)
    angle_deg = serializers.FloatField(default=0.0, min_value=0, max_value=180)
    overlap = serializers.FloatField(default=0.7, min_value=0, max_value=1)
    front_overlap = serializers.FloatField(default=0.8, min_value=0, max_value=1)
    gimbal_pitch = serializers.IntegerField(default=-90, min_value=-90, max_value=30)
    action = serializers.ChoiceField(
        default="photo",
        choices=["none", "photo", "video_start", "video_stop", "hover",
                 "gimbal_rotate", "rotate_yaw", "zoom", "focus"],
    )
    name = serializers.CharField(default="Grid survey", max_length=128)


# -----------------------------------------------------------------------------
# Generic generator view
# -----------------------------------------------------------------------------

class _GenerateView(APIView):
    """Base class: validate serializer, run algorithm, save mission, return."""
    serializer_class = None
    algorithm = None  # callable
    permission_classes = [AllowAny]
    authentication_classes = [CsrfExemptSessionAuthentication, BasicAuthentication]

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        s = self.serializer_class(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            wps = self.algorithm(**self._algo_kwargs(d))
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"internal: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        name = d.get("name", "Mission")
        # Pull WPML fields into a nested dict; everything else is mission-level
        # geometry/algorithm params.
        wpml_keys = set(WPML_SERIALIZER_FIELDS.keys())
        wpml = {k: d[k] for k in wpml_keys if k in d}
        algo_params = {k: v for k, v in d.items()
                       if k not in wpml_keys and k != "name"}
        # Flatten LatLonSerializer results
        for k, v in list(algo_params.items()):
            if hasattr(v, "lat"):
                algo_params[k] = {"lat": v.lat, "lon": v.lon}
        params = {"algo": algo_params, "wpml": wpml}
        kind = self.serializer_class.__name__.replace("RequestSerializer", "").lower()

        bounds = waypoints_bounds(wps)
        stats = mission_stats(wps)
        m = FlightMission.objects.create(
            name=name,
            kind=kind,
            params=params,
            waypoints=[w.to_dict() for w in wps],
            bounds=list(bounds),
            stats=stats,
        )
        return Response(_mission_to_dict(m), status=status.HTTP_200_OK)

    def _algo_kwargs(self, d):
        return d


class PolygonView(_GenerateView):
    serializer_class = PolygonRequestSerializer
    algorithm = staticmethod(polygon_survey)

    def _algo_kwargs(self, d):
        return dict(
            polygon_coords=[(lat, lon) for lat, lon in d["polygon"]],
            altitude=d["altitude"],
            speed=d["speed"],
            line_spacing=d["line_spacing"],
            angle_deg=d["angle_deg"],
            overlap=d["overlap"],
            gimbal_pitch=d["gimbal_pitch"],
            action=d["action"],
            margin=d["margin"],
        )


class SpiralView(_GenerateView):
    serializer_class = SpiralRequestSerializer
    algorithm = staticmethod(spiral)

    def _algo_kwargs(self, d):
        return dict(
            center_lat=d["center"]["lat"],
            center_lon=d["center"]["lon"],
            start_radius=d["start_radius"],
            end_radius=d["end_radius"],
            turns=d["turns"],
            start_alt=d["start_alt"],
            end_alt=d["end_alt"],
            speed=d["speed"],
            gimbal_pitch=d["gimbal_pitch"],
            points_per_turn=d["points_per_turn"],
            inward=d["inward"],
            heading_mode=d["heading_mode"],
        )


class OrbitView(_GenerateView):
    serializer_class = OrbitRequestSerializer
    algorithm = staticmethod(orbit)

    def _algo_kwargs(self, d):
        return dict(
            center_lat=d["center"]["lat"],
            center_lon=d["center"]["lon"],
            radius=d["radius"],
            altitude=d["altitude"],
            speed=d["speed"],
            points=d["points"],
            gimbal_pitch=d["gimbal_pitch"],
            clockwise=d["clockwise"],
            start_angle_deg=d["start_angle_deg"],
        )


class CableView(_GenerateView):
    serializer_class = CableRequestSerializer
    algorithm = staticmethod(cable_cam)

    def _algo_kwargs(self, d):
        return dict(
            path=[(lat, lon) for lat, lon in d["path"]],
            samples=d["samples"],
            altitude=d["altitude"],
            start_alt=d.get("start_alt"),
            end_alt=d.get("end_alt"),
            speed=d["speed"],
            gimbal_pitch=d["gimbal_pitch"],
            repeat=d["repeat"],
        )


class CorkscrewView(_GenerateView):
    serializer_class = CorkscrewRequestSerializer
    algorithm = staticmethod(corkscrew)

    def _algo_kwargs(self, d):
        return dict(
            center_lat=d["center"]["lat"],
            center_lon=d["center"]["lon"],
            radius=d["radius"],
            start_alt=d["start_alt"],
            end_alt=d["end_alt"],
            turns=d["turns"],
            speed=d["speed"],
            points_per_turn=d["points_per_turn"],
            gimbal_pitch=d["gimbal_pitch"],
        )


class GridView(_GenerateView):
    serializer_class = GridRequestSerializer
    algorithm = staticmethod(panel_grid)

    def _algo_kwargs(self, d):
        return dict(
            center_lat=d["center"]["lat"],
            center_lon=d["center"]["lon"],
            width=d["width"],
            height=d["height"],
            altitude=d["altitude"],
            speed=d["speed"],
            line_spacing=d["line_spacing"],
            angle_deg=d["angle_deg"],
            gimbal_pitch=d["gimbal_pitch"],
            action=d["action"],
        )


# -----------------------------------------------------------------------------
# Read-only / export endpoints
# -----------------------------------------------------------------------------

class MissionDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, mid):
        try:
            m = FlightMission.objects.get(pk=mid)
        except FlightMission.DoesNotExist:
            return Response({"error": "not found"}, status=404)
        return Response(_mission_to_dict(m))

    def patch(self, request, mid):
        """Update mutable mission fields (name, waypoints).

        Body shape: {"name": "...", "waypoints": [{lat, lon, alt, ...}]}
        Waypoints are merged into the existing record (preserves kind/params/stats).
        """
        try:
            m = FlightMission.objects.get(pk=mid)
        except FlightMission.DoesNotExist:
            return Response({"error": "not found"}, status=404)
        d = request.data or {}
        if "name" in d and d["name"]:
            m.name = str(d["name"])[:128]
        if "waypoints" in d and isinstance(d["waypoints"], list):
            new_wps = []
            for idx, w in enumerate(d["waypoints"]):
                if not isinstance(w, dict):
                    continue
                try:
                    new_wps.append(Waypoint(
                        index=idx,
                        lat=float(w["lat"]),
                        lon=float(w["lon"]),
                        alt=float(w.get("alt", 60)),
                        speed=float(w.get("speed", 5)),
                        gimbal_pitch=int(w.get("gimbal_pitch", -90)),
                        heading=w.get("heading"),
                        heading_mode=w.get("heading_mode"),
                        action=w.get("action", "photo"),
                        hold_time=float(w.get("hold_time", 0)),
                    ).to_dict())
                except (KeyError, ValueError, TypeError):
                    continue
            if new_wps:
                m.waypoints = new_wps
                # Recompute bounds + stats.
                if new_wps:
                    m.bounds = [
                        min(w["lat"] for w in new_wps),
                        min(w["lon"] for w in new_wps),
                        max(w["lat"] for w in new_wps),
                        max(w["lon"] for w in new_wps),
                    ]
                    m.stats = {
                        "waypoints": len(new_wps),
                        "distance_m": 0.0,   # recompute below if needed
                        "area_m2": (m.stats or {}).get("area_m2", 0.0),
                    }
        m.save()
        return Response(_mission_to_dict(m))

    def delete(self, request, mid):
        try:
            m = FlightMission.objects.get(pk=mid)
        except FlightMission.DoesNotExist:
            return Response({"error": "not found"}, status=404)
        m.delete()
        return Response(status=204)


class MissionListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        qs = FlightMission.objects.all()
        # Optional project filter
        pid = request.query_params.get("project")
        if pid:
            qs = qs.filter(project_id=pid)
        # Optional kind filter
        kind = request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        return Response({
            "count": qs.count(),
            "missions": [
                {
                    "id": m.id,
                    "name": m.name,
                    "kind": m.kind,
                    "project_id": m.project_id,
                    "waypoints": (m.stats or {}).get("waypoints", len(m.waypoints or [])),
                    "distance_m": (m.stats or {}).get("distance_m", 0),
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                }
                for m in qs.order_by("-updated_at")
            ],
        })


def _mission_waypoints_to_objects(m: FlightMission) -> List[Waypoint]:
    out: List[Waypoint] = []
    for idx, w in enumerate(m.waypoints or []):
        if not isinstance(w, dict):
            continue
        try:
            out.append(Waypoint(
                index=idx,
                lat=float(w["lat"]),
                lon=float(w["lon"]),
                alt=float(w.get("alt", 50)),
                speed=float(w.get("speed", 5)),
                gimbal_pitch=int(w.get("gimbal_pitch", -90)),
                heading=w.get("heading"),
                heading_mode=w.get("heading_mode"),
                action=w.get("action", "photo"),
                hold_time=float(w.get("hold_time", 0)),
                action_pitch=w.get("action_pitch"),
                focal_length=float(w.get("focal_length", 24.0)),
                focus_x=float(w.get("focus_x", 0.5)),
                focus_y=float(w.get("focus_y", 0.5)),
                hyperlateral=int(w.get("hyperlateral", 0)),
                hypervertical=int(w.get("hypervertical", 0)),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return out


class ExportKmlView(APIView):
    """GET /export/<id>.kml — generated on the fly from DB waypoints."""
    permission_classes = [AllowAny]

    def get(self, request, mid):
        try:
            m = FlightMission.objects.get(pk=mid)
        except FlightMission.DoesNotExist:
            return Response({"error": "not found"}, status=404)
        wps = _mission_waypoints_to_objects(m)
        if not wps:
            return Response({"error": "mission has no waypoints"}, status=400)
        kml_str = waypoints_to_kml(wps, name=m.name)
        resp = HttpResponse(kml_str, content_type="application/vnd.google-earth.kml+xml")
        resp["Content-Disposition"] = f'attachment; filename="{mid}.kml"'
        return resp


class ExportGeoJsonView(APIView):
    """GET /export/<id>.geojson — generated on the fly from DB waypoints."""
    permission_classes = [AllowAny]

    def get(self, request, mid):
        try:
            m = FlightMission.objects.get(pk=mid)
        except FlightMission.DoesNotExist:
            return Response({"error": "not found"}, status=404)
        wps = _mission_waypoints_to_objects(m)
        if not wps:
            return Response({"error": "mission has no waypoints"}, status=400)
        geo = waypoints_to_geojson(wps, name=m.name)
        resp = HttpResponse(geo, content_type="application/geo+json")
        resp["Content-Disposition"] = f'attachment; filename="{mid}.geojson"'
        return resp


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            "status": "ok",
            "plugin": "flight-planner",
            "projects": FlightProject.objects.count(),
            "missions": FlightMission.objects.count(),
        })


# -----------------------------------------------------------------------------
# Drone model registry endpoints
# -----------------------------------------------------------------------------

class DroneModelsView(APIView):
    """GET /drone-models/  — list all supported DJI models."""
    permission_classes = [AllowAny]

    def get(self, request):
        from . import drone_models
        return Response({
            "count": len(drone_models.DRONE_MODELS),
            "models": drone_models.list_models(),
        })


class DroneModelDetailView(APIView):
    """GET /drone-models/<id>/  — get one model's full specification."""
    permission_classes = [AllowAny]

    def get(self, request, model_id):
        from . import drone_models
        m = drone_models.get_model(model_id)
        if not m:
            return Response({"error": f"unknown model: {model_id}"}, status=404)
        return Response(drone_models.model_summary(m))


class DroneModelValidateView(APIView):
    """POST /drone-models/<id>/validate/  — validate mission params against
    the model's flight envelope."""
    permission_classes = [AllowAny]

    def post(self, request, model_id):
        from . import drone_models
        m = drone_models.get_model(model_id)
        if not m:
            return Response({"error": f"unknown model: {model_id}"}, status=404)
        errs = drone_models.validate_params_for_model(model_id, request.data or {})
        return Response({
            "model_id": model_id,
            "valid": len(errs) == 0,
            "errors": errs,
        })


# -----------------------------------------------------------------------------
# Project endpoints (a project = name + drone model + list of missions)
# -----------------------------------------------------------------------------

class ProjectSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=1, max_length=128)
    drone_model = serializers.CharField(min_length=1, max_length=64)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    mission_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )


class ProjectListCreateView(APIView):
    """GET /projects/  POST /projects/"""
    permission_classes = [AllowAny]
    authentication_classes = [CsrfExemptSessionAuthentication, BasicAuthentication]

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request):
        qs = FlightProject.objects.all().order_by("-updated_at")
        return Response({
            "count": qs.count(),
            "projects": [
                {
                    "id": p.id,
                    "name": p.name,
                    "drone_model": p.drone_model,
                    "description": p.description or "",
                    "mission_count": p.missions.count(),
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                }
                for p in qs
            ],
        })

    def post(self, request):
        s = ProjectSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        from . import drone_models
        if not drone_models.get_model(d["drone_model"]):
            return Response(
                {"error": f"unknown drone_model: {d['drone_model']}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        p = FlightProject.objects.create(
            name=d["name"],
            drone_model=d["drone_model"],
            description=d.get("description", ""),
        )
        # Attach any pre-existing mission_ids
        for mid in d.get("mission_ids", []):
            FlightMission.objects.filter(pk=mid).update(project=p)
        return Response(_project_to_dict(p), status=status.HTTP_201_CREATED)


class ProjectDetailView(APIView):
    """GET/PUT/DELETE /projects/<id>/"""
    permission_classes = [AllowAny]
    authentication_classes = [CsrfExemptSessionAuthentication, BasicAuthentication]

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request, pid):
        try:
            p = FlightProject.objects.get(pk=pid)
        except FlightProject.DoesNotExist:
            return Response({"error": "not found"}, status=404)
        return Response(_project_to_dict(p))

    def put(self, request, pid):
        try:
            p = FlightProject.objects.get(pk=pid)
        except FlightProject.DoesNotExist:
            return Response({"error": "not found"}, status=404)
        s = ProjectSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if "name" in d:
            p.name = d["name"]
        if "drone_model" in d:
            from . import drone_models
            if not drone_models.get_model(d["drone_model"]):
                return Response(
                    {"error": f"unknown drone_model: {d['drone_model']}"},
                    status=400,
                )
            p.drone_model = d["drone_model"]
        if "description" in d:
            p.description = d["description"]
        p.save()
        if "mission_ids" in d:
            # Detach everything, then re-attach listed ones.
            FlightMission.objects.filter(project=p).update(project=None)
            for mid in d["mission_ids"]:
                FlightMission.objects.filter(pk=mid).update(project=p)
        return Response(_project_to_dict(p))

    def delete(self, request, pid):
        try:
            p = FlightProject.objects.get(pk=pid)
        except FlightProject.DoesNotExist:
            return Response({"error": "not found"}, status=404)
        p.delete()  # cascades to missions via FK
        return Response(status=204)


class ProjectAddMissionView(APIView):
    """POST /projects/<id>/add-mission/  body: {"mission_id": "..."}"""
    permission_classes = [AllowAny]
    authentication_classes = [CsrfExemptSessionAuthentication, BasicAuthentication]

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request, pid):
        try:
            p = FlightProject.objects.get(pk=pid)
        except FlightProject.DoesNotExist:
            return Response({"error": "project not found"}, status=404)
        mid = request.data.get("mission_id")
        if not mid:
            return Response({"error": "mission_id required"}, status=400)
        if not FlightMission.objects.filter(pk=mid).exists():
            return Response({"error": f"mission {mid} not found"}, status=404)
        FlightMission.objects.filter(pk=mid).update(project=p)
        p.save()  # bump updated_at
        return Response(_project_to_dict(p))


def _aggregate_project_waypoints(p: FlightProject) -> tuple:
    """Aggregate waypoints from all missions in a project.

    Newest mission's WPML params win. Returns (waypoints, wpml_params, algo_params).
    """
    waypoints: List[Waypoint] = []
    idx = 0
    wpml_params: dict = {}
    algo_params: dict = {"speed": 5.0, "altitude": 50.0, "gimbal_pitch": -90,
                         "heading_mode": "auto", "gimbal_mode": "useRouteSetting"}
    for m in p.missions.all().order_by("-updated_at"):
        mp = m.params or {}
        if isinstance(mp.get("wpml"), dict):
            wpml_params.update(mp["wpml"])
        if isinstance(mp.get("algo"), dict):
            algo_params.update(mp["algo"])
        for w in m.waypoints or []:
            try:
                waypoints.append(Waypoint(
                    index=idx,
                    lat=float(w["lat"]),
                    lon=float(w["lon"]),
                    alt=float(w.get("alt", algo_params.get("altitude", 50))),
                    speed=float(w.get("speed", algo_params.get("speed", 5))),
                    gimbal_pitch=int(w.get("gimbal_pitch", algo_params.get("gimbal_pitch", -90))),
                    heading=w.get("heading"),
                    heading_mode=w.get("heading_mode"),
                    action=w.get("action", "photo"),
                    hold_time=float(w.get("hold_time", 0.0)),
                    action_pitch=w.get("action_pitch"),
                    focal_length=float(w.get("focal_length", 24.0)),
                    focus_x=float(w.get("focus_x", 0.5)),
                    focus_y=float(w.get("focus_y", 0.5)),
                    hyperlateral=int(w.get("hyperlateral", 0)),
                    hypervertical=int(w.get("hypervertical", 0)),
                ))
            except (KeyError, ValueError, TypeError):
                continue
            idx += 1
    return waypoints, wpml_params, algo_params


class ProjectExportKmzView(APIView):
    """GET /projects/<id>/export.kmz  — download a model-specific KMZ."""
    permission_classes = [AllowAny]

    def get(self, request, pid):
        try:
            p = FlightProject.objects.get(pk=pid)
        except FlightProject.DoesNotExist:
            return Response({"error": "project not found"}, status=404)

        from . import drone_models, kmz_export
        model = drone_models.get_model(p.drone_model)
        if not model:
            return Response(
                {"error": f"project's drone_model {p.drone_model} not found"},
                status=400,
            )

        waypoints, wpml_params, _ = _aggregate_project_waypoints(p)
        if not waypoints:
            return Response({"error": "project has no waypoints"}, status=400)

        kmz_bytes = kmz_export.mission_to_kmz(
            waypoints, p.name, p.drone_model, wpml_params
        )
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in p.name)
        resp = HttpResponse(kmz_bytes, content_type="application/vnd.google-earth.kmz")
        resp["Content-Disposition"] = f'attachment; filename="{safe_name}_{p.drone_model}.kmz"'
        return resp


class ProjectExportKmlView(APIView):
    """GET /projects/<id>/export.kml  — vendor-neutral KML 2.2 (no WPML)."""
    permission_classes = [AllowAny]

    def get(self, request, pid):
        try:
            p = FlightProject.objects.get(pk=pid)
        except FlightProject.DoesNotExist:
            return Response({"error": "project not found"}, status=404)
        from . import kml_export
        waypoints, _, _ = _aggregate_project_waypoints(p)
        if not waypoints:
            return Response({"error": "project has no waypoints"}, status=400)
        kml_str = kml_export.waypoints_to_kml(waypoints, name=p.name)
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in p.name)
        resp = HttpResponse(kml_str, content_type="application/vnd.google-earth.kml+xml")
        resp["Content-Disposition"] = f'attachment; filename="{safe_name}.kml"'
        return resp
