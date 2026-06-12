"""
Django app config for the Flight Planner plugin.

Registered in webodm/settings.py INSTALLED_APPS as
'coreplugins.flight-planner.apps.FlightPlannerConfig' so Django discovers
models.py and runs the standard migrations machinery.

The label 'flight_planner' (with underscore) is the migrations app
namespace — DB tables are named `flight_planner_flightproject` and
`flight_planner_flightmission`. The dotted name uses the actual
on-disk path 'coreplugins.flight-planner' (with dash).
"""

from django.apps import AppConfig


class FlightPlannerConfig(AppConfig):
    name = "coreplugins.flight-planner"
    label = "flight_planner"
    verbose_name = "Flight Planner"
