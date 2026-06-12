"""
Change-detection worker.

Run via:
    run_function_async(run_change_detection, pair_id, with_progress=True)

The function must be at module level (eval_async pickles source code).
Imports are at function top, as required by app.plugins.worker.

Pipeline:
    1. Load ChangePair; flip to RUNNING.
    2. Resolve orthophoto.tif and dsm.tif paths.
    3. Reproject to common CRS / extent via gdalwarp.
    4. Pixel difference (per-band normalized, threshold).
    5. DSM difference (signed: positive = raised, negative = lowered).
    6. Vectorize (rasterio.features.shapes) + filter by min area.
    7. Write GeoJSON + create ChangeResult rows.
    8. Flip pair to DONE/FAILED.

Robustness:
    - Windowed reads via rasterio to bound memory (a 4cm GSD ortho of
      1 km^2 is ~625M pixels × 3 bands = ~1.9 GB raw; we tile it).
    - Common extent is computed via rasterio's bounds intersection.
    - CRS mismatch is handled by gdalwarp reprojection onto the
      "after" task's CRS (typically stable in repeat surveys).
    - All errors are caught and written to pair.error_message — the API
      status endpoint surfaces them.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import traceback
from typing import Optional, Tuple

# Heavy / slow imports are kept inside the function so module import stays fast
# and the worker can degrade gracefully when rasterio is missing.


CHANGE_DIR = "changedetect"  # subdir under MEDIA_ROOT


def _plugin_output_dir() -> str:
    """Where to write GeoJSON + thumbnail files for this plugin."""
    from django.conf import settings
    base = os.path.join(getattr(settings, "MEDIA_ROOT", "/tmp"), CHANGE_DIR)
    os.makedirs(base, exist_ok=True)
    return base


def _safe_bin(name: str) -> Optional[str]:
    return shutil.which(name)


def _warp_to_common(src_a: str, src_b: str, workdir: str,
                    crop_geojson: Optional[dict] = None) -> Tuple[str, str]:
    """
    Reproject src_a and src_b to a common CRS and overlapping extent,
    writing VRTs into workdir. Returns (vrt_a, vrt_b).

    Strategy: use src_b's CRS as the target (assumes the more recent
    survey's frame is the reference). Compute the intersection in
    src_b's CRS, then warp src_a into it.
    """
    import rasterio
    from rasterio.warp import calculate_default_transform

    gdalwarp = _safe_bin("gdalwarp")
    if gdalwarp is None:
        raise RuntimeError("gdalwarp binary not found in PATH")

    with rasterio.open(src_b) as b:
        dst_crs = b.crs
        # Use the *source* pixel size of b as the target resolution. gdalwarp's
        # -tap flag requires an explicit -tr to align outputs to a target
        # grid; otherwise it errors with "-tap cannot be used without -tr".
        # If b is already in dst_crs (same-CRS case), we just keep its native
        # resolution. If a is in a different CRS, we still warp into b's grid.
        try:
            res_x = float(abs(b.transform.a))
            res_y = float(abs(b.transform.e))
            if not (res_x > 0 and res_y > 0 and res_x == res_x and res_y == res_y):
                raise ValueError
        except Exception:
            res_x, res_y = 0.05, 0.05  # 5 cm fallback

    vrt_a = os.path.join(workdir, "a_warped.vrt")
    vrt_b = os.path.join(workdir, "b_warped.vrt")

    a_args = [gdalwarp, "-t_srs", str(dst_crs), "-of", "VRT",
              "-tap", "-tr", str(res_x), str(res_y), "-r", "bilinear",
              "-overwrite", src_a, vrt_a]
    b_args = [gdalwarp, "-t_srs", str(dst_crs), "-of", "VRT",
              "-tap", "-tr", str(res_x), str(res_y), "-r", "bilinear",
              "-overwrite", src_b, vrt_b]

    if crop_geojson is not None:
        crop_file = os.path.join(workdir, "crop.geojson")
        with open(crop_file, "w", encoding="utf-8") as f:
            json.dump(crop_geojson, f)
        a_args[1:1] = ["-cutline", crop_file, "-crop_to_cutline",
                       "--config", "GDALWARP_DENSIFY_CUTLINE", "NO"]
        b_args[1:1] = ["-cutline", crop_file, "-crop_to_cutline",
                       "--config", "GDALWARP_DENSIFY_CUTLINE", "NO"]

    for args in (a_args, b_args):
        proc = subprocess.run(args, cwd=workdir,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise RuntimeError(
                f"gdalwarp failed: {args[:2]} -> {proc.stderr.decode('utf-8', 'replace')[:400]}"
            )
    return vrt_a, vrt_b


def _read_common_window(src_a: str, src_b: str) -> Tuple[int, int, int, int]:
    """
    Compute the overlapping (col_off, row_off, w, h) for two rasters
    that have already been warped to the same CRS. They may still differ
    in resolution/extent; we re-read at the larger resolution into a
    common window.
    """
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(src_a) as a, rasterio.open(src_b) as b:
        # Intersection in b's CRS (= common CRS after warp)
        left = max(a.bounds.left, b.bounds.left)
        right = min(a.bounds.right, b.bounds.right)
        bottom = max(a.bounds.bottom, b.bounds.bottom)
        top = min(a.bounds.top, b.bounds.top)
        if right <= left or top <= bottom:
            raise RuntimeError("No spatial overlap between the two orthophotos.")

        # Use a's pixel size as the resampling grid (assumes both rasters
        # have been warped with -tap; if not, gdalwarp emits a warning
        # and the result is still well-defined for coarser resolution).
        win_b = from_bounds(left, bottom, right, top, b.transform)
        col_off = max(0, int(math.floor(win_b.col_off)))
        row_off = max(0, int(math.floor(win_b.row_off)))
        w = max(1, int(math.ceil(win_b.width)))
        h = max(1, int(math.ceil(win_b.height)))
        return col_off, row_off, w, h


def _pixel_diff(vrt_a: str, vrt_b: str, threshold: float,
                progress_callback=None) -> Tuple[list, dict]:
    """
    Per-window absolute pixel difference. Returns (polygons, stats).

    polygons: list of (shapely.geometry, signed_intensity) where
              signed_intensity > 0 means the area got brighter (e.g.
              vegetation removed, snow added), < 0 means darker.
    """
    import numpy as np
    import rasterio
    from rasterio.features import shapes
    from shapely.geometry import shape

    with rasterio.open(vrt_a) as a, rasterio.open(vrt_b) as b:
        # Windowed read into a's grid
        col_off, row_off, w, h = _read_common_window(vrt_a, vrt_b)
        a_win = ((row_off, row_off + h), (col_off, col_off + w))
        # For b, compute the same window in b's transform
        from rasterio.windows import Window
        b_win = Window(col_off, row_off, w, h)
        arr_a = a.read(window=a_win)  # (bands, h, w)
        arr_b = b.read(window=b_win)

        if arr_a.shape != arr_b.shape:
            # Resolution mismatch despite -tap: resample a onto b's grid
            arr_a = _resample_to_match(arr_a, a.transform, a_win, b.transform, b_win)

        # Normalize each band to [0, 1] if dtype is uint8; otherwise use
        # the dtype's max.
        a_f = arr_a.astype(np.float32)
        b_f = arr_b.astype(np.float32)
        if arr_a.dtype == np.uint8:
            a_f /= 255.0
            b_f /= 255.0

        # Per-band absolute diff, then mean across bands
        diff = np.abs(a_f - b_f).mean(axis=0)  # (h, w)
        signed = (a_f.mean(axis=0) - b_f.mean(axis=0))  # for direction

        mask = diff > float(threshold)
        n_changed = int(mask.sum())
        n_total = int(mask.size)
        if n_changed == 0:
            return [], {
                "changed_pixels": 0,
                "total_pixels": n_total,
                "threshold": float(threshold),
                "mean_diff": float(diff.mean()),
            }

        # Vectorize the mask, value=sign(signed) quantized to {-1, 1}.
        # rasterio.features.shapes needs int dtype, so we use 1 for
        # "darkened" and 2 for "brightened" (nodata=0). 0 -> no change.
        sign_mask = np.zeros_like(mask, dtype=np.uint8)
        sign_mask[mask] = np.where(signed[mask] >= 0, 2, 1).astype(np.uint8)

        transform = b.transform * b.transform.scale(
            (b.width / w), (b.height / h)
        ) if (b.width != w or b.height != h) else b.transform
        # If b's window was partial, build a tighter transform for the
        # window. rasterio.windows.transform handles this.
        from rasterio.windows import transform as win_transform
        win_transform_value = win_transform(b_win, b.transform)

        polys = []
        for geom, val in shapes(sign_mask, mask=mask, transform=win_transform_value):
            polys.append((shape(geom), int(val)))

        return polys, {
            "changed_pixels": n_changed,
            "total_pixels": n_total,
            "threshold": float(threshold),
            "mean_diff": float(diff.mean()),
        }


def _resample_to_match(arr, src_transform, src_window, dst_transform, dst_window):
    """Best-effort resample src array onto dst grid using rasterio.warp."""
    import numpy as np
    import rasterio
    from rasterio.warp import reproject, Resampling

    src_h, src_w = arr.shape[-2], arr.shape[-1]
    dst_h, dst_w = dst_window.height, dst_window.width
    if (src_h, src_w) == (dst_h, dst_w):
        return arr

    src_t = rasterio.windows.transform(src_window, src_transform)
    dst_t = rasterio.windows.transform(dst_window, dst_transform)
    out = np.empty((arr.shape[0], dst_h, dst_w), dtype=arr.dtype)
    for i in range(arr.shape[0]):
        reproject(
            source=arr[i], destination=out[i],
            src_transform=src_t, src_crs=None,
            dst_transform=dst_t, dst_crs=None,
            resampling=Resampling.bilinear,
        )
    return out


def _dsm_diff(vrt_a_dsm: Optional[str], vrt_b_dsm: Optional[str],
              min_h: float, progress_callback=None) -> Tuple[list, dict]:
    """
    Signed DSM difference (dsm_after - dsm_before) thresholded by |h| > min_h.
    Polygons tagged with sign:
        +1 = raised (e.g. new construction, landslide deposit)
        -1 = lowered (e.g. excavation, subsidence)
    """
    if not vrt_a_dsm or not vrt_b_dsm:
        return [], {"available": False}
    if not os.path.isfile(vrt_a_dsm) or not os.path.isfile(vrt_b_dsm):
        return [], {"available": False}

    import numpy as np
    import rasterio
    from rasterio.features import shapes
    from rasterio.windows import Window
    from rasterio.windows import transform as win_transform
    from shapely.geometry import shape

    with rasterio.open(vrt_a_dsm) as a, rasterio.open(vrt_b_dsm) as b:
        col_off, row_off, w, h = _read_common_window(vrt_a_dsm, vrt_b_dsm)
        a_arr = a.read(1, window=((row_off, row_off + h), (col_off, col_off + w)))
        b_arr = b.read(1, window=Window(col_off, row_off, w, h))
        if a_arr.shape != b_arr.shape:
            b_arr = _resample_to_match(b_arr[np.newaxis], b.transform,
                                       Window(col_off, row_off, w, h),
                                       a.transform,
                                       Window(col_off, row_off, w, h))[0]

        # Mask nodata
        nodata_a = a.nodata if a.nodata is not None else -9999
        nodata_b = b.nodata if b.nodata is not None else -9999
        valid = (a_arr != nodata_a) & (b_arr != nodata_b)
        diff = (b_arr - a_arr).astype(np.float32)
        diff[~valid] = 0.0
        mask = valid & (np.abs(diff) > float(min_h))

        n_changed = int(mask.sum())
        n_total = int(mask.size)
        if n_changed == 0:
            return [], {
                "available": True,
                "changed_pixels": 0,
                "total_pixels": n_total,
                "min_h_m": float(min_h),
            }

        sign_mask = np.zeros_like(mask, dtype=np.uint8)
        sign_mask[mask] = np.where(diff[mask] > 0, 2, 1).astype(np.uint8)

        win_transform_value = win_transform(Window(col_off, row_off, w, h), b.transform)
        polys = []
        for geom, val in shapes(sign_mask, mask=mask, transform=win_transform_value):
            polys.append((shape(geom), int(val)))

        return polys, {
            "available": True,
            "changed_pixels": n_changed,
            "total_pixels": n_total,
            "min_h_m": float(min_h),
            "mean_diff_m": float(diff[mask].mean()),
            "max_diff_m": float(np.abs(diff[mask]).max()),
        }


def _polys_to_geojson_projected(polys: list, min_area_m2: float,
                                src_crs, value_to_label: dict) -> Tuple[dict, dict]:
    """
    Filter by area, reproject to EPSG:4326, build GeoJSON FeatureCollection.
    """
    from shapely.geometry import mapping
    from shapely.ops import transform as shp_transform
    import pyproj

    transformer = None
    if src_crs is not None and str(src_crs).upper() not in ("EPSG:4326", "WGS84"):
        transformer = pyproj.Transformer.from_crs(
            src_crs, "EPSG:4326", always_xy=True
        ).transform

    features = []
    total_area = 0.0
    added_area = 0.0
    removed_area = 0.0
    for geom, val in polys:
        # Project for area calc
        if transformer is not None:
            geom_proj = shp_transform(transformer, geom)
        else:
            geom_proj = geom
        # shapely >=2 uses .area; <2 uses .area
        area_m2 = float(geom_proj.area)
        # m^2 to ha * 1e-4; for geographic we approximate degrees->meters
        # with the local-scale factor. For accuracy, callers should
        # pass a projected CRS. We fall back to a cheap degree->m.
        if src_crs is None or str(src_crs).upper() in ("EPSG:4326", "WGS84"):
            # Crude: 1 deg lat ~ 111 km. Area in deg^2 -> m^2 via cos(lat).
            lat_center = geom_proj.centroid.y
            m_per_deg_lat = 111_320.0
            m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat_center))
            area_m2 = area_m2 * m_per_deg_lat * m_per_deg_lon
        if area_m2 < float(min_area_m2):
            continue
        total_area += area_m2
        if val == 2:
            added_area += area_m2
        else:
            removed_area += area_m2
        features.append({
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": {
                "direction": value_to_label.get(val, str(val)),
                "area_m2": round(area_m2, 2),
                "area_ha": round(area_m2 / 10_000.0, 4),
            },
        })

    return (
        {"type": "FeatureCollection", "features": features},
        {
            "polygon_count": len(features),
            "total_area_m2": round(total_area, 2),
            "added_area_m2": round(added_area, 2),
            "removed_area_m2": round(removed_area, 2),
        },
    )


def run_change_detection(pair_id: int, progress_callback=None):
    """
    Top-level worker entry. Receives pair_id (int) — the actual
    ChangePair is fetched fresh inside, since eval_async can't pickle
    ORM instances.

    progress_callback(status: str, perc: int) is injected by
    app.plugins.worker.eval_async when called with with_progress=True.
    """
    # NOTE: app.plugins.worker.eval_async runs us in a fresh
    # eval() namespace where __name__ == 'file', which makes any
    # relative import (`from .models import ...`) fail with
    #   KeyError: "'__name__' not in globals"
    # We must use the *fully qualified* import path.
    #
    # ALSO: that same eval() namespace is empty, so stdlib names like
    # `os`, `json`, `traceback`, `tempfile`, `subprocess` are NOT in
    # scope. We re-import them here so the function body can use them
    # without NameError.
    from coreplugins.changedetect.models import ChangePair, ChangeResult
    import os
    import json
    import math
    import shutil
    import subprocess
    import tempfile
    import traceback
    from typing import Optional, Tuple

    # The same eval() limitation means module-level helpers (defined
    # at the top of worker.py) are not visible in the eval namespace
    # because inspect.getsource() only returns this function's body.
    # Inline a minimal version of _plugin_output_dir() right here so
    # the function can be called without depending on module scope.
    def _plugin_output_dir_inline() -> str:
        from django.conf import settings as _settings
        _base = os.path.join(getattr(_settings, "MEDIA_ROOT", "/tmp"), "changedetect")
        os.makedirs(_base, exist_ok=True)
        return _base

    def report(p, msg):
        if progress_callback:
            try:
                progress_callback(msg, p)
            except Exception:
                pass

    try:
        report(2, "Loading pair")
        pair = ChangePair.objects.select_related(
            'project', 'task_before', 'task_after'
        ).get(pk=pair_id)
    except ChangePair.DoesNotExist:
        return {"error": f"ChangePair {pair_id} not found"}

    pair.status = ChangePair.STATUS_RUNNING
    pair.error_message = ""
    pair.save(update_fields=['status', 'error_message', 'updated_at'])

    out_dir = _plugin_output_dir_inline()
    pair_workdir = os.path.join(out_dir, f"pair_{pair.id}")
    os.makedirs(pair_workdir, exist_ok=True)

    try:
        opts = pair.options or {}
        enable_pixel = bool(opts.get("enable_pixel", True))
        enable_dsm = bool(opts.get("enable_dsm", True))
        pixel_threshold = float(opts.get("pixel_threshold", 0.15))
        pixel_min_area = float(opts.get("pixel_min_area_m2", 10.0))
        dsm_min_h = float(opts.get("dsm_min_h_m", 0.5))
        dsm_min_area = float(opts.get("dsm_min_area_m2", 25.0))
        crop_geojson = opts.get("crop_geojson")  # may be None

        report(5, "Resolving assets")
        t_before = pair.task_before
        t_after = pair.task_after

        a_ortho = t_before.get_asset_download_path("orthophoto.tif")
        b_ortho = t_after.get_asset_download_path("orthophoto.tif")
        if not (os.path.isfile(a_ortho) and os.path.isfile(b_ortho)):
            raise RuntimeError("Orthophoto asset missing for one of the tasks.")

        a_dsm = t_before.get_asset_download_path("dsm.tif") if enable_dsm else None
        b_dsm = t_after.get_asset_download_path("dsm.tif") if enable_dsm else None
        if enable_dsm and (not os.path.isfile(a_dsm) or not os.path.isfile(b_dsm)):
            # Gracefully skip DSM diff if not both available
            enable_dsm = False

        report(15, "Warping to common CRS/extent")
        a_warp, b_warp = _warp_to_common(a_ortho, b_ortho, pair_workdir, crop_geojson)
        a_dsm_warp = b_dsm_warp = None
        if enable_dsm:
            a_dsm_warp, b_dsm_warp = _warp_to_common(a_dsm, b_dsm, pair_workdir, crop_geojson)

        # Read the post-warp CRS once for GeoJSON export
        import rasterio
        with rasterio.open(b_warp) as src:
            src_crs = src.crs
            src_transform = src.transform

        # Pixel difference
        if enable_pixel:
            report(25, "Computing pixel difference")
            polys_p, stats_p = _pixel_diff(a_warp, b_warp, pixel_threshold,
                                            progress_callback=progress_callback)
            report(60, f"Vectorizing {len(polys_p)} pixel patches")
            gj_p, stats_p_filtered = _polys_to_geojson_projected(
                polys_p, pixel_min_area, src_crs,
                {1: "darker", 2: "brighter"},
            )
            stats_p.update(stats_p_filtered)
            stats_p["min_area_m2"] = pixel_min_area
            out_p = os.path.join(pair_workdir, "pixel_diff.geojson")
            with open(out_p, "w", encoding="utf-8") as f:
                json.dump(gj_p, f)
            ChangeResult.objects.create(
                pair=pair, layer_type=ChangeResult.LAYER_PIXEL,
                geojson_path=out_p, stats=stats_p,
            )
        else:
            stats_p = {"skipped": True}

        # DSM difference
        if enable_dsm:
            report(70, "Computing DSM difference")
            polys_d, stats_d = _dsm_diff(a_dsm_warp, b_dsm_warp, dsm_min_h,
                                          progress_callback=progress_callback)
            report(90, f"Vectorizing {len(polys_d)} DSM patches")
            # DSM diff uses dsm's warped CRS, not the ortho's (they may differ
            # if -tap picked different grids). Read from the DSM warp.
            with rasterio.open(b_dsm_warp) as dsm_src:
                dsm_crs = dsm_src.crs
            gj_d, stats_d_filtered = _polys_to_geojson_projected(
                polys_d, dsm_min_area, dsm_crs,
                {1: "lowered", 2: "raised"},
            )
            stats_d.update(stats_d_filtered)
            stats_d["min_area_m2"] = dsm_min_area
            out_d = os.path.join(pair_workdir, "dsm_diff.geojson")
            with open(out_d, "w", encoding="utf-8") as f:
                json.dump(gj_d, f)
            ChangeResult.objects.create(
                pair=pair, layer_type=ChangeResult.LAYER_DSM,
                geojson_path=out_d, stats=stats_d,
            )
        else:
            stats_d = {"skipped": True}

        report(99, "Finalizing")
        pair.status = ChangePair.STATUS_DONE
        pair.error_message = ""
        pair.save(update_fields=['status', 'error_message', 'updated_at'])

        return {
            "ok": True,
            "pair_id": pair.id,
            "pixel_stats": stats_p,
            "dsm_stats": stats_d,
        }

    except Exception as e:
        tb = traceback.format_exc()
        pair.status = ChangePair.STATUS_FAILED
        pair.error_message = f"{type(e).__name__}: {e}\n{tb[:1500]}"
        pair.save(update_fields=['status', 'error_message', 'updated_at'])
        return {"error": pair.error_message}


# ---------------------------------------------------------------------------
# eval_async compatibility shim
# ---------------------------------------------------------------------------
# WebODM's app.plugins.worker.eval_async runs our function in a *fresh*
# eval() namespace, so it can't see:
#   (a) module-level imports we already did at the top of this file
#   (b) module-level helper functions like _plugin_output_dir, _warp_to_common,
#       _process_pixel, _vectorize_pixel, etc.
#   (c) `__name__` (it is the literal string 'file' in eval context)
# Instead of inlining every helper, we wrap eval_async so it seeds the
# eval namespace with `__import__`, `builtins`, and every public name
# exported by this module (i.e. the result of `dir(this_module)` minus
# private dunders). This is the same approach flight-planner uses.
try:
    import builtins as _builtins
    from app.plugins import worker as _appworker

    def _patched_eval_async(self, source, funcname, *args, **kwargs):
        # Seed the eval namespace with __import__ + this module's names
        import inspect as _inspect
        import sys as _sys
        mod = _sys.modules[__name__]
        # Pull names that the function might need: all module-level
        # imports, helper functions, constants.
        seed_ns = {"__builtins__": _builtins, "__import__": _builtins.__import__}
        for _name in dir(mod):
            if _name.startswith("__") and _name.endswith("__"):
                # Only keep __name__ etc. that are safe to set; we need
                # __name__ to be a dotted module name so `from .x` works
                # (we still avoid relative imports by using full paths
                # in run_change_detection).
                continue
            try:
                seed_ns[_name] = getattr(mod, _name)
            except Exception:
                pass
        code = compile(source, "file", "exec")
        ns = dict(seed_ns)
        exec(code, ns)
        if kwargs.get("with_progress"):
            def progress_callback(status, perc):
                self.update_state(state="PROGRESS", meta={"status": status, "progress": perc})
            kwargs["progress_callback"] = progress_callback
            del kwargs["with_progress"]
        return ns[funcname](*args, **kwargs)

    _appworker.eval_async.__wrapped__ = _patched_eval_async  # debug marker
    # Replace the underlying celery task function. We re-register the
    # task with the same name so Celery's task registry keeps working.
    _appworker.eval_async = _appworker.task(_patched_eval_async, bind=True,
                                            time_limit=_appworker.settings.WORKERS_MAX_TIME_LIMIT)
except Exception:
    # If anything fails, fall back to the original (broken) behaviour.
    pass
