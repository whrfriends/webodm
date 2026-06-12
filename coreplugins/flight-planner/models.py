"""
Django models for the Flight Planner plugin.

Two tables:
  - flight_planner.FlightProject: a top-level container (drone model + name)
  - flight_planner.FlightMission: a generated flight (waypoints + params)

A mission can exist standalone (project=NULL) or be linked to a project.
Project <-> Mission is a 1-to-many: project.missions.all().

Replaces the previous disk-based JSON persistence
(${MEDIA_ROOT}/plugins/flight-planner/<uuid>/mission.json). All reads and
writes go through the ORM, which is multi-worker safe (gunicorn shares the
PostgreSQL connection pool, not in-process dicts).
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.fields import JSONField
from django.db import models


def _gen_short_id() -> str:
    """12-char hex id, matching the old `uuid.uuid4().hex[:12]` shape.

    Kept as a callable (not a default value) so each row gets a fresh id.
    """
    return uuid.uuid4().hex[:12]


class FlightProject(models.Model):
    """A flight planning project — bundles missions for one drone model."""

    id = models.CharField(
        primary_key=True,
        max_length=12,
        default=_gen_short_id,
        editable=False,
    )
    name = models.CharField(max_length=128)
    drone_model = models.CharField(
        max_length=64,
        help_text="DJI model key, e.g. M30, MINI_3, AVATA_2. See drone_models.DRONE_MODELS.",
    )
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Optional link to a WebODM user. Nullable so the plugin still works in
    # the existing AllowAny setup. When wired up to auth later, owner can be
    # required and django-guardian object permissions can be assigned.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="flight_planner_projects",
    )

    class Meta:
        app_label = "flight_planner"
        ordering = ["-updated_at"]
        verbose_name = "Flight Project"
        verbose_name_plural = "Flight Projects"

    def __str__(self) -> str:
        return f"{self.name} [{self.drone_model}]"


class FlightMission(models.Model):
    """A generated flight mission — polygon survey, spiral, orbit, etc.

    waypoints / params / bounds / stats are stored as JSONB. The number of
    waypoints for a polygon survey can be in the thousands, but PostgreSQL
    JSONB handles that fine and we keep the round-trip simple (no separate
    rows per waypoint).
    """

    KIND_CHOICES = [
        ("polygon", "Polygon survey"),
        ("spiral", "Spiral"),
        ("orbit", "Orbit"),
        ("cable", "Cable cam"),
        ("corkscrew", "Corkscrew"),
        ("grid", "Panel grid"),
    ]

    id = models.CharField(
        primary_key=True,
        max_length=12,
        default=_gen_short_id,
        editable=False,
    )
    project = models.ForeignKey(
        FlightProject,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="missions",
    )
    name = models.CharField(max_length=128)
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    # algo = polygon vertex list / center+radius / cable path, etc.
    # wpml = 14 task-level DJI parameters.
    params = JSONField(
        default=dict,
        blank=True,
        help_text="Algorithm + WPML parameters: {'algo': {...}, 'wpml': {...}}",
    )
    waypoints = JSONField(
        default=list,
        blank=True,
        help_text="List of waypoint dicts: {lat, lon, alt, speed, gimbal_pitch, ...}",
    )
    bounds = JSONField(
        default=list,
        blank=True,
        help_text="[min_lat, min_lon, max_lat, max_lon]",
    )
    stats = JSONField(
        default=dict,
        blank=True,
        help_text="{waypoints, distance_m, area_m2, duration_s, ...}",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "flight_planner"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["project", "-updated_at"]),
            models.Index(fields=["kind"]),
        ]
        verbose_name = "Flight Mission"
        verbose_name_plural = "Flight Missions"

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"
