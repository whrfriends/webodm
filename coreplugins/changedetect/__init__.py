"""
Change Detection plugin package.

WebODM's plugin loader (app/plugins/functions.py) does:
    module = importlib.import_module("coreplugins.changedetect")
    plugin = (getattr(module, "Plugin"))()

We satisfy that with a module-level __getattr__ that imports plugin.py
on first attribute access. This avoids the AppRegistryNotReady crash
that an eager `from .plugin import *` would cause during Django's
apps.populate() — at that point `app.models` hasn't been imported by
Django, and plugin.py's transitive import of `app.plugins.PluginBase`
chains into `app.models.project` which imports guardian -> auth.models,
triggering apps.get_containing_app_config while apps aren't ready yet.

Pattern lifted from coreplugins/road-attributes/__init__.py.
"""
import importlib

_LAZY_ATTRS = ("Plugin", "PluginBase", "MountPoint",
               "ProjectChangeDetect", "ChangePairList",
               "ChangePairStatus", "ChangeResultDownload",
               "run_change_detection")


def __getattr__(name):
    if name in _LAZY_ATTRS:
        mod = importlib.import_module("coreplugins.changedetect.plugin")
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(list(globals().keys()) + list(_LAZY_ATTRS)))


# IMPORTANT: explicitly import worker.py at package load time so the
# module-level patch in worker.py (which monkey-patches
# app.plugins.worker.eval_async to seed the eval namespace with our
# module's globals) takes effect on **both** the webapp and the
# worker container. The webapp container is what serializes the celery
# task arguments; the worker container is what actually executes them.
# Without this, the patch only runs in the container that happens to
# import worker.py first — and since the patch modifies a global
# function in app.plugins.worker, it must run before the first celery
# task is dispatched.
#
# Side effect: importing worker.py triggers an import of our models
# (ChangePair, ChangeResult) which forces Django to load our app_label
# 'changedetect' — but the Meta.app_label = "changedetect" class
# attribute handles that case.
importlib.import_module("coreplugins.changedetect.worker")
