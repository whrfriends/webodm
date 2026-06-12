"""
Road Attributes plugin package.

WebODM's plugin loader (app/plugins/functions.py) does:
    module = importlib.import_module("coreplugins.road-attributes")
    plugin = (getattr(module, "Plugin"))()

We satisfy that with a module-level __getattr__ that imports plugin.py on
first attribute access. Note: do NOT cache into sys.modules.__dict__ here
- that pattern was observed to cause "maximum recursion depth exceeded"
errors with Django's app-loading machinery in some edge cases.
"""
import importlib

_LAZY_ATTRS = ("Plugin", "PluginBase", "Menu", "MountPoint")


def __getattr__(name):
    if name in _LAZY_ATTRS:
        mod = importlib.import_module("coreplugins.road-attributes.plugin")
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(list(globals().keys()) + list(_LAZY_ATTRS)))
