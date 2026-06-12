"""Hand-written initial migration.

Reason: `makemigrations` would emit `import coreplugins.road-attributes.models`
which is a SyntaxError. We hand-write the migration to:
1. Avoid the dash-name import.
2. Use `django.utils.module_loading.import_string` for string defaults
   (Django's own resolver, supports dash names).

Run with:
    docker exec webapp python manage.py migrate road_attributes
"""
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True
    dependencies = [
        ("app", "__first__"),  # FK to app.Project + app.Task
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        # If flight-planner is installed we depend on its migration.
        # We do NOT hard-depend to keep the plugin optional; the FK is
        # nullable so migration is safe without flight-planner too.
    ]

    operations = [
        migrations.CreateModel(
            name="RoadAttributeType",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(help_text="枚举代码,英文+下划线,例如 crack_longitudinal / pothole / marking_wear", max_length=64, unique=True)),
                ("name_zh", models.CharField(help_text="中文名(显示用)", max_length=120)),
                ("name_en", models.CharField(blank=True, help_text="英文名(显示用)", max_length=120)),
                ("category", models.CharField(choices=[("surface", "路面病害"), ("facility", "沿线设施"), ("sign", "交通标志"), ("marking", "交通标线"), ("structure", "桥涵结构"), ("drainage", "排水设施"), ("greening", "绿化"), ("environment", "路域环境"), ("other", "其他")], default="surface", help_text="属性大类", max_length=32)),
                ("severity_levels", models.TextField(blank=True, default='coreplugins.road-attributes.models.json_list_default', help_text="严重程度等级定义,JSON 列表;为空时用 DEFAULT_SEVERITY_LEVELS")),
                ("unit", models.CharField(blank=True, help_text="默认计量单位(米/毫米/处/平方米),仅作 UI 提示", max_length=20)),
                ("description", models.TextField(blank=True, help_text="说明/识别方法")),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Road Attribute Type",
                "verbose_name_plural": "Road Attribute Types",
                "db_table": "road_attributes_type",
                "ordering": ["sort_order", "code"],
            },
        ),
        migrations.CreateModel(
            name="Road",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="道路名称", max_length=200)),
                ("code", models.CharField(blank=True, help_text="道路编号", max_length=50)),
                ("road_class", models.CharField(choices=[("expressway", "高速公路"), ("national", "国道"), ("provincial", "省道"), ("county", "县道"), ("township", "乡道"), ("village", "村道"), ("other", "其他")], default="other", max_length=20)),
                ("surface_type", models.CharField(choices=[("asphalt", "沥青"), ("concrete", "水泥混凝土"), ("gravel", "砂石"), ("soil", "土路"), ("brick", "砖石"), ("mixed", "混合"), ("other", "其他")], default="asphalt", max_length=20)),
                ("lanes", models.PositiveIntegerField(default=2, help_text="车道数")),
                ("width_m", models.FloatField(blank=True, help_text="路宽(米)", null=True)),
                ("total_length_m", models.FloatField(blank=True, help_text="总长(米)", null=True)),
                ("speed_limit_kmh", models.PositiveIntegerField(blank=True, null=True)),
                ("admin_region", models.CharField(blank=True, help_text="所属行政区划", max_length=200)),
                ("start_point", models.TextField(blank=True, default='coreplugins.road-attributes.models.json_default', help_text="起点 {lat, lng}")),
                ("end_point", models.TextField(blank=True, default='coreplugins.road-attributes.models.json_default', help_text="终点 {lat, lng}")),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=models.PROTECT, related_name="road_attributes_roads", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(on_delete=models.CASCADE, related_name="road_attributes_roads", to="app.project", help_text="归属 WebODM 项目")),
            ],
            options={
                "verbose_name": "Road",
                "verbose_name_plural": "Roads",
                "db_table": "road_attributes_road",
                "ordering": ["name"],
            },
        ),
        migrations.AddIndex(
            model_name="road",
            index=models.Index(fields=["project", "name"], name="ra_road_proj_name_idx"),
        ),
        migrations.AddIndex(
            model_name="road",
            index=models.Index(fields=["road_class"], name="ra_road_class_idx"),
        ),
        migrations.CreateModel(
            name="RoadSegment",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("seq", models.PositiveIntegerField(help_text="路段在 road 内的顺序号")),
                ("name", models.CharField(blank=True, max_length=200)),
                ("direction", models.CharField(choices=[("bidirectional", "双向"), ("up", "上行"), ("down", "下行")], default="bidirectional", max_length=20)),
                ("start_stake", models.CharField(blank=True, help_text="起点桩号", max_length=20)),
                ("end_stake", models.CharField(blank=True, help_text="终点桩号", max_length=20)),
                ("start_point", models.TextField(blank=True, default='coreplugins.road-attributes.models.json_default', help_text="起点 {lat, lng, alt?}")),
                ("end_point", models.TextField(blank=True, default='coreplugins.road-attributes.models.json_default', help_text="终点 {lat, lng, alt?}")),
                ("length_m", models.FloatField(help_text="路段长度(米)")),
                ("width_m", models.FloatField(blank=True, help_text="路段路宽(米)", null=True)),
                ("centerline", models.TextField(blank=True, default='coreplugins.road-attributes.models.json_list_default', help_text="中心线经纬度序列")),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("road", models.ForeignKey(on_delete=models.CASCADE, related_name="segments", to="road_attributes.road")),
            ],
            options={
                "verbose_name": "Road Segment",
                "verbose_name_plural": "Road Segments",
                "db_table": "road_attributes_segment",
                "ordering": ["road", "seq"],
                "unique_together": {("road", "seq")},
            },
        ),
        migrations.AddIndex(
            model_name="roadsegment",
            index=models.Index(fields=["road", "seq"], name="ra_seg_road_seq_idx"),
        ),
        migrations.CreateModel(
            name="AttributeImage",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(help_text="属性照片原图", upload_to="road_attributes/%Y/%m/")),
                ("thumbnail", models.ImageField(blank=True, null=True, upload_to="road_attributes/thumbs/%Y/%m/")),
                ("captured_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("position", models.TextField(blank=True, default='coreplugins.road-attributes.models.json_default', help_text="{lat, lng, alt?, heading?, gimbal_pitch?}")),
                ("camera_info", models.TextField(blank=True, default='coreplugins.road-attributes.models.json_default', help_text="拍摄参数 {model, focal_length, iso, shutter, ...}")),
                ("notes", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("uploaded_by", models.ForeignKey(on_delete=models.PROTECT, related_name="uploaded_road_attribute_images", to=settings.AUTH_USER_MODEL)),
                ("webodm_task", models.ForeignKey(blank=True, help_text="照片所属的 WebODM 3D 任务(可选)", null=True, on_delete=models.SET_NULL, related_name="road_attribute_images", to="app.task")),
            ],
            options={
                "verbose_name": "Attribute Image",
                "verbose_name_plural": "Attribute Images",
                "db_table": "road_attributes_image",
                "ordering": ["-captured_at"],
            },
        ),
        migrations.CreateModel(
            name="RoadAttribute",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("severity", models.CharField(blank=True, help_text="严重程度 code", max_length=20)),
                ("position", models.TextField(blank=True, default='coreplugins.road-attributes.models.json_default', help_text="{lat, lng, alt?}")),
                ("stake", models.CharField(blank=True, help_text="发现处桩号", max_length=20)),
                ("length_m", models.FloatField(blank=True, help_text="长度(米)", null=True)),
                ("width_m", models.FloatField(blank=True, help_text="宽度(米/毫米单位由 attribute_type.unit 决定)", null=True)),
                ("depth_mm", models.FloatField(blank=True, help_text="深度(毫米)", null=True)),
                ("area_m2", models.FloatField(blank=True, help_text="面积(平方米)", null=True)),
                ("quantity", models.PositiveIntegerField(blank=True, help_text="数量(条/处)", null=True)),
                ("status", models.CharField(choices=[("open", "待处理"), ("in_progress", "处理中"), ("repaired", "已修复"), ("verified", "已验收"), ("ignored", "忽略")], default="open", max_length=20)),
                ("description", models.TextField(blank=True)),
                ("discovered_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("attribute_type", models.ForeignKey(on_delete=models.PROTECT, related_name="instances", to="road_attributes.roadattributetype")),
                ("images", models.ManyToManyField(blank=True, related_name="attributes", to="road_attributes.attributeimage")),
                ("inspector", models.ForeignKey(on_delete=models.PROTECT, related_name="road_attributes_inspected", to=settings.AUTH_USER_MODEL)),
                ("segment", models.ForeignKey(on_delete=models.CASCADE, related_name="attributes", to="road_attributes.roadsegment")),
                # Flight-planner FK is optional; declared with null=True so the
                # migration succeeds even if flight-planner is not installed.
                ("flight_mission", models.ForeignKey(blank=True, help_text="巡检时使用的 flight-planner 任务", null=True, on_delete=models.SET_NULL, related_name="road_attributes", to="flight_planner.flightmission")),
                ("webodm_task", models.ForeignKey(blank=True, help_text="WebODM 3D 重建任务", null=True, on_delete=models.SET_NULL, related_name="road_attributes", to="app.task")),
            ],
            options={
                "verbose_name": "Road Attribute",
                "verbose_name_plural": "Road Attributes",
                "db_table": "road_attributes_attribute",
                "ordering": ["-discovered_at"],
            },
        ),
        migrations.AddIndex(
            model_name="roadattribute",
            index=models.Index(fields=["segment", "attribute_type"], name="ra_attr_seg_type_idx"),
        ),
        migrations.AddIndex(
            model_name="roadattribute",
            index=models.Index(fields=["status"], name="ra_attr_status_idx"),
        ),
        migrations.AddIndex(
            model_name="roadattribute",
            index=models.Index(fields=["severity"], name="ra_attr_sev_idx"),
        ),
        migrations.AddIndex(
            model_name="roadattribute",
            index=models.Index(fields=["discovered_at"], name="ra_attr_discovered_idx"),
        ),
    ]
