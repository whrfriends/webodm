"""
Django models for the Change Detection plugin.

Two tables:
  - changedetect.ChangePair: a single temporal comparison between two tasks
    in the same project (task_before vs task_after, with parameters).
  - changedetect.ChangeResult: one result layer per pair (pixel diff,
    DSM diff, etc.). A pair can have multiple result layers.

Why ORM not disk-JSON (per WebODM conventions):
  - Multi-worker safe (gunicorn shares the DB, not in-process dicts).
  - django-guardian object permissions already wired up for Project/Task,
    we can reuse `check_project_perms` from app.api.common.
  - Querying/listing pairs per project becomes a simple ORM call.

`app_label` is declared explicitly in Meta so the model can be imported
without an AppConfig in INSTALLED_APPS. WebODM's boot script instantiates
the plugin before Django's app registry is fully ready, and the
container's settings.py isn't bind-mounted — so the alternative (rely on
auto app discovery) emits a warning and the plugin is never registered.
Same pattern as coreplugins.flight-planner/models.py.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.fields import JSONField
from django.db import models
from django.utils import timezone

# Note: do NOT import app.models.Project / app.models.Task at module level.
# Django's app registry isn't fully populated during plugin scan, and a
# top-level import of app.models pulls in guardian / contrib.auth chains
# too early. FKs use string `to='app.Project'` references (resolved by
# Django's app-loading machinery at migration time), and we lazy-import
# the models inside methods that need them. See flight-planner/models.py
# and road-attributes/models.py for the same convention.


class ChangePair(models.Model):
    """
    A temporal comparison between two tasks in the same project.

    task_before / task_after must belong to the same project
    (enforced in the API layer; not a DB-level constraint because
    Task.project is settable).
    """

    STATUS_PENDING = "PENDING"
    STATUS_QUEUED = "QUEUED"
    STATUS_RUNNING = "RUNNING"
    STATUS_DONE = "DONE"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    project = models.ForeignKey(
        'app.Project',
        on_delete=models.CASCADE,
        related_name='change_pairs',
    )
    task_before = models.ForeignKey(
        'app.Task',
        on_delete=models.CASCADE,
        related_name='cd_before_pairs',
    )
    task_after = models.ForeignKey(
        'app.Task',
        on_delete=models.CASCADE,
        related_name='cd_after_pairs',
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional human label, e.g. '2024-Q1 vs 2024-Q3'.",
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    options = JSONField(
        default=dict,
        blank=True,
        help_text="User-tweakable thresholds: pixel_threshold, dsm_min_h, "
                  "min_area_m2, enable_pixel, enable_dsm, crop_geojson (optional).",
    )
    error_message = models.TextField(blank=True, default="")

    celery_task_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Celery task id, used by frontend for progress polling.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="change_pairs",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "changedetect"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "-created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"ChangePair({self.id}, {self.task_before_id}->{self.task_after_id}, {self.status})"


class ChangeResult(models.Model):
    """
    One result layer produced by a ChangePair.

    A pair can produce multiple layers (pixel diff, DSM diff, DTM diff).
    Each layer has a GeoJSON file with detected change polygons and
    optional statistics (total area, area by direction, etc.).
    """

    LAYER_PIXEL = "pixel"
    LAYER_DSM = "dsm"
    LAYER_DTM = "dtm"
    LAYER_CHOICES = [
        (LAYER_PIXEL, "Pixel difference"),
        (LAYER_DSM, "DSM difference"),
        (LAYER_DTM, "DTM difference"),
    ]

    pair = models.ForeignKey(
        ChangePair,
        on_delete=models.CASCADE,
        related_name="results",
    )
    layer_type = models.CharField(max_length=16, choices=LAYER_CHOICES)
    geojson_path = models.CharField(
        max_length=512,
        help_text="Absolute path to the GeoJSON file with change polygons.",
    )
    thumbnail_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Optional PNG heatmap, served as a static asset.",
    )
    stats = JSONField(
        default=dict,
        blank=True,
        help_text="Stats: total_area_m2, added_area_m2, removed_area_m2, "
                  "polygon_count, mean_intensity, etc.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "changedetect"
        ordering = ["layer_type"]
        indexes = [
            models.Index(fields=["pair", "layer_type"]),
        ]

    def __str__(self):
        return f"ChangeResult({self.pair_id}, {self.layer_type})"
