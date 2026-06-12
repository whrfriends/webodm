"""
DJI drone model registry for KMZ export.

Each model declares the parameters that affect WPML/KMZ output:
  - WPML <wpml:useModel> identifier (DJI's machine name for the aircraft)
  - <wpml:cameraType> identifier (for <wpml:payloadParam>)
  - max / min flight speed, altitude, distance
  - supported gimbal modes, action types, RTH behaviors
  - whether hyperlateral / hypervertical are honored
  - max photo / video triggers per action group

All values are from publicly available DJI specifications and WPML
documentation. No proprietary code is reproduced; we generate standard
KML 2.2 + the documented DJI WPML extension namespace.

Namespace: http://www.dji.com/wpmz/1.0.2  (DJI Pilot 2 / FlightHub 2)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional


@dataclass
class DroneModel:
    """Specification of one DJI aircraft that supports waypoint missions."""
    model_id: str               # machine id used in <wpml:useModel>
    display_name: str           # human-readable name for UI
    category: str               # consumer | enterprise | fpv
    series: str                 # mavic | phantom | inspire | mini | air | matrice | fpv | avata

    # Flight envelope
    max_speed: float            # m/s
    min_speed: float            # m/s (some aircraft enforce a min waypoint speed)
    max_altitude: float         # m above takeoff
    min_altitude: float         # m above takeoff
    max_flight_distance: float  # m from home (one-way)
    max_flight_time: int        # minutes (informational)

    # Gimbal
    gimbal_modes: List[str] = field(default_factory=lambda: ["useRouteSetting"])
    # ^ values: useRouteSetting, manual, fixed

    # Actions
    supported_actions: List[str] = field(default_factory=lambda: [
        "takePhoto", "startRecord", "stopRecord", "hover"
    ])
    # ^ takePhoto | startRecord | stopRecord | focusCamera | zoom | rotateYaw | hover | gimbalRotate

    # Waypoint heading
    heading_modes: List[str] = field(default_factory=lambda: ["auto", "fixed", "manual"])

    # Camera / payload
    camera_type: str = ""       # identifier for <wpml:cameraType>
    payload_position_index: int = 0

    # Feature flags
    supports_hyper: bool = True    # <wpml:hyperlateral> / <wpml:hypervertical> respected
    supports_overlap: bool = True  # <wpml:overlap> tag respected
    supports_pano: bool = False
    supports_curve: bool = True    # <wpml:waypointTurnMode> = "toPointAndPassWithContinuityCurvature"
    supports_global_speed: bool = True  # <wpml:globalSpeed> at missionConfig level

    # RTH
    rth_on_rc_low: str = "goHome"        # goHome | land | hover
    rth_on_signal_lost: str = "goHome"   # goHome | land | hover | continue
    finish_action: str = "goHome"        # goHome | land | hover | backToFirst

    # Notes (shown in UI)
    notes: str = ""


# -----------------------------------------------------------------------------
# Model database
# -----------------------------------------------------------------------------

DRONE_MODELS: Dict[str, DroneModel] = {}


def _register(m: DroneModel) -> None:
    DRONE_MODELS[m.model_id] = m


# ---- Mavic 3 series ----
_register(DroneModel(
    model_id="M3E",  # Mavic 3 Enterprise
    display_name="DJI Mavic 3 Enterprise (M3E)",
    category="enterprise", series="mavic",
    max_speed=21, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=15000, max_flight_time=45,
    camera_type="M3E_CAM", payload_position_index=0,
    gimbal_modes=["useRouteSetting", "manual"],
    supported_actions=["takePhoto", "startRecord", "stopRecord", "hover", "rotateYaw", "gimbalRotate"],
    supports_hyper=True, supports_pano=False,
    rth_on_rc_low="goHome", rth_on_signal_lost="goHome", finish_action="goHome",
    notes="支持变焦 / 测光矩阵；M3E 与 M3T 共享机身，相机型号 M3E_CAM",
))

_register(DroneModel(
    model_id="M3T",
    display_name="DJI Mavic 3 Thermal (M3T)",
    category="enterprise", series="mavic",
    max_speed=21, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=15000, max_flight_time=45,
    camera_type="M3T_CAM", payload_position_index=0,
    gimbal_modes=["useRouteSetting", "manual"],
    supported_actions=["takePhoto", "startRecord", "stopRecord", "hover", "rotateYaw", "gimbalRotate"],
    supports_hyper=True,
    notes="含热成像通道；可见光 + 红外双负载",
))

_register(DroneModel(
    model_id="MAVIC_3",
    display_name="DJI Mavic 3",
    category="consumer", series="mavic",
    max_speed=21, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=15000, max_flight_time=46,
    camera_type="MAVIC_3_CAM",
    supports_hyper=True,
    notes="4/3 CMOS 哈苏相机",
))

_register(DroneModel(
    model_id="MAVIC_3_PRO",
    display_name="DJI Mavic 3 Pro",
    category="consumer", series="mavic",
    max_speed=21, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=15000, max_flight_time=43,
    camera_type="MAVIC_3_PRO_CAM",
    supports_hyper=True,
    notes="三摄系统 (哈苏主摄 + 中长焦 + 长焦)",
))

_register(DroneModel(
    model_id="MAVIC_3_CLASSIC",
    display_name="DJI Mavic 3 Classic",
    category="consumer", series="mavic",
    max_speed=21, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=15000, max_flight_time=46,
    camera_type="MAVIC_3_CAM",
    supports_hyper=True,
    notes="单 4/3 CMOS 哈苏相机",
))

# ---- Air 2 / Air 2S / Air 3 ----
_register(DroneModel(
    model_id="AIR_2S",
    display_name="DJI Air 2S",
    category="consumer", series="air",
    max_speed=19, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=12000, max_flight_time=31,
    camera_type="AIR_2S_CAM",
    supports_hyper=True,
    notes="1 英寸 CMOS；不支持 hyperlateral/hypervertical 实测受限",
))

_register(DroneModel(
    model_id="AIR_3",
    display_name="DJI Air 3",
    category="consumer", series="air",
    max_speed=21, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=12000, max_flight_time=46,
    camera_type="AIR_3_CAM",
    supports_hyper=True,
    notes="双主摄 (广角 + 中长焦)",
))

# ---- Mini series ----
_register(DroneModel(
    model_id="MINI_3",
    display_name="DJI Mini 3",
    category="consumer", series="mini",
    max_speed=16, min_speed=1, max_altitude=400, min_altitude=2,
    max_flight_distance=10000, max_flight_time=38,
    camera_type="MINI_3_CAM",
    supports_hyper=False,  # Mini 系列不支持超采样拍照模式
    supports_pano=True,
    notes="≤249g；不支持 hyperlateral/hypervertical",
))

_register(DroneModel(
    model_id="MINI_3_PRO",
    display_name="DJI Mini 3 Pro",
    category="consumer", series="mini",
    max_speed=16, min_speed=1, max_altitude=400, min_altitude=2,
    max_flight_distance=10000, max_flight_time=34,
    camera_type="MINI_3_PRO_CAM",
    supports_hyper=False, supports_pano=True,
    notes="≤249g；Mini 系列无超采样",
))

_register(DroneModel(
    model_id="MINI_4_PRO",
    display_name="DJI Mini 4 Pro",
    category="consumer", series="mini",
    max_speed=16, min_speed=1, max_altitude=400, min_altitude=2,
    max_flight_distance=10000, max_flight_time=34,
    camera_type="MINI_4_PRO_CAM",
    supports_hyper=False, supports_pano=True,
    notes="≤249g；全向避障",
))

# ---- Phantom 4 ----
_register(DroneModel(
    model_id="PHANTOM_4",
    display_name="DJI Phantom 4",
    category="consumer", series="phantom",
    max_speed=20, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=5000, max_flight_time=28,
    camera_type="PHANTOM_4_CAM",
    supports_hyper=False,
    notes="旧机型；仅支持 waypoint 基本动作",
))

_register(DroneModel(
    model_id="PHANTOM_4_PRO",
    display_name="DJI Phantom 4 Pro V2.0",
    category="consumer", series="phantom",
    max_speed=20, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=5000, max_flight_time=30,
    camera_type="PHANTOM_4_PRO_CAM",
    supports_hyper=False,
    notes="1 英寸 20MP CMOS；机械快门",
))

# ---- Inspire 2 ----
_register(DroneModel(
    model_id="INSPIRE_2",
    display_name="DJI Inspire 2",
    category="professional", series="inspire",
    max_speed=26, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=7000, max_flight_time=27,
    camera_type="X7_CAM",  # or X5S, X4S - user must select
    supports_hyper=True,
    notes="可换相机 (X4S/X5S/X7)；camera_type 需根据挂载相机调整",
))

# ---- Matrice series (Enterprise) ----
_register(DroneModel(
    model_id="M30",
    display_name="DJI Matrice 30 (M30)",
    category="enterprise", series="matrice",
    max_speed=23, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=15000, max_flight_time=41,
    camera_type="M30_CAM", payload_position_index=0,
    gimbal_modes=["useRouteSetting", "manual"],
    supported_actions=["takePhoto", "startRecord", "stopRecord", "hover", "rotateYaw", "gimbalRotate", "zoom"],
    supports_hyper=True,
    rth_on_rc_low="goHome", rth_on_signal_lost="goHome",
    notes="支持 8K 变焦；企业级冗余",
))

_register(DroneModel(
    model_id="M30T",
    display_name="DJI Matrice 30T (M30T)",
    category="enterprise", series="matrice",
    max_speed=23, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=15000, max_flight_time=41,
    camera_type="M30T_CAM", payload_position_index=0,
    supported_actions=["takePhoto", "startRecord", "stopRecord", "hover", "rotateYaw", "gimbalRotate", "zoom"],
    supports_hyper=True,
    notes="可见光 + 红外热成像 + 测距",
))

_register(DroneModel(
    model_id="M300",
    display_name="DJI Matrice 300 RTK (M300)",
    category="enterprise", series="matrice",
    max_speed=23, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=15000, max_flight_time=55,
    camera_type="H20_CAM",  # H20 / H20T / Z30 / XT2 / P1 / L1 可选
    payload_position_index=1,  # M300 常用 P1/L1 在挂载 1
    gimbal_modes=["useRouteSetting", "manual"],
    supported_actions=["takePhoto", "startRecord", "stopRecord", "hover", "rotateYaw", "gimbalRotate", "zoom", "focusCamera"],
    supports_hyper=True, supports_pano=True,
    notes="支持 H20/H20T/Z30/XT2/P1/L1 多种负载；camera_type 需根据挂载调整",
))

_register(DroneModel(
    model_id="M350",
    display_name="DJI Matrice 350 RTK (M350)",
    category="enterprise", series="matrice",
    max_speed=23, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=15000, max_flight_time=55,
    camera_type="H20_CAM", payload_position_index=1,
    gimbal_modes=["useRouteSetting", "manual"],
    supported_actions=["takePhoto", "startRecord", "stopRecord", "hover", "rotateYaw", "gimbalRotate", "zoom", "focusCamera"],
    supports_hyper=True, supports_pano=True,
    notes="M300 升级版；支持 H20/H20T/L2/P1 等负载",
))

# ---- FPV / Avata ----
_register(DroneModel(
    model_id="AVATA_2",
    display_name="DJI Avata 2",
    category="fpv", series="avata",
    max_speed=27, min_speed=1, max_altitude=500, min_altitude=2,
    max_flight_distance=5000, max_flight_time=23,
    camera_type="AVATA_2_CAM",
    supports_hyper=False, supports_curve=False,
    supported_actions=["takePhoto", "startRecord", "stopRecord", "hover"],
    notes="FPV 穿越机；不支持平滑转弯，建议将转弯模式设为 toPoint",
))

# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def list_models() -> List[dict]:
    """Return all models as a list of public dicts (for API responses)."""
    out = []
    for m in DRONE_MODELS.values():
        out.append({
            "model_id": m.model_id,
            "display_name": m.display_name,
            "category": m.category,
            "series": m.series,
            "max_speed": m.max_speed,
            "min_speed": m.min_speed,
            "max_altitude": m.max_altitude,
            "min_altitude": m.min_altitude,
            "max_flight_distance": m.max_flight_distance,
            "max_flight_time": m.max_flight_time,
            "camera_type": m.camera_type,
            "supports_hyper": m.supports_hyper,
            "supports_overlap": m.supports_overlap,
            "supports_pano": m.supports_pano,
            "supports_curve": m.supports_curve,
            "gimbal_modes": list(m.gimbal_modes),
            "supported_actions": list(m.supported_actions),
            "heading_modes": list(m.heading_modes),
            "rth_on_rc_low": m.rth_on_rc_low,
            "rth_on_signal_lost": m.rth_on_signal_lost,
            "finish_action": m.finish_action,
            "notes": m.notes,
        })
    out.sort(key=lambda x: (x["category"], x["display_name"]))
    return out


def get_model(model_id: str) -> Optional[DroneModel]:
    return DRONE_MODELS.get(model_id)


def model_summary(m: DroneModel) -> dict:
    """Concise summary for the UI tooltip."""
    return {
        "model_id": m.model_id,
        "display_name": m.display_name,
        "speed_range_m_s": [m.min_speed, m.max_speed],
        "altitude_range_m": [m.min_altitude, m.max_altitude],
        "max_flight_distance_m": m.max_flight_distance,
        "max_flight_time_min": m.max_flight_time,
        "camera_type": m.camera_type,
        "gimbal_modes": m.gimbal_modes,
        "supported_actions": m.supported_actions,
        "supports_hyper": m.supports_hyper,
        "supports_overlap": m.supports_overlap,
        "supports_pano": m.supports_pano,
        "supports_curve": m.supports_curve,
        "notes": m.notes,
    }


def validate_params_for_model(model_id: str, params: dict) -> dict:
    """Return a {field: error_message} dict (empty if all OK)."""
    errs = {}
    m = get_model(model_id)
    if not m:
        return {"_general": f"Unknown model: {model_id}"}

    spd = params.get("speed")
    if spd is not None and (spd < m.min_speed or spd > m.max_speed):
        errs["speed"] = f"超出 {m.display_name} 速度范围 ({m.min_speed}–{m.max_speed} m/s)"

    alt = params.get("altitude")
    if alt is not None and (alt < m.min_altitude or alt > m.max_altitude):
        errs["altitude"] = f"超出 {m.display_name} 高度范围 ({m.min_altitude}–{m.max_altitude} m)"

    gimbal = params.get("gimbal_pitch")
    if gimbal is not None and (gimbal < -90 or gimbal > 30):
        errs["gimbal_pitch"] = "云台俯仰角应在 -90° ~ 30° 之间"

    if not m.supports_curve and params.get("curve_radius", 0) > 0:
        errs["curve_radius"] = f"{m.display_name} 不支持平滑转弯"

    return errs


def action_to_actuator(action: str, model: DroneModel) -> Optional[str]:
    """Map our action vocabulary to DJI WPML actionActuatorFunc, or None if
    the model doesn't support it."""
    # Map our internal action names → DJI actuator function names
    actuator_map = {
        "none": None,
        "photo": "takePhoto",
        "video_start": "startRecord",
        "video_stop": "stopRecord",
        "hover": "hover",
        "rotate_yaw": "rotateYaw",
        "gimbal_rotate": "gimbalRotate",
        "zoom": "zoom",
        "focus": "focusCamera",
    }
    actuator = actuator_map.get(action)
    if actuator is None:
        return None
    if actuator not in model.supported_actions:
        return None
    return actuator
