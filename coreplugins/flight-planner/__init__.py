"""Flight Planner plugin package.

Lazy-loads plugin.py to avoid Django apps-registry circularity: when this
package is registered via INSTALLED_APPS, Django's apps.populate() loads
this file before the auth / guardian / app.models chain is fully wired.
Importing plugin.py (which transitively imports app.models) at module load
time would explode with `AppRegistryNotReady`.

The PluginBase loader in `app/plugins/functions.py` does:
    module = importlib.import_module("coreplugins.flight-planner")
    plugin = (getattr(module, "Plugin"))()

We satisfy that with a module-level __getattr__ that imports plugin.py on
first attribute access. Subsequent getattr calls reuse the cached module.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

_LAZY_ATTRS = ("Plugin", "PluginBase", "Menu", "MountPoint")


def __getattr__(name: str) -> Any:
    if name in _LAZY_ATTRS or name.isupper():
        mod = importlib.import_module("coreplugins.flight-planner.plugin")
        value = getattr(mod, name)
        sys.modules[__name__].__dict__[name] = value  # cache
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list:
    return sorted(set(globals().keys()) | set(_LAZY_ATTRS))
