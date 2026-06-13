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


class ChangeAnnotation(models.Model):
    """
    AI-generated label for a single change-detection feature.

    One row per (result, feature_index) tuple. We re-run the AI
    classification whenever the user clicks "AI 识别", and we
    overwrite the existing rows (same key) so we don't accumulate
    stale labels. The (result, feature_index) key is stable because
    the change-detection worker always emits features in the same
    order (sorted by descending area).

    `centroid` / `bbox` are stored as denormalised columns (in
    addition to the LABEL_COLORS lookup) so we can colour the map
    overlay without joining back to the GeoJSON file.
    """

    # Stable id (result, feature_index). We don't use Django's default
    # bigint PK here because the API client needs to upsert by key.
    result = models.ForeignKey(
        'ChangeResult',
        on_delete=models.CASCADE,
        related_name='ai_annotations',
    )
    feature_index = models.PositiveIntegerField(
        help_text="Index of the feature inside the result's GeoJSON "
                  "FeatureCollection (sorted by area, descending).",
    )
    label = models.CharField(
        max_length=32,
        help_text="One of ALLOWED_LABELS in ai_classify.py.",
    )
    confidence = models.FloatField(
        default=0.0,
        help_text="0.0-1.0 confidence reported by the classifier.",
    )
    source = models.CharField(
        max_length=32,
        default="llm_fallback",
        help_text="geodeep_aerovision / geodeep_cars / llm_fallback",
    )
    rationale = models.TextField(
        blank=True, default="",
        help_text="Short human-readable Chinese reason from the model.",
    )
    centroid = JSONField(
        default=list, blank=True,
        help_text="[lng, lat] of the feature's geometric centroid.",
    )
    bbox = JSONField(
        default=list, blank=True,
        help_text="[minx, miny, maxx, maxy] of the feature's bbox.",
    )
    area_m2 = models.FloatField(
        default=0.0,
        help_text="Area in m² (denormalised so the API can list without re-reading GeoJSON).",
    )
    model = models.CharField(
        max_length=64, default="",
        help_text="Model id used (e.g. 'aerovision' or 'MiniMax-M3').",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "changedetect"
        # One annotation per (result, feature)
        unique_together = [("result", "feature_index")]
        indexes = [
            models.Index(fields=["result", "label"]),
        ]
        ordering = ["result_id", "feature_index"]

    def __str__(self):
        return f"ChangeAnnotation({self.result_id}#{self.feature_index}={self.label})"


class ChangeInsight(models.Model):
    """
    LLM-generated narrative for a finished pair.

    Two flavours, distinguished by the `kind` field:
      - 'analyze': the long Chinese interpretation (analyze_pair_changes)
      - 'summary': the ≤100-字 report summary (summarize_for_report)
    Both are keyed on the pair so we can show the latest insight
    alongside the pair list, and re-running the LLM simply overwrites.
    """

    KIND_CHOICES = [
        ("analyze", "变化原因解读"),
        ("summary", "报告摘要"),
    ]
    pair = models.ForeignKey(
        'ChangePair',
        on_delete=models.CASCADE,
        related_name='ai_insights',
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default="analyze")
    text = models.TextField(
        help_text="LLM-generated Chinese text.",
    )
    model = models.CharField(
        max_length=64, default="",
        help_text="Model id that produced this insight (MiniMax-M3 by default).",
    )
    usage = JSONField(
        default=dict, blank=True,
        help_text="Token usage stats from the LLM response.",
    )
    elapsed_ms = models.IntegerField(
        default=0,
        help_text="Round-trip time to the LLM gateway.",
    )
    error = models.TextField(
        blank=True, default="",
        help_text="If the LLM call failed, the error string. Otherwise empty.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "changedetect"
        unique_together = [("pair", "kind")]
        indexes = [
            models.Index(fields=["pair", "kind"]),
        ]
        ordering = ["pair_id", "kind"]

    def __str__(self):
        return f"ChangeInsight(pair={self.pair_id}, kind={self.kind})"


class PairRecommendation(models.Model):
    """
    Cached LLM-suggested pair combinations for a project. The cache
    lets the project map load recommendations instantly (no LLM call
    on every page open) while still being refreshed when the user
    clicks "AI 推荐".

    The recommended (task_a, task_b) IDs are stored as plain UUID
    strings to avoid a hard FK to app.Task (which can be deleted).
    """

    project = models.ForeignKey(
        'app.Project',
        on_delete=models.CASCADE,
        related_name='cd_recommendations',
    )
    rank = models.PositiveSmallIntegerField(
        help_text="1 = best, 2 = next, etc.",
    )
    task_a_id = models.CharField(
        max_length=64,
        help_text="Task id (UUID string) of the earlier task.",
    )
    task_b_id = models.CharField(
        max_length=64,
        help_text="Task id of the later task.",
    )
    reason = models.TextField(
        blank=True, default="",
        help_text="1-2 sentence Chinese justification from the LLM.",
    )
    model = models.CharField(max_length=64, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "changedetect"
        unique_together = [("project", "rank")]
        ordering = ["project_id", "rank"]

    def __str__(self):
        return f"PairRecommendation(project={self.project_id}, rank={self.rank})"
