"""
AI-powered change-zone classification.

Two-stage pipeline:
  1. For each detected change feature (a polygon in pixel_diff.geojson
     or dsm_diff.geojson), crop the corresponding region out of the
     pair's AFTER-task orthophoto and run geodeep's
     aerovision-classifier over it. This gives us a high-confidence
     ground-truth label ("building", "vehicle", "boat", "tree", …).
  2. For zones where the visual classifier is uncertain or returns
     nothing, fall back to the LLM (ai.classify_change_zone) which
     uses spatial heuristics (area, direction, proximity to road /
     building) to suggest a label.

The geodeep call is the heavyweight step (~5-30 s per zone on CPU).
We do it in a Celery task via `app.plugins.worker.run_function_async`
so the API can return immediately with a celery_task_id; the worker
posts back the per-zone annotations to the change_pair.

The LLM step is fast (1-3 s) and runs in the same Celery task right
after the geodeep step.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — keep here so the API layer can label them too
# ---------------------------------------------------------------------------

# Order matters: most-confident first. The "label" field on a
# ChangeAnnotation is always one of these.
ALLOWED_LABELS = (
    "building", "vehicle", "vegetation", "road", "construction",
    "demolition", "water", "bare_soil", "structure", "industrial",
    "container", "boat", "plane", "tree", "other",
)
# Color per label (matches webodm convention for thematic layers)
LABEL_COLORS = {
    "building":      "#e74c3c",
    "vehicle":       "#f1c40f",
    "vegetation":    "#27ae60",
    "road":          "#34495e",
    "construction":  "#e67e22",
    "demolition":    "#7f8c8d",
    "water":         "#3498db",
    "bare_soil":     "#a0522d",
    "structure":     "#9b59b6",
    "industrial":    "#c0392b",
    "container":     "#d35400",
    "boat":          "#1abc9c",
    "plane":         "#34495e",
    "tree":          "#16a085",
    "other":         "#95a5a6",
}
# Human-readable Chinese label
LABEL_CN = {
    "building": "建筑物", "vehicle": "车辆", "vegetation": "植被变化",
    "road": "道路变化", "construction": "施工区", "demolition": "拆除区",
    "water": "水体变化", "bare_soil": "裸土", "structure": "构筑物",
    "industrial": "工业设施", "container": "集装箱", "boat": "船舶",
    "plane": "飞机", "tree": "树木", "other": "其他",
}


# ---------------------------------------------------------------------------
# Geodeep wrapper
# ---------------------------------------------------------------------------

def _try_import_geodeep():
    """Late-import geodeep. The library is optional: if it's not
    installed we just skip the visual-classification step and the
    function returns empty detections, so the LLM fallback still runs.
    """
    try:
        from geodeep import detect as gdetect, models  # type: ignore
        from webodm import settings  # type: ignore
        models.cache_dir = os.path.join(settings.MEDIA_CACHE, "detection_models")
        return gdetect, models
    except ImportError as e:
        log.info(f"geodeep not available: {e}")
        return None, None


def _orthophoto_path(task) -> Optional[str]:
    """Resolve the absolute path to a task's orthophoto.tif, or None."""
    if not task:
        return None
    try:
        return os.path.abspath(task.get_asset_download_path("orthophoto.tif"))
    except Exception as e:
        log.warning(f"could not resolve orthophoto for task {task.id}: {e}")
        return None


def _crop_orthophoto(ortho_path: str, feature: Dict[str, Any], tmpdir: str) -> Optional[str]:
    """Crop the orthophoto to a feature's bbox using gdalwarp. Returns
    the path of the cropped VRT or None on failure.
    """
    import shutil
    import subprocess
    import tempfile
    gdalwarp = shutil.which("gdalwarp")
    if gdalwarp is None:
        return None
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if not coords or not coords[0]:
        return None
    ring = coords[0] if isinstance(coords[0][0], list) else coords
    xs = [c[0] for c in ring]; ys = [c[1] for c in ring]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    # tiny padding so the model doesn't see zero-margin crops
    pad_x = (maxx - minx) * 0.05 or 0.0005
    pad_y = (maxy - miny) * 0.05 or 0.0005
    crop_geojson = os.path.join(tmpdir, "crop.geojson")
    out_vrt = os.path.join(tmpdir, "crop.vrt")
    with open(crop_geojson, "w") as f:
        json.dump({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [[
                    [minx - pad_x, miny - pad_y],
                    [maxx + pad_x, miny - pad_y],
                    [maxx + pad_x, maxy + pad_y],
                    [minx - pad_x, maxy + pad_y],
                    [minx - pad_x, miny - pad_y],
                ]]},
            }],
        }, f)
    try:
        p = subprocess.run(
            [gdalwarp, "-cutline", crop_geojson,
             "--config", "GDALWARP_DENSIFY_CUTLINE", "NO",
             "-crop_to_cutline", "-of", "VRT",
             ortho_path, out_vrt],
            capture_output=True, timeout=60,
        )
        if p.returncode != 0:
            log.debug(f"gdalwarp failed: {p.stderr.decode()[:200]}")
            return None
        return out_vrt
    except Exception as e:
        log.debug(f"gdalwarp error: {e}")
        return None


def _near_feature(ortho_path: str, feature: Dict[str, Any], model_name: str,
                  classes: Optional[List[str]] = None) -> Tuple[bool, float]:
    """Run a geodeep model over a single feature's bbox (the orthophoto
    has already been cropped). Returns (found, confidence) — found is
    True if at least one detection is in the model classes.
    """
    gdetect, _ = _try_import_geodeep()
    if gdetect is None:
        return False, 0.0
    try:
        result = gdetect(ortho_path, model_name, output_type="geojson",
                         classes=classes, max_threads=1)
        # result is a list of features; we don't filter by IoU here
        # because we already cropped to the feature.
        if not result or not result.get("features"):
            return False, 0.0
        # Take the highest-confidence feature
        feats = result["features"]
        feats.sort(key=lambda f: (f.get("properties") or {}).get("confidence", 0),
                   reverse=True)
        top = feats[0]
        props = top.get("properties") or {}
        return True, float(props.get("confidence", 0.0))
    except Exception as e:
        log.debug(f"geodeep {model_name} failed: {e}")
        return False, 0.0


# ---------------------------------------------------------------------------
# Spatial heuristics — used to enrich the LLM's context
# ---------------------------------------------------------------------------

def _centroid(feature: Dict[str, Any]) -> List[float]:
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if not coords or not coords[0]:
        return [0, 0]
    ring = coords[0] if isinstance(coords[0][0], list) else coords
    cx = sum(c[0] for c in ring) / len(ring)
    cy = sum(c[1] for c in ring) / len(ring)
    return [cx, cy]


def _bbox(feature: Dict[str, Any]) -> List[float]:
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if not coords or not coords[0]:
        return []
    ring = coords[0] if isinstance(coords[0][0], list) else coords
    xs = [c[0] for c in ring]; ys = [c[1] for c in ring]
    return [min(xs), min(ys), max(xs), max(ys)]


def _area_m2(feature: Dict[str, Any]) -> float:
    """Read pre-computed area_m2 from feature.properties if present,
    else return 0 — the worker that produced the GeoJSON should have
    filled this in for us.
    """
    p = feature.get("properties") or {}
    try:
        return float(p.get("area_m2", 0))
    except (TypeError, ValueError):
        return 0.0


def _direction(feature: Dict[str, Any]) -> str:
    return (feature.get("properties") or {}).get("direction", "?")


# ---------------------------------------------------------------------------
# Main entry point: classify a single zone
# ---------------------------------------------------------------------------

def classify_zone_with_ai(feature: Dict[str, Any], layer_type: str,
                          ortho_after_path: Optional[str] = None,
                          progress_callback=None) -> Dict[str, Any]:
    """
    Run the full AI pipeline on a single change feature.

    Returns:
        {
            "label": one of ALLOWED_LABELS,
            "confidence": 0.0-1.0,
            "source": "geodeep_aerovision" | "geodeep_cars" | "llm_fallback",
            "rationale": "...",
            "centroid": [lng, lat],
            "area_m2": float,
        }
    The shape is stable even if every step fails — in that case
    label='other', source='llm_fallback' and rationale describes why.
    """
    import tempfile
    from .ai import classify_change_zone  # avoid circular import

    centroid = _centroid(feature)
    bbox = _bbox(feature)
    area = _area_m2(feature)
    direction = _direction(feature)

    if progress_callback:
        progress_callback(10, f"准备分析区域 {area:.0f} m²")

    # 1. Geodeep over the cropped orthophoto
    if ortho_after_path and os.path.exists(ortho_after_path):
        with tempfile.TemporaryDirectory(prefix="cd_clf_") as tmpdir:
            crop_vrt = _crop_orthophoto(ortho_after_path, feature, tmpdir)
            if crop_vrt:
                if progress_callback:
                    progress_callback(40, "AI 视觉识别中…")
                # Try aerovision first (richer class set), then cars
                found, conf = _near_feature(
                    crop_vrt, feature, "aerovision",
                    classes=["building", "boat", "plane"],
                )
                if found and conf >= 0.4:
                    if progress_callback:
                        progress_callback(100, "完成")
                    return {
                        "label": "building" if conf >= 0.7 else "structure",
                        "confidence": conf,
                        "source": "geodeep_aerovision",
                        "rationale": f"AI 视觉识别 (aerovision): 建筑置信度 {conf:.2f}",
                        "centroid": centroid, "area_m2": area, "bbox": bbox,
                    }
                # Cars pass
                found, conf = _near_feature(crop_vrt, feature, "cars")
                if found and conf >= 0.4:
                    if progress_callback:
                        progress_callback(100, "完成")
                    return {
                        "label": "vehicle", "confidence": conf,
                        "source": "geodeep_cars",
                        "rationale": f"AI 视觉识别 (cars): 车辆置信度 {conf:.2f}",
                        "centroid": centroid, "area_m2": area, "bbox": bbox,
                    }

    # 2. LLM fallback — uses spatial heuristics
    if progress_callback:
        progress_callback(70, "LLM 推理中…")
    result = classify_change_zone({
        "layer_type": layer_type,
        "area_m2": area,
        "direction": direction,
        "centroid": centroid,
        "bbox": bbox,
        "near_road": False,       # TODO: cross-reference OSM road layer
        "near_building": False,   # TODO: cross-reference OSM building layer
    })
    if progress_callback:
        progress_callback(100, "完成")
    if not result.get("ok"):
        return {
            "label": "other", "confidence": 0.0,
            "source": "llm_fallback",
            "rationale": f"LLM 失败: {result.get('error', '?')}",
            "centroid": centroid, "area_m2": area, "bbox": bbox,
        }
    return {
        "label": result["label"],
        "confidence": result["confidence"],
        "source": "llm_fallback",
        "rationale": result.get("rationale", ""),
        "centroid": centroid, "area_m2": area, "bbox": bbox,
    }


def classify_all_zones_for_pair(pair, progress_callback=None) -> Dict[str, Any]:
    """
    Run classification for every change feature in every result of a
    pair. Returns a per-feature list suitable for bulk-inserting into
    ChangeAnnotation rows.
    """
    results = list(pair.results.all())
    if not results:
        return {"annotations": [], "skipped": 0, "errors": []}

    # Use the AFTER-task orthophoto as the visual reference
    ortho_after = _orthophoto_path(pair.task_after)

    annotations: List[Dict[str, Any]] = []
    errors: List[str] = []
    total_features = 0
    for r in results:
        if not r.geojson_path or not os.path.exists(r.geojson_path):
            errors.append(f"result {r.id}: missing geojson_path")
            continue
        try:
            with open(r.geojson_path) as f:
                geo = json.load(f)
        except Exception as e:
            errors.append(f"result {r.id}: {e}")
            continue
        features = geo.get("features", [])
        total_features += len(features)
        for i, feat in enumerate(features):
            if progress_callback:
                pct = 10 + int(80 * (i + 1) / max(len(features), 1))
                progress_callback(pct, f"AI 识别 {r.layer_type} 区域 {i+1}/{len(features)}")
            try:
                ann = classify_zone_with_ai(
                    feat, layer_type=r.layer_type,
                    ortho_after_path=ortho_after,
                )
                ann["result_id"] = r.id
                ann["layer_type"] = r.layer_type
                # Stable per-feature id so re-running the AI doesn't
                # produce duplicates. We use the result id + feature
                # index; the LLM step is non-deterministic so we don't
                # include the label in the key.
                ann["feature_index"] = i
                annotations.append(ann)
            except Exception as e:
                log.exception("classify_zone_with_ai failed")
                errors.append(f"feature {i} of result {r.id}: {e}")

    return {
        "annotations": annotations,
        "total_features": total_features,
        "skipped": total_features - len(annotations),
        "errors": errors,
    }
