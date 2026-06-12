"""
PluginAccess: admin-UI-configurable plugin visibility / access control.

One row per plugin (`plugin_name` is the folder name under `coreplugins/`).
Each row has an `access_mode` and (when restricted) a set of `groups`.

The `PluginBase.user_can_access(request)` hook (app/plugins/plugin_base.py)
queries this table; superusers are always allowed. Plugins without a row
default to `public` (any authenticated user can access) — backward compatible
with plugins written before the access-control feature was added.

Why a model instead of reusing Django's Permission table?
  - Django's Permission is tied to a Model via ContentType; we don't want
    every plugin to ship a dummy Model just to host permissions.
  - This single table is easier to introspect and to render in admin UI.
  - It survives plugin code changes (the table outlives any one plugin).
"""
from django.db import models
from django.contrib.auth.models import Group


class PluginAccess(models.Model):
    ACCESS_PUBLIC = "public"
    ACCESS_SUPERUSER = "superuser"
    ACCESS_RESTRICTED = "restricted"

    ACCESS_MODES = [
        (ACCESS_PUBLIC, "Public — any authenticated user"),
        (ACCESS_SUPERUSER, "Superuser only"),
        (ACCESS_RESTRICTED, "Restricted to selected groups"),
    ]

    plugin_name = models.CharField(
        max_length=64,
        unique=True,
        help_text="Plugin folder name (matches `coreplugins/<plugin_name>/`)",
    )
    access_mode = models.CharField(
        max_length=16,
        choices=ACCESS_MODES,
        default=ACCESS_PUBLIC,
        help_text=(
            "public = any authenticated user. "
            "superuser = only superusers. "
            "restricted = only listed groups (superusers always allowed)."
        ),
    )
    groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name="plugin_access_set",
        help_text="Groups allowed when access_mode = restricted. "
                  "Ignored for public / superuser modes.",
    )
    notes = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional description for the admin (e.g. who should be in this group)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Plugin access"
        verbose_name_plural = "Plugin access"
        ordering = ["plugin_name"]

    def __str__(self):
        return "{} [{}]".format(self.plugin_name, self.get_access_mode_display())

    def group_names(self):
        return ", ".join(self.groups.values_list("name", flat=True)) or "—"
    group_names.short_description = "Allowed groups"