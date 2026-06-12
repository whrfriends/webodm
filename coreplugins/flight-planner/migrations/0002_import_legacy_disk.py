"""
One-time data migration: import the old disk-based JSON files into the
new FlightProject / FlightMission Django models.

Before this refactor, the plugin stored projects and missions as JSON
files at:
  ${MEDIA_ROOT}/plugins/flight-planner/projects/<pid>/project.json
  ${MEDIA_ROOT}/plugins/flight-planner/<mid>/mission.json

After the ORM refactor, those JSON files become cold backups. This
migration copies them into PostgreSQL so users don't lose their work.

Django's migration system records the migration in `django_migrations`
so this only runs once. To re-run, manually delete the migration record
for ('flight_planner', '0002_import_legacy_disk').

RunPython functions are responsible for atomicity; we wrap the work in
a single transaction.atomic() so a partial import can be retried.
"""

from __future__ import annotations

import datetime
import importlib
import json
import os

from django.conf import settings
from django.db import migrations, transaction


PLUGIN_MEDIA_DIR = os.path.join(settings.MEDIA_ROOT, "plugins", "flight-planner")
PROJECTS_DIR = os.path.join(PLUGIN_MEDIA_DIR, "projects")


def _to_datetime(ts):
    """Convert a unix timestamp (float, may be None) to a tz-aware datetime."""
    if ts is None:
        return None
    try:
        return datetime.datetime.fromtimestamp(float(ts), tz=datetime.timezone.utc)
    except (ValueError, OSError, TypeError):
        return None


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def import_legacy_disk(apps, schema_editor):
    """Scan the disk for old project.json / mission.json and import them."""
    # Reach the models via the apps registry, not by import — Django's
    # migration framework wants models to be resolved at the migration
    # level (so historical models can be replayed).
    FlightProject = apps.get_model("flight_planner", "FlightProject")
    FlightMission = apps.get_model("flight_planner", "FlightMission")

    if not os.path.isdir(PLUGIN_MEDIA_DIR):
        return

    with transaction.atomic():
        # ---- 1. Import missions first (so projects can attach them) -------
        imported_missions = 0
        skipped_missions = 0
        for entry in os.listdir(PLUGIN_MEDIA_DIR):
            mission_path = os.path.join(PLUGIN_MEDIA_DIR, entry, "mission.json")
            if not os.path.isfile(mission_path):
                continue
            rec = _read_json(mission_path)
            if not rec or not isinstance(rec.get("id"), str):
                skipped_missions += 1
                continue
            mid = rec["id"]
            if FlightMission.objects.filter(pk=mid).exists():
                continue  # already imported
            FlightMission.objects.create(
                id=mid,
                project=None,  # linked below when projects are imported
                name=(rec.get("name") or "Mission")[:128],
                kind=(rec.get("kind") or "polygon")[:32],
                params=rec.get("params") or {},
                waypoints=rec.get("waypoints") or [],
                bounds=rec.get("bounds") or [],
                stats=rec.get("stats") or {},
                created_at=_to_datetime(rec.get("created_at")) or _to_datetime(rec.get("stats", {}).get("created_at")) or None,
                updated_at=_to_datetime(rec.get("updated_at")) or None,
            )
            imported_missions += 1

        # ---- 2. Import projects and link to their missions ---------------
        imported_projects = 0
        skipped_projects = 0
        if os.path.isdir(PROJECTS_DIR):
            for entry in os.listdir(PROJECTS_DIR):
                project_path = os.path.join(PROJECTS_DIR, entry, "project.json")
                if not os.path.isfile(project_path):
                    continue
                rec = _read_json(project_path)
                if not rec or not isinstance(rec.get("id"), str):
                    skipped_projects += 1
                    continue
                pid = rec["id"]
                if FlightProject.objects.filter(pk=pid).exists():
                    continue
                p = FlightProject.objects.create(
                    id=pid,
                    name=(rec.get("name") or "Project")[:128],
                    drone_model=(rec.get("drone_model") or "M30")[:64],
                    description=rec.get("description") or "",
                    created_at=_to_datetime(rec.get("created_at")) or None,
                    updated_at=_to_datetime(rec.get("updated_at")) or None,
                )
                # Attach the missions this project recorded
                for mid in rec.get("mission_ids", []):
                    FlightMission.objects.filter(pk=mid).update(project=p)
                imported_projects += 1

        # ---- 3. Summary log ---------------------------------------------
        if imported_projects or imported_missions:
            print(
                "[flight_planner 0002] imported {} projects ({} skipped), "
                "{} missions ({} skipped) from {} into PostgreSQL".format(
                    imported_projects, skipped_projects,
                    imported_missions, skipped_missions,
                    PLUGIN_MEDIA_DIR,
                )
            )


def reverse_noop(apps, schema_editor):
    """Reverse migration: leave the DB alone, just log a warning.

    Reverting this migration would orphan the new DB rows without
    restoring the disk files, so we do nothing on reverse. Operators who
    need to roll back should manually re-export from the DB.
    """
    print("[flight_planner 0002] reverse: leaving DB rows in place; "
          "disk JSON files are untouched.")


class Migration(migrations.Migration):

    dependencies = [
        ("flight_planner", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(import_legacy_disk, reverse_noop),
    ]
