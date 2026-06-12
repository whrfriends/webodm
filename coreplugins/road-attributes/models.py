"""
Road Attributes plugin - data model (5 tables).

Design goals:
- Roads, segments, attribute types, attribute records, and image evidence
  are first-class entities (not JSON blobs), so a query like "all potholes
  on segment 3 of road 7 with severity>=medium" is a single ORM call.
- Geometry: roads have ordered segments with start/end GPS points. We
  use TextField-stored JSON for portability across SQLite/MySQL/Postgres;
  the segment's `centerline` field is the canonical polyline.
- Cross-plugin FKs: a RoadAttribute can link to flight-planner.FlightMission
  (optional) and to app.Task (optional) so an attribute record inherits the
  context of the inspection flight and the WebODM 3D model.
- All timestamps are auto-managed. All string defaults use module-level
  callables (not lambdas) to survive serialization in migrations.

JSON-on-Django-2.2 note: WebODM 2.x ships Django 2.2, which has no
`models.JSONField` (added in Django 3.1). We store JSON in TextField and
serialize/deserialize in the serializer layer.
"""
import json
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


# ----- JSON helpers (callable, string-friendly for makemigrations) -----

def json_default():
    return json.dumps({}, ensure_ascii=False)


def json_list_default():
    return json.dumps([], ensure_ascii=False)


class _JSONTextField(models.TextField):
    """SQLite/MySQL-friendly JSON field. Stored as TEXT, serialized as JSON.

    The serializer layer handles JSON deserialization so the field stays
    a portable TextField at the DB layer. We do NOT override
    `to_python` / `from_db_value` here to keep the round-trip explicit.
    """
    description = "JSON (TextField-backed, portable)"


def _gen_uuid_short():
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Enums (kept in module scope for migration stability)
# ---------------------------------------------------------------------------

ROAD_CLASS_CHOICES = (
    ("expressway", "高速公路"),
    ("national", "国道"),
    ("provincial", "省道"),
    ("county", "县道"),
    ("township", "乡道"),
    ("village", "村道"),
    ("other", "其他"),
)

SURFACE_TYPE_CHOICES = (
    ("asphalt", "沥青"),
    ("concrete", "水泥混凝土"),
    ("gravel", "砂石"),
    ("soil", "土路"),
    ("brick", "砖石"),
    ("mixed", "混合"),
    ("other", "其他"),
)

DIRECTION_CHOICES = (
    ("bidirectional", "双向"),
    ("up", "上行"),
    ("down", "下行"),
)

ATTRIBUTE_CATEGORY_CHOICES = (
    ("surface", "路面病害"),
    ("facility", "沿线设施"),
    ("sign", "交通标志"),
    ("marking", "交通标线"),
    ("structure", "桥涵结构"),
    ("drainage", "排水设施"),
    ("greening", "绿化"),
    ("environment", "路域环境"),
    ("other", "其他"),
)

# Default severity ladder applied to AttributeType when severity_levels is empty
DEFAULT_SEVERITY_LEVELS = [
    {"code": "none", "name_zh": "无", "color": "#9ca3af"},
    {"code": "light", "name_zh": "轻微", "color": "#facc15"},
    {"code": "medium", "name_zh": "中等", "color": "#fb923c"},
    {"code": "severe", "name_zh": "严重", "color": "#ef4444"},
    {"code": "critical", "name_zh": "危殆", "color": "#7f1d1d"},
]


# ---------------------------------------------------------------------------
# Table 1: AttributeType
# ---------------------------------------------------------------------------

class RoadAttributeType(models.Model):
    """属性类型字典(裂缝/坑槽/标线磨损/护栏损坏/...)."""

    code = models.SlugField(
        max_length=64, unique=True,
        help_text="枚举代码,英文+下划线,例如 crack_longitudinal / pothole / marking_wear"
    )
    name_zh = models.CharField(max_length=120, help_text="中文名(显示用)")
    name_en = models.CharField(max_length=120, blank=True, help_text="英文名(显示用)")

    category = models.CharField(
        max_length=32, choices=ATTRIBUTE_CATEGORY_CHOICES,
        default="surface",
        help_text="属性大类,见 ATTRIBUTE_CATEGORY_CHOICES"
    )
    severity_levels = models.TextField(
        default=json_list_default, blank=True,
        help_text="严重程度等级定义,JSON 列表;为空时用 DEFAULT_SEVERITY_LEVELS"
    )
    unit = models.CharField(
        max_length=20, blank=True,
        help_text="默认计量单位(米/毫米/处/平方米),仅作 UI 提示"
    )
    description = models.TextField(blank=True, help_text="说明/识别方法")
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "road_attributes_type"
        ordering = ["sort_order", "code"]
        verbose_name = "Road Attribute Type"
        verbose_name_plural = "Road Attribute Types"

    def __str__(self):
        return f"{self.name_zh}({self.code})"

    def effective_severity_levels(self):
        return self.severity_levels or DEFAULT_SEVERITY_LEVELS


# ---------------------------------------------------------------------------
# Table 2: Road
# ---------------------------------------------------------------------------

class Road(models.Model):
    """一条道路(物理上连续,可有多段)。"""

    project = models.ForeignKey(
        "app.Project", on_delete=models.CASCADE,
        related_name="road_attributes_roads",
        help_text="归属 WebODM 项目"
    )
    name = models.CharField(max_length=200, help_text="道路名称,如'205 国道 K0-K12 段'")
    code = models.CharField(max_length=50, blank=True, help_text="道路编号(路政/公路编码)")
    road_class = models.CharField(
        max_length=20, choices=ROAD_CLASS_CHOICES, default="other"
    )
    surface_type = models.CharField(
        max_length=20, choices=SURFACE_TYPE_CHOICES, default="asphalt"
    )

    # 路网静态台账
    lanes = models.PositiveIntegerField(default=2, help_text="车道数")
    width_m = models.FloatField(null=True, blank=True, help_text="路宽(米)")
    total_length_m = models.FloatField(null=True, blank=True, help_text="总长(米),由 segments 求和或手填")
    speed_limit_kmh = models.PositiveIntegerField(null=True, blank=True)
    admin_region = models.CharField(max_length=200, blank=True, help_text="所属行政区划")

    # 起终点(便于在没有 GIS 后端时也有路网大致范围)
    start_point = models.TextField(
        default=json_default, blank=True,
        help_text="{lat, lng, label?}"
    )
    end_point = models.TextField(
        default=json_default, blank=True,
        help_text="{lat, lng, label?}"
    )

    # 关联的可选资源
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="road_attributes_roads",
    )
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "road_attributes_road"
        ordering = ["name"]
        verbose_name = "Road"
        verbose_name_plural = "Roads"
        indexes = [
            models.Index(fields=["project", "name"]),
            models.Index(fields=["road_class"]),
        ]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Table 3: RoadSegment
# ---------------------------------------------------------------------------

class RoadSegment(models.Model):
    """一个路段(road 下的有序子段)。"""

    road = models.ForeignKey(
        Road, on_delete=models.CASCADE, related_name="segments"
    )
    seq = models.PositiveIntegerField(help_text="路段在 road 内的顺序号")
    name = models.CharField(max_length=200, blank=True)

    direction = models.CharField(
        max_length=20, choices=DIRECTION_CHOICES, default="bidirectional"
    )
    start_stake = models.CharField(max_length=20, blank=True, help_text="起点桩号,K0+000")
    end_stake = models.CharField(max_length=20, blank=True, help_text="终点桩号")

    start_point = models.TextField(
        default=json_default, blank=True, help_text="{lat, lng, alt?}"
    )
    end_point = models.TextField(
        default=json_default, blank=True, help_text="{lat, lng, alt?}"
    )
    length_m = models.FloatField(help_text="路段长度(米)")
    width_m = models.FloatField(null=True, blank=True, help_text="路段路宽(米),可与 road 不同")
    centerline = models.TextField(
        default=json_list_default, blank=True,
        help_text="中心线经纬度序列 [{lat,lng}, ...],缺省=起终点连线"
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "road_attributes_segment"
        ordering = ["road", "seq"]
        unique_together = [("road", "seq")]
        verbose_name = "Road Segment"
        verbose_name_plural = "Road Segments"
        indexes = [
            models.Index(fields=["road", "seq"]),
        ]

    def __str__(self):
        return f"{self.road.name}#{self.seq}"


# ---------------------------------------------------------------------------
# Table 4: AttributeImage
# ---------------------------------------------------------------------------

class AttributeImage(models.Model):
    """路面属性的照片证据。"""

    image = models.ImageField(
        upload_to="road_attributes/%Y/%m/",
        help_text="属性照片原图"
    )
    thumbnail = models.ImageField(
        upload_to="road_attributes/thumbs/%Y/%m/",
        null=True, blank=True
    )
    captured_at = models.DateTimeField(default=timezone.now)
    position = models.TextField(
        default=json_default, blank=True,
        help_text="{lat, lng, alt?, heading?, gimbal_pitch?}"
    )
    camera_info = models.TextField(
        default=json_default, blank=True,
        help_text="{model, focal_length, iso, shutter, ...}"
    )
    webodm_task = models.ForeignKey(
        "app.Task", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="road_attribute_images",
        help_text="照片所属的 WebODM 3D 任务(可选)"
    )
    notes = models.CharField(max_length=200, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="uploaded_road_attribute_images"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "road_attributes_image"
        ordering = ["-captured_at"]
        verbose_name = "Attribute Image"
        verbose_name_plural = "Attribute Images"

    def __str__(self):
        return f"image#{self.pk} ({self.captured_at:%Y-%m-%d %H:%M})"


# ---------------------------------------------------------------------------
# Table 5: RoadAttribute
# ---------------------------------------------------------------------------

class RoadAttribute(models.Model):
    """一段路上的一个属性记录(单次发现的病害/事件)。"""

    segment = models.ForeignKey(
        RoadSegment, on_delete=models.CASCADE, related_name="attributes"
    )
    attribute_type = models.ForeignKey(
        RoadAttributeType, on_delete=models.PROTECT,
        related_name="instances"
    )
    severity = models.CharField(
        max_length=20, blank=True,
        help_text="严重程度 code;有效值取自 attribute_type.effective_severity_levels()"
    )

    # 定位
    position = models.TextField(
        default=json_default, blank=True,
        help_text="{lat, lng, alt?},在该属性发生位置(可与 segment 起/终点不同)"
    )
    stake = models.CharField(max_length=20, blank=True, help_text="发现处桩号")

    # 度量
    length_m = models.FloatField(null=True, blank=True, help_text="长度(米),如裂缝长")
    width_m = models.FloatField(null=True, blank=True, help_text="宽度(米/毫米单位由 attribute_type.unit 决定)")
    depth_mm = models.FloatField(null=True, blank=True, help_text="深度(毫米)")
    area_m2 = models.FloatField(null=True, blank=True, help_text="面积(平方米)")
    quantity = models.PositiveIntegerField(null=True, blank=True, help_text="数量(条/处)")

    # 状态
    status = models.CharField(
        max_length=20,
        choices=(
            ("open", "待处理"),
            ("in_progress", "处理中"),
            ("repaired", "已修复"),
            ("verified", "已验收"),
            ("ignored", "忽略"),
        ),
        default="open"
    )

    # 上下文
    description = models.TextField(blank=True)
    discovered_at = models.DateTimeField(default=timezone.now)
    inspector = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="road_attributes_inspected"
    )

    # 可选关联
    flight_mission = models.ForeignKey(
        "flight_planner.FlightMission", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="road_attributes",
        help_text="巡检时使用的 flight-planner 任务"
    )
    webodm_task = models.ForeignKey(
        "app.Task", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="road_attributes",
        help_text="WebODM 3D 重建任务(若巡检影像被处理为模型)"
    )

    # 照片(M2M)
    images = models.ManyToManyField(
        AttributeImage, blank=True, related_name="attributes"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "road_attributes_attribute"
        ordering = ["-discovered_at"]
        verbose_name = "Road Attribute"
        verbose_name_plural = "Road Attributes"
        indexes = [
            models.Index(fields=["segment", "attribute_type"]),
            models.Index(fields=["status"]),
            models.Index(fields=["severity"]),
            models.Index(fields=["discovered_at"]),
        ]

    def __str__(self):
        return f"{self.attribute_type.name_zh}@{self.segment} sev={self.severity or '-'}"
