from django.views.decorators.csrf import csrf_exempt
from app.plugins import PluginBase
from app.plugins import MountPoint
from .api import (
    ProjectChangeDetect, ChangeResultDownload, ChangePairList, ChangePairStatus,
    ChangePairRun, ChangePairReport,
)


class Plugin(PluginBase):
    def include_js_files(self):
        # Order matters: html2canvas must be loaded before main.js
        # since main.js uses window.html2canvas for the report download.
        return ['html2canvas.min.js', 'main.js']

    def include_css_files(self):
        return ['build/Changedetect.css']

    def api_mount_points(self):
        # CSRF: we have to apply csrf_exempt as a real decorator to the
        # view function returned by as_view(). Setting
        # `view.csrf_exempt = True` was a Django <1.10 trick; modern
        # Django only honors the @csrf_exempt wrapper. The DRF view
        # classes also carry @method_decorator(csrf_exempt,
        # name='dispatch') but that one decorates dispatch(), not the
        # as_view() result, so it doesn't help here either.
        def _exempt(view_cls):
            return csrf_exempt(view_cls.as_view())
        return [
            # project-scoped
            MountPoint('project/(?P<project_id>[^/.]+)/changedetect/create', _exempt(ProjectChangeDetect)),
            MountPoint('project/(?P<project_id>[^/.]+)/changedetect/list', _exempt(ChangePairList)),
            # pair-scoped
            MountPoint('changedetect/pair/(?P<pk>[^/.]+)/status', _exempt(ChangePairStatus)),
            MountPoint('changedetect/pair/(?P<pk>[^/.]+)/run', _exempt(ChangePairRun)),
            MountPoint('changedetect/pair/(?P<pk>[^/.]+)/report', _exempt(ChangePairReport)),
            MountPoint('changedetect/pair/(?P<pk>[^/.]+)/result/(?P<result_id>[^/.]+)/download', _exempt(ChangeResultDownload)),
        ]
