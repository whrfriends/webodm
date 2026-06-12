"""
Bridge Database REST API for the road-attributes WebODM plugin.

The page (originally built for road inspection) is now repurposed as a
"桥梁数据库" (bridge database) UI. All read/write operations hit the
existing `bridge.*` PostgreSQL schema directly via raw SQL — no Django
ORM model is defined for these tables (they predate the plugin).

Endpoints (mounted at /api/plugins/road-attributes/<path>):

  GET    /health/                              - liveness + bridge count
  GET    /meta/                                - distinct values for filter dropdowns
  GET    /bridges/                             - paginated list with column filters + search
  POST   /bridges/                             - create a new bridge card
  GET    /bridges/<id>/                        - single bridge, all 155 fields
  PATCH  /bridges/<id>/                        - update fields
  DELETE /bridges/<id>/                        - delete (cascade to sub-tables)
  GET    /bridges/<id>/<subtable>/             - one of:
                                                 evaluations, piers, bearings,
                                                 main-beams, expansion-joints,
                                                 diseases, archives
  GET    /bridges/export/                      - CSV download (current filter set)
  GET    /bridges/stats/                       - aggregate counts (for the stats tab)
  POST   /bridges/<id>/photos/                 - upload general/front photo (multipart)
  DELETE /bridges/<id>/photos/<kind>/          - clear general or front photo
  GET    /placeholders/<tab>/                  - placeholder payload for the 4 other tabs
"""
import csv
import io
import json
import os
import uuid

from django.conf import settings
from django.db import connection
from django.http import HttpResponse, JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


# ============================================================================
# List-view columns (the 13 shown in the main data table).
# Each entry: (sql_column, display_label, kind)
#   kind: 'text' (case-insensitive contains filter),
#         'enum' (exact match on distinct value),
#         'number' (numeric range — not used yet but reserved),
#         'rating' (renders as a circular badge)
# ============================================================================
LIST_COLUMNS = [
    ("eval_level",          "评定等级",    "rating"),
    ("route_id",            "线路编号",    "enum"),
    ("route_name",          "线路名称",    "text"),
    ("bridge_id_code",      "桥梁编号",    "text"),
    ("bridge_name",         "桥梁名称",    "text"),
    ("length_m",            "桥梁全长(米)", "text"),
    ("max_span_m",          "最大跨径(米)", "text"),
    ("stake_no",            "桥位桩号",    "text"),
    ("design_stake_no",     "设计桩号",    "text"),
    ("bridge_type",         "桥梁类型",    "enum"),
    ("span_category",       "跨径分类",    "enum"),
    ("longitude",           "经度",        "text"),
    ("latitude",            "纬度",        "text"),
    # Photo thumbnail (not user-filterable, but included in the list SELECT
    # so the UI column can render an <img> without a second round-trip).
    ("general_photo_url",   "照片",        "photo"),
]
LIST_COL_BY_KEY = {c[0]: c for c in LIST_COLUMNS}


# Sub-tables with a real bridge_card_id FK.
SUBTABLES = {
    "evaluations":       ("bridge_evaluations",       "评定记录"),
    "piers":             ("bridge_piers",             "桥墩"),
    "bearings":          ("bridge_bearings",          "支座"),
    "main-beams":        ("bridge_main_beams",        "主梁/桥面系"),
    "expansion-joints":  ("bridge_expansion_joints",  "伸缩缝"),
    "diseases":          ("bridge_diseases",          "病害"),
    "archives":          ("bridge_archives",          "档案"),
}
SUBTABLES_BY_ID = {t: t for t, _ in SUBTABLES.values()}


# Other 4 tabs in the UI: no underlying tables, return placeholders.
PLACEHOLDER_TABS = {"tunnels": "隧道", "culverts": "涵洞", "slopes": "边坡", "road-segments": "路段"}


# Columns allowed in POST/PATCH payloads (everything else is computed / system-managed).
EDITABLE_COLUMNS = {c for c, _, _ in LIST_COLUMNS} | {
    "admin_code", "location", "township", "admin_id", "tech_id",
    "route_level", "secondary_route", "ramp_route_id", "ramp_stake_value",
    "is_cross_province", "connected_province", "report_code",
    "function_type", "bridge_nature", "toll_nature", "project_company",
    "is_mof_subsidy", "engineer_nature",
    "crossed_obj_type", "crossed_road_name",
    "crossed_obj_type2", "crossed_road_name2",
    "crossed_obj_type3", "crossed_road_name3", "crossed_road_stake",
    "underpass_name", "interchange_cross_way", "is_interchange",
    "interchange_type", "interchange_form",
    "is_border_river_bridge", "is_water_source_bridge",
    "total_width_m", "deck_net_width", "lane_width_m", "sidewalk_width_m",
    "bridge_width_count", "lane_count", "bridge_height", "bridge_slope",
    "curve_radius", "nav_clearance", "bridge_height_limit",
    "std_deck_clearance_m", "actual_deck_clearance_m",
    "std_under_clearance_m", "actual_under_clearance_m", "over_clearance_m",
    "approach_width_m", "approach_road_width_m", "approach_line_type",
    "approach_curve", "deck_elevation_m", "design_load", "pass_load",
    "seismic_level", "peak_acceleration", "design_flood_level",
    "history_flood_level", "design_flood_freq", "normal_water_level",
    "design_water_level", "deck_pavement", "expansion_joint_type",
    "bearing_type", "median_width_m", "guardrail_height_m", "guardrail_width_m",
    "railing_material", "median_guardrail_level", "side_guardrail_level",
    "anti_collision", "anti_ship_collision", "has_health_monitor",
    "is_attached_pipeline", "is_long_large_bridge", "is_wide_road_narrow_bridge",
    "hole_layout", "total_span_m", "span_count", "is_single_pier",
    "abutment_type", "abutment_material", "pier_type", "pier_material",
    "foundation_type", "foundation_material", "cone_slope", "pier_protection",
    "regulating_structure", "main_arch", "cable_tower", "spandrel_structure",
    "main_cable", "stay_cable", "suspender", "tie_bar", "sidewalk_curb",
    "lighting_sign", "wing_wall", "anchorage", "drainage_nav",
    "built_date", "design_life_period", "service_life",
    "subgrade_form", "driving_direction", "curve_slope_feature",
    "start_stake_no", "end_stake_no", "construction_stake",
    "design_unit", "constructor_unit", "supervisor_unit",
    "design_leader", "constructor_leader", "supervisor_leader",
    "maintenance_unit", "maintainer_unit", "supervisory_unit",
    "maintenance_unit_nature", "is_co_maintained",
    "maintenance_start_stake", "maintenance_end_stake", "maintenance_length_m",
    "bridge_status", "maintenance_check_level", "eval_date",
    "reconstruct_part", "is_widened_bridge", "is_in_annual_report",
    "bridge_engineer", "remarks",
    "general_photo_url", "front_photo_url",
    "filled_by", "fill_date", "creator", "created_time",
}
SYSTEM_COLUMNS = {"id", "created_at", "updated_at"}


# ============================================================================
# Columns that need ::numeric cast for ORDER BY.
#
# bridge.bridge_cards is a legacy-imported table where ~95% of "numeric"
# columns are stored as character varying. Lexicographic ORDER BY on a
# varchar column gives the wrong result for any value with a decimal point
# (e.g. '995.55' > '9.8' > '96.04' because '9' > '.' and '9' > '6' in
# ASCII), and silently puts everything >= '10' before everything >= '2'.
#
# Verified against information_schema.columns for bridge.bridge_cards —
# every name listed below is data_type 'character varying'. The cast to
# ::numeric restores correct numeric ordering. Empty strings / non-numeric
# junk cast to NULL, which the NULLS LAST clause sends to the end.
#
# Date columns (built_date, eval_date, fill_date) are intentionally NOT
# listed: 'built_date'/'eval_date' hold ISO date strings ("2024-05-15")
# whose lexicographic order matches chronological order, and 'fill_date'
# is already a real `date` column in the database.
# ============================================================================
NUMERIC_ORDER_COLUMNS = {
    # 长度/跨径 (米)
    "length_m", "max_span_m", "total_span_m", "total_width_m",
    "deck_net_width", "lane_width_m", "sidewalk_width_m",
    "maintenance_length_m",
    # 宽度/高度/净空 (米)
    "bridge_height", "bridge_height_limit",
    "std_deck_clearance_m", "actual_deck_clearance_m",
    "std_under_clearance_m", "actual_under_clearance_m",
    "over_clearance_m",
    "approach_width_m", "approach_road_width_m", "deck_elevation_m",
    "median_width_m", "guardrail_height_m", "guardrail_width_m",
    # 计数
    "bridge_width_count", "lane_count", "span_count",
    # 坡度/半径/导航净空
    "bridge_slope", "cone_slope", "curve_radius", "nav_clearance",
    # 荷载/水位/加速度/频率
    "peak_acceleration", "design_flood_level", "history_flood_level",
    "design_flood_freq", "normal_water_level", "design_water_level",
    # 经纬度
    "longitude", "latitude",
    # 桩号值 (K0+610.539 → "610.539")
    "ramp_stake_value",
    # 设计/使用年限
    "design_life_period", "service_life",
}


# ============================================================================
# Helpers
# ============================================================================
def _query(sql, params=None):
    """Run a SELECT and return list of dict rows. All values JSON-safe."""
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        cols = [c[0] for c in cur.description]
        out = []
        for row in cur.fetchall():
            d = {}
            for col, val in zip(cols, row):
                if val is None:
                    d[col] = None
                elif hasattr(val, "isoformat"):
                    d[col] = val.isoformat()
                elif isinstance(val, (str, int, float, bool)):
                    d[col] = val
                elif isinstance(val, (list, tuple, dict)):
                    d[col] = val
                else:
                    d[col] = str(val)
            out.append(d)
        return out


def _query_one(sql, params=None):
    rows = _query(sql, params)
    return rows[0] if rows else None


def _exec(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])


def _build_filters(request):
    """Parse column filters + global search. Returns (where_sql, params).

    Skips the 'photo' column (general_photo_url is a text URL — searching
    by substring of an image path is never useful) and the synthetic 'id'
    column that is not in LIST_COLUMNS anyway.
    """
    where = []
    params = []
    for col, _, kind in LIST_COLUMNS:
        if kind == "photo":
            continue
        v = request.GET.get(col, "").strip()
        if not v:
            continue
        if kind == "enum":
            where.append(f"{col} = %s")
            params.append(v)
        else:
            where.append(f"{col}::text ILIKE %s")
            params.append(f"%{v}%")
    q = request.GET.get("q", "").strip()
    if q:
        where.append(
            "(bridge_name::text ILIKE %s OR bridge_id_code::text ILIKE %s "
            "OR route_name::text ILIKE %s OR route_id::text ILIKE %s "
            "OR stake_no::text ILIKE %s OR design_stake_no::text ILIKE %s)"
        )
        params.extend([f"%{q}%"] * 6)
    return ("WHERE " + " AND ".join(where)) if where else "", params


# ============================================================================
# Endpoints
# ============================================================================
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def health(request):
    cnt = _query_one("SELECT count(*) AS c FROM bridge.bridge_cards")["c"]
    return Response({"status": "ok", "plugin": "road-attributes", "bridge_count": cnt})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def meta(request):
    """Distinct values for the column-header filter dropdowns."""
    def distinct(col):
        rows = _query(
            f"SELECT DISTINCT {col}::text AS v FROM bridge.bridge_cards "
            f"WHERE {col} IS NOT NULL AND {col}::text <> '' ORDER BY v"
        )
        return [r["v"] for r in rows]
    return Response({
        "eval_levels":    distinct("eval_level"),
        "span_categories": distinct("span_category"),
        "route_ids":      distinct("route_id"),
        "bridge_types":   distinct("bridge_type"),
    })


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def bridges_list(request):
    """GET: paginated list with filters + search + ordering.
    POST: create new bridge (minimal validation)."""
    if request.method == "POST":
        return _create_bridge(request)
    page = max(1, int(request.GET.get("page", 1)))
    page_size = min(100, max(1, int(request.GET.get("page_size", 10))))
    offset = (page - 1) * page_size
    where_sql, params = _build_filters(request)

    # Ordering: ?ordering=route_id,-bridge_name (asc, desc)
    ordering = request.GET.get("ordering", "route_id,bridge_id_code").strip()
    order_parts = []
    for p in [x.strip() for x in ordering.split(",") if x.strip()]:
        direction = "DESC" if p.startswith("-") else "ASC"
        col = p[1:] if p.startswith("-") else p
        # Legacy table stores numbers as character varying — without
        # ::numeric, ORDER BY sorts lexicographically and '995.55' > '9.8'.
        if col in NUMERIC_ORDER_COLUMNS:
            order_parts.append(f"{col}::numeric {direction} NULLS LAST")
        else:
            order_parts.append(f"{col} {direction} NULLS LAST")
    # Always tie-break by id for stable pagination
    if not any("id" in p for p in order_parts):
        order_parts.append("id ASC")
    order_sql = "ORDER BY " + ", ".join(order_parts)

    total = _query_one(
        f"SELECT count(*) AS c FROM bridge.bridge_cards {where_sql}", params
    )["c"]
    select_cols = ", ".join(c for c, _, _ in LIST_COLUMNS)
    rows = _query(
        f"SELECT id, {select_cols} FROM bridge.bridge_cards {where_sql} "
        f"{order_sql} "
        f"LIMIT %s OFFSET %s",
        params + [page_size, offset],
    )
    return Response({
        "count": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "ordering": ordering,
        "results": rows,
    })


def _create_bridge(request):
    payload = request.data if hasattr(request, "data") else {}
    if not isinstance(payload, dict):
        return Response({"detail": "expected JSON object"}, status=400)
    bridge_name = (payload.get("bridge_name") or "").strip()
    if not bridge_name:
        return Response({"detail": "bridge_name is required"}, status=400)
    bridge_id_code = (payload.get("bridge_id_code") or "").strip()
    if not bridge_id_code:
        return Response({"detail": "bridge_id_code is required"}, status=400)

    cols, vals = [], []
    for k, v in payload.items():
        if k in SYSTEM_COLUMNS:
            continue
        if k not in EDITABLE_COLUMNS:
            continue
        if v in ("", None):
            continue
        cols.append(k)
        vals.append(v)
    if "bridge_name" not in cols:
        cols.append("bridge_name"); vals.append(bridge_name)
    if "bridge_id_code" not in cols:
        cols.append("bridge_id_code"); vals.append(bridge_id_code)

    placeholders = ", ".join(["%s"] * len(vals))
    col_list = ", ".join(cols)
    _exec(
        f"INSERT INTO bridge.bridge_cards ({col_list}) VALUES ({placeholders}) RETURNING id",
        vals,
    )
    new_id = _query_one("SELECT id FROM bridge.bridge_cards ORDER BY created_at DESC LIMIT 1")
    return Response({"id": new_id["id"] if new_id else None, "created": True}, status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def bridge_detail(request, bridge_id):
    bridge_id = _coerce_uuid(bridge_id)
    if bridge_id is None:
        return Response({"detail": "invalid uuid"}, status=400)
    if request.method == "GET":
        row = _query_one("SELECT * FROM bridge.bridge_cards WHERE id = %s", [bridge_id])
        if not row:
            return Response({"detail": "not found"}, status=404)
        return Response(row)
    if request.method == "DELETE":
        # Sub-tables that FK to bridge_cards via bridge_card_id — clean up first.
        for table, _ in SUBTABLES.values():
            _exec(
                f"DELETE FROM bridge.{table} WHERE bridge_card_id = %s", [bridge_id]
            )
        _exec("DELETE FROM bridge.bridge_cards WHERE id = %s", [bridge_id])
        return Response(status=204)
    # PATCH
    payload = request.data if hasattr(request, "data") else {}
    if not isinstance(payload, dict):
        return Response({"detail": "expected JSON object"}, status=400)
    sets, vals = [], []
    for k, v in payload.items():
        if k in SYSTEM_COLUMNS or k not in EDITABLE_COLUMNS:
            continue
        sets.append(f"{k} = %s")
        vals.append("" if v is None else v)
    if not sets:
        return Response({"updated": True, "changed": 0})
    vals.append(bridge_id)
    _exec(
        f"UPDATE bridge.bridge_cards SET {', '.join(sets)} WHERE id = %s",
        vals,
    )
    return Response({"updated": True, "changed": len(sets)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bridge_subtable(request, bridge_id, kind):
    if kind not in SUBTABLES:
        return Response({"detail": f"unknown subtable: {kind}"}, status=400)
    bridge_id = _coerce_uuid(bridge_id)
    if bridge_id is None:
        return Response({"detail": "invalid uuid"}, status=400)
    table, label = SUBTABLES[kind]
    rows = _query(
        f"SELECT * FROM bridge.{table} WHERE bridge_card_id = %s ORDER BY id",
        [bridge_id],
    )
    return Response({"label": label, "kind": kind, "count": len(rows), "rows": rows})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bridges_stats(request):
    total_row = _query_one("SELECT count(*) AS c FROM bridge.bridge_cards")
    total = total_row["c"] if total_row else 0
    by_eval = _query(
        "SELECT COALESCE(eval_level, '未定级') AS k, count(*) AS c "
        "FROM bridge.bridge_cards GROUP BY eval_level ORDER BY c DESC"
    )
    by_span = _query(
        "SELECT COALESCE(span_category, '未分类') AS k, count(*) AS c "
        "FROM bridge.bridge_cards GROUP BY span_category ORDER BY c DESC"
    )
    by_route = _query(
        "SELECT COALESCE(route_id, '未指定') AS k, count(*) AS c "
        "FROM bridge.bridge_cards GROUP BY route_id ORDER BY c DESC LIMIT 20"
    )
    by_type = _query(
        "SELECT COALESCE(bridge_type, '未指定') AS k, count(*) AS c "
        "FROM bridge.bridge_cards GROUP BY bridge_type ORDER BY c DESC LIMIT 20"
    )
    by_year = _query(
        "SELECT COALESCE(built_date, '未知') AS k, count(*) AS c "
        "FROM bridge.bridge_cards GROUP BY built_date ORDER BY built_date NULLS LAST LIMIT 20"
    )
    sum_row = _query_one(
        "SELECT sum(length_m::numeric) AS s, avg(length_m::numeric) AS a, "
        "sum(max_span_m::numeric) AS ms FROM bridge.bridge_cards"
    )
    return Response({
        "total": total,
        "by_eval_level": by_eval,
        "by_span_category": by_span,
        "by_route_id": by_route,
        "by_bridge_type": by_type,
        "by_built_date": by_year,
        "total_length_m": sum_row["s"] if sum_row else None,
        "avg_length_m": sum_row["a"] if sum_row else None,
        "max_span_sum_m": sum_row["ms"] if sum_row else None,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bridges_export(request):
    """CSV export (UTF-8 with BOM so Excel opens it cleanly).
    Honors column filters + search. If `ids` is provided (comma-separated),
    only those bridges are exported (this is what the UI sends when the
    user has selected rows)."""
    where_sql, params = _build_filters(request)
    selected_ids = [x for x in request.GET.get("ids", "").split(",") if x]
    if selected_ids:
        where_sql = (where_sql + " AND " if where_sql else "WHERE ") + "id = ANY(%s::uuid[])"
        params = params + [selected_ids]
    order_sql = "ORDER BY route_id NULLS LAST, bridge_id_code NULLS LAST"
    rows = _query(
        f"SELECT * FROM bridge.bridge_cards {where_sql} {order_sql}",
        params,
    )
    buf = io.StringIO()
    buf.write("\ufeff")
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    else:
        buf.write("(no rows match the current filter / selection)\n")
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    suffix = "_selected" if selected_ids else ""
    resp["Content-Disposition"] = f'attachment; filename="bridges{suffix}.csv"'
    return resp


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def placeholder_tab(request, tab):
    """The 4 other tabs (隧道/涵洞/边坡/路段) have no underlying tables yet."""
    label = PLACEHOLDER_TABS.get(tab, tab)
    return Response({
        "placeholder": True,
        "tab": tab,
        "label": label,
        "message": "数据未建表",
        "count": 0,
        "rows": [],
    })


# ---------- Photo upload ----------
def _photo_dir():
    """Where uploaded bridge photos go. Returns (dir, url_prefix)."""
    media_root = getattr(settings, "MEDIA_ROOT", "/webodm/app/media")
    base = os.path.join(media_root, "bridge_photos")
    os.makedirs(base, exist_ok=True)
    return base, "/media/bridge_photos/"


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def photo_upload(request, bridge_id):
    """Upload a photo. Field name is one of: general, front."""
    bridge_id = _coerce_uuid(bridge_id)
    if bridge_id is None:
        return Response({"detail": "invalid uuid"}, status=400)
    kind = request.GET.get("kind", "general")
    if kind not in ("general", "front"):
        return Response({"detail": "kind must be 'general' or 'front'"}, status=400)
    f = request.FILES.get("file")
    if not f:
        return Response({"detail": "missing 'file' field"}, status=400)
    base, url_prefix = _photo_dir()
    ext = os.path.splitext(f.name)[1].lower() or ".jpg"
    new_name = f"{bridge_id}_{kind}_{uuid.uuid4().hex[:8]}{ext}"
    full = os.path.join(base, new_name)
    with open(full, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)
    url = url_prefix + new_name
    col = "general_photo_url" if kind == "general" else "front_photo_url"
    _exec(f"UPDATE bridge.bridge_cards SET {col} = %s WHERE id = %s", [url, bridge_id])
    return Response({"url": url, "kind": kind})


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def photo_delete(request, bridge_id, kind):
    bridge_id = _coerce_uuid(bridge_id)
    if bridge_id is None:
        return Response({"detail": "invalid uuid"}, status=400)
    if kind not in ("general", "front"):
        return Response({"detail": "kind must be 'general' or 'front'"}, status=400)
    col = "general_photo_url" if kind == "general" else "front_photo_url"
    _exec(f"UPDATE bridge.bridge_cards SET {col} = NULL WHERE id = %s", [bridge_id])
    return Response(status=204)


# ---------- Helpers ----------
def _coerce_uuid(s):
    try:
        return str(uuid.UUID(str(s)))
    except (ValueError, AttributeError, TypeError):
        return None
