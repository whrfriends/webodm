from django.db import migrations, models


class Migration(migrations.Migration):
    """
    PluginAccess: admin-UI-configurable plugin visibility.

    Stores per-plugin access mode (public / superuser / restricted) and
    (for restricted) the set of allowed Django Groups. The framework hook
    PluginBase.user_can_access() reads this table on every request, so
    permission changes take effect immediately without a webapp restart.
    """
    dependencies = [
        ('app', '0051_init_basemaps'),
        ('auth', '__first__'),  # Group model is in django.contrib.auth
    ]

    operations = [
        migrations.CreateModel(
            name='PluginAccess',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('plugin_name', models.CharField(help_text='Plugin folder name (matches coreplugins/<plugin_name>/)', max_length=64, unique=True)),
                ('access_mode', models.CharField(choices=[('public', 'Public \u2014 any authenticated user'), ('superuser', 'Superuser only'), ('restricted', 'Restricted to selected groups')], default='public', help_text='public = any authenticated user. superuser = only superusers. restricted = only listed groups (superusers always allowed).', max_length=16)),
                ('notes', models.CharField(blank=True, help_text='Optional description for the admin (e.g. who should be in this group)', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('groups', models.ManyToManyField(blank=True, help_text='Groups allowed when access_mode = restricted. Ignored for public / superuser modes.', related_name='plugin_access_set', to='auth.Group')),
            ],
            options={
                'verbose_name': 'Plugin access',
                'verbose_name_plural': 'Plugin access',
                'ordering': ['plugin_name'],
            },
        ),
    ]