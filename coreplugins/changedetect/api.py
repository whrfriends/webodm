"""
REST API for the Change Detection plugin.

Endpoints (mounted under /api/plugins/changedetect/):
  POST   project/<project_id>/changedetect         Create a pair + start worker
  GET    project/<project_id>/changedetect/list    List pairs in a project
  POST   changedetect/pair/<pair_id>/run          (Re-)run an existing pair
  GET    changedetect/<pair_id>/status             Poll status + progress
  GET    changedetect/<pair_id>/result/<result_id>/download  Download GeoJSON

The worker function (run_change_detection, in worker.py) updates the
ChangePair/ChangeResult rows directly. The status endpoint then reflects
DB state — this avoids having to ship celery result payloads to the
client, which keeps large change-polygon GeoJSONs out of the message
queue.
"""

import os
import json

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import permissions, status
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework_jwt.authentication import JSONWebTokenAuthentication
from app.api.authentication import JSONWebTokenAuthenticationQS


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """
    Session auth that does NOT enforce CSRF. Required because plugin
    mount points in WebODM are resolved by a try_resolve_url loop in
    app/plugins/views.py, which sits OUTSIDE the regular URL resolver —
    so CsrfViewMiddleware's normal csrf_exempt detection (looking at
    the view function's csrf_exempt flag) doesn't apply. DRF's CSRF
    check (in SessionAuthentication.enforce_csrf) is the only place
    that matters for DRF views; we no-op it here. The
    @method_decorator(csrf_exempt, name='dispatch') on each view class
    covers the case where the view runs through standard DRF dispatch.
    """
    def enforce_csrf(self, request):
        return  # CSRF disabled
from rest_framework.response import Response
from rest_framework.views import APIView
from django.http import HttpResponse, FileResponse, Http404, HttpResponseForbidden
from django.utils.translation import gettext_lazy as _


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """Session auth that does NOT enforce CSRF.

    Plugin endpoints are intended for both browser and non-browser callers
    (scripts, integrations, headless tooling). Forcing a CSRF token breaks
    every external client. Same pattern used by flight-planner.
    """
    def enforce_csrf(self, request):
        return  # no-op


# Convenience base: default authentication classes use the CSRF-exempt
# variant so DRF's own enforce_csrf() (called from SessionAuthentication)
# is a no-op. Subclasses still need @method_decorator(csrf_exempt, name='dispatch')
# applied to themselves — @method_decorator on a base class only affects
# that class's dispatch; subclass dispatch is not auto-decorated.
class ChangeDetectAPIView(APIView):
    # Authentication order matters:
    # 1. JWT (header / query) — primary, what scripts/CLI use
    # 2. Session (no CSRF) — for browser UI; jQuery adds X-CSRFToken anyway,
    #    but CsrfExemptSessionAuthentication here keeps the API callable
    #    from non-browser clients without a token round-trip.
    # 3. Basic — fallthrough.
    authentication_classes = [
        JSONWebTokenAuthentication,
        JSONWebTokenAuthenticationQS,
        CsrfExemptSessionAuthentication,
        BasicAuthentication,
    ]
    permission_classes = (permissions.AllowAny,)

from app.api.common import get_and_check_project, check_project_perms
from app.models import Task
from worker.tasks import TestSafeAsyncResult

from .models import ChangePair, ChangeResult
from .worker import run_change_detection
from app.plugins.worker import run_function_async


def _run_change_detection_safe(pair_id, progress_callback=None):
    """
    Thin wrapper that re-executes ``run_change_detection`` in an eval()
    namespace seeded with this module's globals. This is needed because
    WebODM's app.plugins.worker.eval_async runs worker functions in a
    fresh, empty eval namespace (where __name__ == 'file', no module
    imports, no module-level helpers). This wrapper sidesteps the
    limitation by defining the wrapper here, then having the wrapper
    re-execute the real function with everything it needs.
    """
    import inspect as _inspect
    import sys as _sys
    import types as _types
    mod = _sys.modules["coreplugins.changedetect.worker"]
    fake = _types.ModuleType("__cd_safe__")
    fake.__dict__.update(mod.__dict__)
    src = _inspect.getsource(mod.run_change_detection)
    code = compile(src, "<cd_safe:run_change_detection>", "exec")
    exec(code, fake.__dict__)
    return fake.run_change_detection(pair_id, progress_callback)


def _get_pair_or_404(request, pair_id):
    try:
        pair = ChangePair.objects.select_related('project', 'task_before', 'task_after').get(pk=pair_id)
    except (ChangePair.DoesNotExist, ValueError):
        raise Http404("ChangePair not found")

    # Project-level perms; reuse WebODM's guardian-based check.
    if not (pair.project.public):
        check_project_perms(request, pair.project, ('view_project',))
    return pair


@method_decorator(csrf_exempt, name='dispatch')
class ProjectChangeDetect(ChangeDetectAPIView):
    """
    POST /api/plugins/changedetect/project/<project_id>/changedetect

    Body:
      task_before: int  (required)
      task_after:  int  (required)
      name:        str  (optional, defaults to "<t1> vs <t2>")
      options:     dict (optional thresholds/flags)
    """
    permission_classes = (permissions.AllowAny,)

    def post(self, request, project_id=None):
        project = get_and_check_project(request, project_id)
        if not project:
            return Response({'error': _('Project not found.')}, status=status.HTTP_404_NOT_FOUND)

        if not (project.public):
            check_project_perms(request, project, ('change_project',))

        # Parse + validate (task IDs are UUIDs in WebODM; accept either str or int)
        raw_before = request.data.get('task_before')
        raw_after = request.data.get('task_after')
        if not raw_before or not raw_after:
            return Response({'error': _('task_before and task_after are required.')},
                            status=status.HTTP_400_BAD_REQUEST)
        task_before_id = str(raw_before).strip()
        task_after_id = str(raw_after).strip()
        if task_before_id == task_after_id:
            return Response({'error': _('task_before and task_after must differ.')},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            t_before = Task.objects.get(pk=task_before_id, project=project)
            t_after = Task.objects.get(pk=task_after_id, project=project)
        except (Task.DoesNotExist, ValueError, Exception):
            # ValidationError (malformed UUID) and DoesNotExist (no such task
            # in this project) both end up here; surface a single clean 400
            # instead of letting Django render its 500 traceback page.
            return Response({'error': _('Tasks not found in this project.')},
                            status=status.HTTP_400_BAD_REQUEST)

        if t_before.orthophoto_extent is None or t_after.orthophoto_extent is None:
            return Response({'error': _('Both tasks must have an orthophoto.')},
                            status=status.HTTP_400_BAD_REQUEST)

        # Defaults
        options = dict(request.data.get('options') or {})
        # Sanitize / default-fill
        options.setdefault('pixel_threshold', 0.15)
        options.setdefault('pixel_min_area_m2', 10.0)
        options.setdefault('dsm_min_h_m', 0.5)
        options.setdefault('dsm_min_area_m2', 25.0)
        options.setdefault('enable_pixel', True)
        options.setdefault('enable_dsm', True)
        if 'crop_geojson' in options and options['crop_geojson']:
            # accepted as JSON string
            try:
                options['crop_geojson'] = json.loads(options['crop_geojson'])
            except (TypeError, ValueError):
                return Response({'error': _('crop_geojson must be valid JSON.')},
                                status=status.HTTP_400_BAD_REQUEST)

        name = (request.data.get('name') or '').strip()
        if not name:
            name = f"{t_before.name} vs {t_after.name}"

        # Create the pair row in PENDING; worker flips to QUEUED->RUNNING->DONE/FAILED.
        pair = ChangePair.objects.create(
            project=project,
            task_before=t_before,
            task_after=t_after,
            name=name[:255],
            status=ChangePair.STATUS_QUEUED,
            options=options,
            created_by=request.user if request.user.is_authenticated else None,
        )

        # Hand off to Celery. We pass the pair id (not the model instance,
        # because eval_async serializes source code and can't pickle ORM).
        try:
            async_result = run_function_async(
                _run_change_detection_safe, pair.id, with_progress=True,
            )
            pair.celery_task_id = async_result.task_id
            pair.save(update_fields=['celery_task_id', 'updated_at'])
        except Exception as e:
            pair.status = ChangePair.STATUS_FAILED
            pair.error_message = f"Failed to enqueue worker: {e}"
            pair.save(update_fields=['status', 'error_message', 'updated_at'])
            return Response({'error': pair.error_message}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'id': pair.id,
            'celery_task_id': pair.celery_task_id,
            'status': pair.status,
            'name': pair.name,
        }, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class ChangePairList(ChangeDetectAPIView):
    """GET /api/plugins/changedetect/project/<project_id>/changedetect/list"""
    permission_classes = (permissions.AllowAny,)

    def get(self, request, project_id=None):
        project = get_and_check_project(request, project_id)
        if not project:
            return Response({'error': _('Project not found.')}, status=status.HTTP_404_NOT_FOUND)
        if not project.public:
            check_project_perms(request, project, ('view_project',))

        pairs = project.change_pairs.select_related('task_before', 'task_after').prefetch_related('results')[:200]
        out = []
        for p in pairs:
            out.append({
                'id': p.id,
                'name': p.name,
                'status': p.status,
                'task_before': p.task_before_id,
                'task_after': p.task_after_id,
                'task_before_name': p.task_before.name,
                'task_after_name': p.task_after.name,
                'options': p.options,
                'error_message': p.error_message,
                'created_at': p.created_at.isoformat(),
                'updated_at': p.updated_at.isoformat(),
                'results': [
                    {
                        'id': r.id,
                        'layer_type': r.layer_type,
                        'stats': r.stats,
                        'has_thumbnail': bool(r.thumbnail_path),
                    }
                    for r in p.results.all()
                ],
            })
        return Response({'pairs': out}, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class ChangePairRun(ChangeDetectAPIView):
    """
    POST /api/plugins/changedetect/changedetect/pair/<pair_id>/run

    (Re-)runs the worker for an existing ChangePair. Resets status to
    QUEUED, clears error_message, and re-enqueues Celery. Used by the
    frontend "Run" button on the panel.
    """
    permission_classes = (permissions.AllowAny,)

    def post(self, request, pk=None, **kwargs):
        pair = _get_pair_or_404(request, pk)
        if not (pair.project.public):
            check_project_perms(request, pair.project, ('change_project',))

        pair.status = ChangePair.STATUS_QUEUED
        pair.error_message = ''
        # Merge any updated options from the request body
        new_options = request.data.get('options') if hasattr(request, 'data') else None
        if isinstance(new_options, dict):
            existing = dict(pair.options or {})
            existing.update(new_options)
            pair.options = existing
        pair.save(update_fields=['status', 'error_message', 'options', 'updated_at'])

        try:
            async_result = run_function_async(
                _run_change_detection_safe, pair.id, with_progress=True,
            )
            pair.celery_task_id = async_result.task_id
            pair.save(update_fields=['celery_task_id', 'updated_at'])
        except Exception as e:
            pair.status = ChangePair.STATUS_FAILED
            pair.error_message = f"Failed to enqueue worker: {e}"
            pair.save(update_fields=['status', 'error_message', 'updated_at'])
            return Response({'error': pair.error_message},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'id': pair.id,
            'celery_task_id': pair.celery_task_id,
            'status': pair.status,
            'name': pair.name,
        }, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class ChangePairStatus(ChangeDetectAPIView):
    """
    GET /api/plugins/changedetect/changedetect/<pair_id>/status

    Combines DB state (authoritative) with live Celery progress (for
    RUNNING pairs). On DONE/FAILED the worker has already updated the
    DB row, so we just return that state.
    """
    permission_classes = (permissions.AllowAny,)

    def get(self, request, pk=None, **kwargs):
        pair = _get_pair_or_404(request, pk)

        out = {
            'id': pair.id,
            'status': pair.status,
            'error_message': pair.error_message,
            'updated_at': pair.updated_at.isoformat(),
        }

        # If still queued/running, ask Celery for live progress.
        if pair.status in (ChangePair.STATUS_QUEUED, ChangePair.STATUS_RUNNING, ChangePair.STATUS_PENDING):
            if pair.celery_task_id:
                res = TestSafeAsyncResult(pair.celery_task_id)
                if not res.ready():
                    info = res.info or {}
                    if isinstance(info, dict):
                        out['progress_status'] = info.get('status', '')
                        out['progress'] = info.get('progress', 0)
                else:
                    # Celery finished but DB row not yet updated — race window.
                    # Worker should have written before returning; if it didn't,
                    # surface the error from celery.
                    if res.state == "FAILURE":
                        out['status'] = ChangePair.STATUS_FAILED
                        try:
                            out['error_message'] = str(res.result)
                        except Exception:
                            out['error_message'] = "Worker failed (see server logs)"

        # Attach results
        out['results'] = [
            {
                'id': r.id,
                'layer_type': r.layer_type,
                'stats': r.stats,
            }
            for r in pair.results.all()
        ]
        return Response(out, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class ChangeResultDownload(ChangeDetectAPIView):
    """GET /api/plugins/changedetect/changedetect/<pair_id>/result/<result_id>/download"""
    permission_classes = (permissions.AllowAny,)

    def get(self, request, pk=None, result_id=None, **kwargs):
        pair = _get_pair_or_404(request, pk)
        try:
            result = pair.results.get(pk=result_id)
        except ChangeResult.DoesNotExist:
            raise Http404("ChangeResult not found")

        if not result.geojson_path or not os.path.isfile(result.geojson_path):
            return Response({'error': _('Result file missing on disk.')},
                            status=status.HTTP_410_GONE)

        filename = f"{pair.name.replace(' ', '_').replace('/', '-')}_{result.layer_type}.geojson"
        f = open(result.geojson_path, 'rb')
        return FileResponse(f, content_type='application/geo+json',
                            as_attachment=True, filename=filename)


@method_decorator(csrf_exempt, name='dispatch')
class ChangePairReport(ChangeDetectAPIView):
    """
    POST /api/plugins/changedetect/changedetect/pair/<pk>/report/

    Body (JSON):
      {
        "screenshot": "data:image/png;base64,...",   # full page with overlay
        "map":        "data:image/png;base64,...",   # optional: just the leaflet map
        "title_suffix": "Q1 vs Q2"                    # optional
      }

    Returns:
      application/pdf (the report file)
    """
    permission_classes = (permissions.AllowAny,)

    def post(self, request, pk=None, **kwargs):
        pair = _get_pair_or_404(request, pk)
        if pair.status != 'DONE':
            return Response({'error': _('Only DONE pairs can be exported as a report.')},
                            status=status.HTTP_400_BAD_REQUEST)

        body = request.data if hasattr(request, 'data') else {}
        screenshot_b64 = body.get('screenshot') if hasattr(body, 'get') else None
        map_b64 = body.get('map') if hasattr(body, 'get') else None
        title_suffix = body.get('title_suffix', '') if hasattr(body, 'get') else ''

        if not screenshot_b64:
            return Response({'error': _('Missing "screenshot" field (base64 PNG).')},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            from .report import build_report
            pdf_bytes = build_report(
                pair=pair, project=pair.project,
                screenshot_b64=screenshot_b64, map_b64=map_b64,
                title_suffix=title_suffix or '',
            )
        except ImportError as e:
            import traceback
            with open('/tmp/cd_report_err.log', 'w') as f:
                f.write(traceback.format_exc())
            return Response({'error': f'reportlab not installed: {e}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            import traceback
            with open('/tmp/cd_report_err.log', 'w') as f:
                f.write(traceback.format_exc())
            log.exception("PDF build failed")
            return Response({'error': f'PDF build failed: {e}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        safe_name = (pair.name or f'pair_{pair.id}').replace(' ', '_').replace('/', '-')[:60]
        filename = f'changedetect_{pair.id}_{safe_name}.pdf'
        resp = HttpResponse(pdf_bytes, content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="{filename}"'
        resp['Content-Length'] = str(len(pdf_bytes))
        return resp
