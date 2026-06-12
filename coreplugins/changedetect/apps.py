"""
Django app config for the Change Detection plugin.

Registered in webodm/settings.py INSTALLED_APPS as
'coreplugins.changedetect.apps.ChangeDetectConfig' so Django discovers
models.py and runs the standard migrations machinery.

label='changedetect' keeps DB table names clean
(`changedetect_changepair`, `changedetect_changeresult`).
"""

from django.apps import AppConfig


class ChangeDetectConfig(AppConfig):
    name = "coreplugins.changedetect"
    label = "changedetect"
    verbose_name = "Change Detection"
