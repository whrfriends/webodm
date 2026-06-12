from app.plugins import PluginBase
from app.plugins import MountPoint
from .api import (
    ProjectChangeDetect, ChangeResultDownload, ChangePairList, ChangePairStatus,
    ChangePairRun,
)


class Plugin(PluginBase):
    def include_js_files(self):
        return ['main.js']

    def include_css_files(self):
        return ['build/Changedetect.css']

    def api_mount_points(self):
        # CSRF is handled in api.py via @method_decorator(csrf_exempt,
        # name='dispatch') on each DRF view class. We also set
        # csrf_exempt=True on the outer view function object here so
        # that Django's CsrfViewMiddleware does not block POSTs.
        def _exempt(view_cls):
            v = view_cls.as_view()
            v.csrf_exempt = True
            return v
        return [
            # project-scoped
            MountPoint('project/(?P<project_id>[^/.]+)/changedetect/create', _exempt(ProjectChangeDetect)),
            MountPoint('project/(?P<project_id>[^/.]+)/changedetect/list', _exempt(ChangePairList)),
            # pair-scoped
            MountPoint('changedetect/pair/(?P<pk>[^/.]+)/status', _exempt(ChangePairStatus)),
            MountPoint('changedetect/pair/(?P<pk>[^/.]+)/run', _exempt(ChangePairRun)),
            MountPoint('changedetect/pair/(?P<pk>[^/.]+)/result/(?P<result_id>[^/.]+)/download', _exempt(ChangeResultDownload)),
        ]
