from django.apps import AppConfig


class RoadAttributesConfig(AppConfig):
    name = "coreplugins.road-attributes"
    label = "road_attributes"  # underscore form, used for DB table prefix
    verbose_name = "Road Attributes (路面巡检属性)"
