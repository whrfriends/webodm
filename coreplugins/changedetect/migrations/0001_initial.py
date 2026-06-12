# Generated for the Change Detection plugin.
# References app.Project and app.Task (latest app migration 0052_plugin_access)
# and the swappable AUTH_USER_MODEL. Manually authored (no `makemigrations`
# run) to keep the migration deterministic.

import django.contrib.postgres.fields.jsonb
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('app', '0052_plugin_access'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ChangePair',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(
                    blank=True, default='', max_length=255,
                    help_text="Optional human label, e.g. '2024-Q1 vs 2024-Q3'.",
                )),
                ('status', models.CharField(
                    choices=[
                        ('PENDING', 'Pending'),
                        ('QUEUED', 'Queued'),
                        ('RUNNING', 'Running'),
                        ('DONE', 'Done'),
                        ('FAILED', 'Failed'),
                    ],
                    default='PENDING', max_length=16,
                )),
                ('options', django.contrib.postgres.fields.jsonb.JSONField(
                    blank=True, default=dict,
                    help_text="User-tweakable thresholds: pixel_threshold, dsm_min_h, min_area_m2, ...",
                )),
                ('error_message', models.TextField(blank=True, default='')),
                ('celery_task_id', models.CharField(blank=True, default='', max_length=64)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('project', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='change_pairs',
                    to='app.Project',
                )),
                ('task_before', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='cd_before_pairs',
                    to='app.Task',
                )),
                ('task_after', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='cd_after_pairs',
                    to='app.Task',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='change_pairs',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='changepair',
            index=models.Index(fields=['project', '-created_at'], name='changedetect_cp_proj_idx'),
        ),
        migrations.AddIndex(
            model_name='changepair',
            index=models.Index(fields=['status'], name='changedetect_cp_status_idx'),
        ),
        migrations.CreateModel(
            name='ChangeResult',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('layer_type', models.CharField(
                    choices=[
                        ('pixel', 'Pixel difference'),
                        ('dsm', 'DSM difference'),
                        ('dtm', 'DTM difference'),
                    ],
                    max_length=16,
                )),
                ('geojson_path', models.CharField(max_length=512)),
                ('thumbnail_path', models.CharField(blank=True, default='', max_length=512)),
                ('stats', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('pair', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='results',
                    to='changedetect.ChangePair',
                )),
            ],
            options={
                'ordering': ['layer_type'],
            },
        ),
        migrations.AddIndex(
            model_name='changeresult',
            index=models.Index(fields=['pair', 'layer_type'], name='changedetect_cr_pair_idx'),
        ),
    ]
