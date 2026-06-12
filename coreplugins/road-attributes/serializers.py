"""
DRF serializers for road-attributes plugin.
"""
import importlib
import json

from django.contrib.auth import get_user_model
from rest_framework import serializers

# Use importlib for dash-name models. See webodm-plugin-development skill
# pitfall on dash-package imports.
_models = importlib.import_module("coreplugins.road-attributes.models")
Road = _models.Road
RoadSegment = _models.RoadSegment
RoadAttribute = _models.RoadAttribute
RoadAttributeType = _models.RoadAttributeType
AttributeImage = _models.AttributeImage


def _loads(v):
    """Decode a JSON-stored TextField. Empty/None becomes a sensible default."""
    if v is None or v == "":
        return None
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return None


class _JSONField(serializers.Field):
    """Read/write a JSON-stored TextField. Pairs with models._JSONTextField."""

    def __init__(self, default_shape=None, **kwargs):
        self._default_shape = default_shape if default_shape is not None else {}
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_null", True)
        super().__init__(**kwargs)

    def to_representation(self, value):
        if value in (None, ""):
            return self._default_shape if isinstance(self._default_shape, (dict, list)) else None
        if isinstance(value, str):
            return _loads(value) or self._default_shape
        return value

    def to_internal_value(self, data):
        if data in (None, ""):
            return json.dumps(self._default_shape, ensure_ascii=False)
        if isinstance(data, str):
            try:
                json.loads(data)
            except (ValueError, TypeError):
                raise serializers.ValidationError("invalid JSON string")
            return data
        return json.dumps(data, ensure_ascii=False)


class _JSONListField(_JSONField):
    def __init__(self, **kwargs):
        kwargs.setdefault("default_shape", [])
        super().__init__(**kwargs)


class RoadAttributeTypeSerializer(serializers.ModelSerializer):
    effective_severity_levels = serializers.SerializerMethodField()
    severity_levels = _JSONListField()

    class Meta:
        model = RoadAttributeType
        fields = [
            "id", "code", "name_zh", "name_en", "category",
            "severity_levels", "effective_severity_levels",
            "unit", "description", "is_active", "sort_order",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_effective_severity_levels(self, obj):
        return obj.effective_severity_levels()


class AttributeImageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    position = _JSONField()
    camera_info = _JSONField()

    class Meta:
        model = AttributeImage
        fields = [
            "id", "image", "image_url", "thumbnail",
            "captured_at", "position", "camera_info",
            "webodm_task", "notes", "uploaded_by",
            "created_at",
        ]
        read_only_fields = ["created_at", "uploaded_by"]

    def get_image_url(self, obj):
        request = self.context.get("request")
        if not obj.image or not request:
            return None
        return request.build_absolute_uri(obj.image.url)


class RoadSegmentSerializer(serializers.ModelSerializer):
    attribute_count = serializers.SerializerMethodField()
    start_point = _JSONField()
    end_point = _JSONField()
    centerline = _JSONListField()

    class Meta:
        model = RoadSegment
        fields = [
            "id", "road", "seq", "name", "direction",
            "start_stake", "end_stake",
            "start_point", "end_point",
            "length_m", "width_m", "centerline",
            "notes", "attribute_count",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_attribute_count(self, obj):
        return obj.attributes.count()


class RoadAttributeSerializer(serializers.ModelSerializer):
    attribute_type_detail = RoadAttributeTypeSerializer(source="attribute_type", read_only=True)
    image_count = serializers.SerializerMethodField()
    images = AttributeImageSerializer(many=True, read_only=True)
    upload_image_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    position = _JSONField()

    class Meta:
        model = RoadAttribute
        fields = [
            "id", "segment", "attribute_type", "attribute_type_detail",
            "severity", "position", "stake",
            "length_m", "width_m", "depth_mm", "area_m2", "quantity",
            "status", "description", "discovered_at",
            "inspector", "flight_mission", "webodm_task",
            "images", "image_count", "upload_image_ids",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "inspector",
                            "attribute_type_detail", "image_count", "images"]

    def get_image_count(self, obj):
        return obj.images.count()

    def create(self, validated_data):
        upload_ids = validated_data.pop("upload_image_ids", [])
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["inspector"] = request.user
        attr = super().create(validated_data)
        if upload_ids:
            attr.images.set(AttributeImage.objects.filter(pk__in=upload_ids))
        return attr

    def update(self, instance, validated_data):
        upload_ids = validated_data.pop("upload_image_ids", None)
        attr = super().update(instance, validated_data)
        if upload_ids is not None:
            attr.images.set(AttributeImage.objects.filter(pk__in=upload_ids))
        return attr


class RoadSerializer(serializers.ModelSerializer):
    segments = RoadSegmentSerializer(many=True, read_only=True)
    segment_count = serializers.SerializerMethodField()
    attribute_count = serializers.SerializerMethodField()
    open_attribute_count = serializers.SerializerMethodField()
    start_point = _JSONField()
    end_point = _JSONField()

    class Meta:
        model = Road
        fields = [
            "id", "project", "name", "code", "road_class", "surface_type",
            "lanes", "width_m", "total_length_m", "speed_limit_kmh",
            "admin_region", "start_point", "end_point",
            "owner", "notes",
            "segment_count", "attribute_count", "open_attribute_count",
            "segments",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "owner",
                            "segment_count", "attribute_count",
                            "open_attribute_count", "segments"]

    def get_segment_count(self, obj):
        return obj.segments.count()

    def get_attribute_count(self, obj):
        return RoadAttribute.objects.filter(segment__road=obj).count()

    def get_open_attribute_count(self, obj):
        return RoadAttribute.objects.filter(segment__road=obj, status="open").count()

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["owner"] = request.user
        return super().create(validated_data)
