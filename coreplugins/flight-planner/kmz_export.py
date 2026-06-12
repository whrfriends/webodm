"""
KMZ (DJI Waypoint Markup Language) export.

Generates a DJI Pilot 2 / FlightHub 2 compatible KMZ file:
  wpmz/template.kml    (mission + waylines, with WPML extensions)
  wpmz/waylines.wpml   (line-segment wayline, for Pilot 2 mapping view)

Output is parameterized by the chosen DJI model AND by user-supplied
mission-level and per-waypoint settings — see drone_models.py.

Namespace: http://www.dji.com/wpmz/1.0.2

This is an open implementation based on the publicly documented WPML
schema (used by DJI Pilot 2 SDK and many third-party waypoint tools).
No proprietary DJI code is reproduced.
"""
from __future__ import annotations

import io
import os
import zipfile
from typing import List, Optional
from xml.sax.saxutils import escape

from .algorithms import Waypoint
from .drone_models import DroneModel, get_model, action_to_actuator


WPML_NS = "http://www.dji.com/wpmz/1.0.2"
KML_NS = "http://www.opengis.net/kml/2.2"


# -----------------------------------------------------------------------------
# Defaults — applied when a key is missing from params
# -----------------------------------------------------------------------------

DEFAULTS = {
    # mission-level
    "fly_to_wayline_mode": "safely",        # safely | directly
    "finish_action": None,                  # -> model.finish_action
    "exit_on_rc_low": None,                 # -> model.rth_on_rc_low
    "exit_on_signal_lost": None,            # -> model.rth_on_signal_lost
    "takeoff_security_height": 20,          # m
    "global_speed": None,                   # m/s; None = omit (use per-waypoint)
    "cali_flight_enable": 0,                # 0|1

    # wayline-level
    "height_mode": "relativeToStartPoint",  # relativeToStartPoint | WGS84 | AGL
    "ellipsoid_height": 0,
    "heading_mode": "auto",                 # auto | fixed | manual
    "gimbal_mode": "useRouteSetting",       # useRouteSetting | manual | fixed
    "auto_flight_speed": 0,                 # 0 = use global

    # user override for the model-decided smooth-curve turn
    "turn_mode_override": None,             # None | "toPoint" | "toPointAndPassWithContinuityCurvature"

    # camera / payload
    "payload_position_index": None,         # None -> model default
    "camera_type_override": None,           # None -> model.camera_type
    "lens_index": None,                     # None | 0=wide, 1=medium tele, 2=tele

    # action group behaviour
    "action_group_mode": "sequence",        # sequence | parallel
    "action_trigger_type": "reachPoint",    # reachPoint | multipleTiming | betweenAdjacentPoints | reachEnd
    "photo_interval": None,                 # seconds — when action_trigger_type=multipleTiming

    # file naming
    "file_suffix_prefix": "WP",             # WP_<idx> | REC_<idx>
    "recording_suffix_prefix": "REC",
}


def _xml_header() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n'


def _kml_open(extra_attrs: str = "") -> str:
    return (
        f'<kml xmlns="{KML_NS}" '
        f'xmlns:wpml="{WPML_NS}"{extra_attrs}>\n'
    )


def _wpml(tag: str, value, indent: str = "    ") -> str:
    """Emit a single <wpml:tag>value</wpml:tag> line."""
    if value is None:
        return ""
    return f'{indent}<wpml:{tag}>{escape(str(value))}</wpml:{tag}>\n'


def _param(params: dict, key: str):
    """Return params[key] if set, else DEFAULTS[key]."""
    if key in params and params[key] is not None:
        return params[key]
    return DEFAULTS.get(key)


def _mission_config(model: DroneModel, params: dict) -> str:
    """<wpml:missionConfig> block at top of template.kml."""
    speed = _param(params, "global_speed")
    if speed is None:
        speed = params.get("speed", 5.0)  # fall back to per-mission default

    parts = [
        "  <wpml:missionConfig>\n",
        _wpml("flyToWaylineMode", _param(params, "fly_to_wayline_mode")),
        _wpml("finishAction",      _param(params, "finish_action")      or model.finish_action),
        _wpml("exitOnRCLow",       _param(params, "exit_on_rc_low")     or model.rth_on_rc_low),
        _wpml("exitOnSignalLost",  _param(params, "exit_on_signal_lost") or model.rth_on_signal_lost),
        _wpml("takeOffSecurityHeight", _param(params, "takeoff_security_height")),
        _wpml("globalSpeed",       speed),
        _wpml("caliFlightEnable",  _param(params, "cali_flight_enable")),
        "  </wpml:missionConfig>\n",
    ]
    return "".join(parts)


def _payload_param(model: DroneModel, params: dict) -> str:
    """<wpml:payloadParam> — camera / gimbal configuration."""
    ppi = _param(params, "payload_position_index")
    if ppi is None:
        ppi = model.payload_position_index
    cam = _param(params, "camera_type_override") or model.camera_type
    if not cam:
        return ""

    out = (
        "  <wpml:payloadParam>\n"
        f'    <wpml:payloadPositionIndex>{ppi}</wpml:payloadPositionIndex>\n'
        f'    <wpml:cameraType>{escape(cam)}</wpml:cameraType>\n'
    )

    # Lens index — only meaningful for multi-lens cameras (Mavic 3 Pro,
    # Mavic 3 Enterprise, M30 series, M300/M350 with H20). Spec says the
    # global lens index is set here for the whole mission.
    lens = _param(params, "lens_index")
    if lens is not None:
        out += f'    <wpml:useGlobalPayloadLensIndex>{int(lens)}</wpml:useGlobalPayloadLensIndex>\n'

    out += "  </wpml:payloadParam>\n"
    return out


def _wayline_coord_sys(model: DroneModel, params: dict) -> str:
    return (
        "    <wpml:waylineCoordinateSysParam>\n"
        "      <wpml:coordinateMode>WGS84</wpml:coordinateMode>\n"
        f"      <wpml:heightMode>{escape(str(_param(params, 'height_mode')))}</wpml:heightMode>\n"
        f"      <wpml:ellipsoidHeight>{_param(params, 'ellipsoid_height')}</wpml:ellipsoidHeight>\n"
        "    </wpml:waylineCoordinateSysParam>\n"
    )


def _gimbal_wayline_params(model: DroneModel, params: dict) -> str:
    out = ""
    out += _wpml("waylineHeadingMode", _param(params, "heading_mode"))
    if model.supports_global_speed and _param(params, "global_speed") is not None:
        out += _wpml("globalSpeed", _param(params, "global_speed"))
    out += _wpml("gimbalMode", _param(params, "gimbal_mode"))
    return out


def _resolve_turn_mode(model: DroneModel, params: dict) -> str:
    """User can override; otherwise honour the model flag."""
    override = _param(params, "turn_mode_override")
    if override:
        return override
    return ("toPointAndPassWithContinuityCurvature"
            if model.supports_curve else "toPoint")


def _placemark(wp: Waypoint, model: DroneModel, params: dict, is_last: bool) -> str:
    """Render one <Placemark> for a waypoint."""
    act = action_to_actuator(wp.action, model)
    action_xml = _action_group(wp, act, model, params) if act else ""

    hyper_xml = ""
    if model.supports_hyper:
        hyper_xml = (
            f"      <wpml:hyperlateral>{1 if getattr(wp, 'hyperlateral', 0) else 0}</wpml:hyperlateral>\n"
            f"      <wpml:hypervertical>{1 if getattr(wp, 'hypervertical', 0) else 0}</wpml:hypervertical>\n"
        )

    turn_mode = _resolve_turn_mode(model, params)

    # Per-waypoint values (fall back to mission defaults)
    gimbal = wp.gimbal_pitch if wp.gimbal_pitch is not None else params.get("gimbal_pitch", -90)
    speed = wp.speed if wp.speed else params.get("speed", 5.0)
    heading_mode = getattr(wp, "heading_mode", None) or _param(params, "heading_mode")
    heading_angle = wp.heading if wp.heading is not None else 0
    heading_enable = 1 if (wp.heading is not None and heading_mode == "fixed") else 0

    ppi = _param(params, "payload_position_index")
    if ppi is None:
        ppi = model.payload_position_index

    return (
        "    <Placemark>\n"
        f"      <wpml:index>{wp.index}</wpml:index>\n"
        f"      <wpml:executeHeight>{wp.alt:.2f}</wpml:executeHeight>\n"
        f"      <wpml:waypointSpeed>{speed:.2f}</wpml:waypointSpeed>\n"
        f"      <wpml:waypointHeadingMode>{heading_mode}</wpml:waypointHeadingMode>\n"
        f"      <wpml:waypointHeadingAngle>{int(heading_angle)}</wpml:waypointHeadingAngle>\n"
        f"      <wpml:waypointHeadingAngleEnable>{heading_enable}</wpml:waypointHeadingAngleEnable>\n"
        f"      <wpml:waypointTurnMode>{turn_mode}</wpml:waypointTurnMode>\n"
        f"      <wpml:waypointGimbalHeadingAngleEnable>0</wpml:waypointGimbalHeadingAngleEnable>\n"
        f"      <wpml:waypointGimbalPitchAngle>{int(gimbal)}</wpml:waypointGimbalPitchAngle>\n"
        f"      <wpml:gimbalRotateTimeInterval>0</wpml:gimbalRotateTimeInterval>\n"
        f"      <wpml:payloadPositionIndex>{ppi}</wpml:payloadPositionIndex>\n"
        + hyper_xml
        + action_xml +
        f"      <Point>\n"
        f"        <coordinates>{wp.lon:.7f},{wp.lat:.7f},0</coordinates>\n"
        f"      </Point>\n"
        "    </Placemark>\n"
    )


# -----------------------------------------------------------------------------
# Action groups
# -----------------------------------------------------------------------------

def _hover_param_xml(hover_time: float) -> str:
    if hover_time and hover_time > 0:
        return f"        <wpml:hoverTime>{hover_time:.1f}</wpml:hoverTime>\n"
    return ""


def _rotate_yaw_param_xml(target_angle: int) -> str:
    # rotateYaw needs target angle in actionActuatorFuncParam
    return f"        <wpml:rotateAngle>{int(target_angle)}</wpml:rotateAngle>\n"


def _gimbal_param_xml(pitch_angle: int, duration: int) -> str:
    return (
        f"        <wpml:gimbalPitchAngle>{int(pitch_angle)}</wpml:gimbalPitchAngle>\n"
        f"        <wpml:rotateTime>{int(duration)}</wpml:rotateTime>\n"
    )


def _zoom_param_xml(focal_length: float) -> str:
    # zoom uses focal length in mm
    return f"        <wpml:focalLength>{focal_length:.1f}</wpml:focalLength>\n"


def _focus_param_xml(focus_x: float, focus_y: float) -> str:
    return (
        f"        <wpml:focusX>{focus_x:.2f}</wpml:focusX>\n"
        f"        <wpml:focusY>{focus_y:.2f}</wpml:focusY>\n"
    )


def _action_func_param(wp: Waypoint, actuator: str, model: DroneModel, params: dict) -> str:
    """Build the <wpml:actionActuatorFuncParam> block for the chosen actuator."""
    ppi = _param(params, "payload_position_index")
    if ppi is None:
        ppi = model.payload_position_index

    prefix = _param(params, "file_suffix_prefix") if actuator in ("takePhoto",) else \
             _param(params, "recording_suffix_prefix") if actuator in ("startRecord",) else \
             "WP"

    if actuator == "takePhoto":
        suffix = f"{prefix}_{wp.index:03d}"
        return (
            f"        <wpml:payloadPositionIndex>{ppi}</wpml:payloadPositionIndex>\n"
            f"        <wpml:fileSuffix>{escape(suffix)}</wpml:fileSuffix>\n"
            "        <wpml:useGlobalPayloadLensIndex>0</wpml:useGlobalPayloadLensIndex>\n"
        )
    elif actuator == "startRecord":
        suffix = f"{prefix}_{wp.index:03d}"
        return (
            f"        <wpml:payloadPositionIndex>{ppi}</wpml:payloadPositionIndex>\n"
            f"        <wpml:fileSuffix>{escape(suffix)}</wpml:fileSuffix>\n"
        )
    elif actuator == "stopRecord":
        return (
            f"        <wpml:payloadPositionIndex>{ppi}</wpml:payloadPositionIndex>\n"
        )
    elif actuator == "hover":
        return _hover_param_xml(getattr(wp, "hold_time", 0.0))
    elif actuator == "rotateYaw":
        return _rotate_yaw_param_xml(getattr(wp, "heading", 0) or 0)
    elif actuator == "gimbalRotate":
        pitch = getattr(wp, "action_pitch", None)
        if pitch is None:
            pitch = wp.gimbal_pitch if wp.gimbal_pitch is not None else -90
        return _gimbal_param_xml(pitch, getattr(wp, "rotate_time", 2))
    elif actuator == "zoom":
        fl = getattr(wp, "focal_length", 24.0)
        return _zoom_param_xml(fl)
    elif actuator == "focusCamera":
        return _focus_param_xml(getattr(wp, "focus_x", 0.5), getattr(wp, "focus_y", 0.5))
    return f"        <wpml:payloadPositionIndex>{ppi}</wpml:payloadPositionIndex>\n"


def _action_group(wp: Waypoint, actuator: str, model: DroneModel, params: dict) -> str:
    """<wpml:actionGroup> block — bound to a single waypoint's index range."""
    trigger = _param(params, "action_trigger_type")
    group_mode = _param(params, "action_group_mode")

    # For 'multipleTiming' trigger, interval is required; we tag it via
    # the actionGroupStartIndex/EndIndex window and inject photoInterval
    # as a sibling to the actionTrigger in extended scenarios. For the
    # simple reachPoint case, we leave the standard structure.
    trigger_xml = (
        "        <wpml:actionTrigger>\n"
        f"          <wpml:actionTriggerType>{trigger}</wpml:actionTriggerType>\n"
    )
    if trigger == "multipleTiming":
        interval = _param(params, "photo_interval")
        if interval:
            trigger_xml += f"          <wpml:actionInterval>{int(interval)}</wpml:actionInterval>\n"
    trigger_xml += "        </wpml:actionTrigger>\n"

    func_param = _action_func_param(wp, actuator, model, params)

    return (
        "      <wpml:actionGroup>\n"
        f"        <wpml:actionGroupId>{wp.index}</wpml:actionGroupId>\n"
        f"        <wpml:actionGroupStartIndex>{wp.index}</wpml:actionGroupStartIndex>\n"
        f"        <wpml:actionGroupEndIndex>{wp.index}</wpml:actionGroupEndIndex>\n"
        f"        <wpml:actionGroupMode>{group_mode}</wpml:actionGroupMode>\n"
        + trigger_xml +
        "        <wpml:action>\n"
        f"          <wpml:actionId>{wp.index}</wpml:actionId>\n"
        f"          <wpml:actionActuatorFunc>{actuator}</wpml:actionActuatorFunc>\n"
        "          <wpml:actionActuatorFuncParam>\n"
        + func_param +
        "          </wpml:actionActuatorFuncParam>\n"
        "        </wpml:action>\n"
        "      </wpml:actionGroup>\n"
    )


# -----------------------------------------------------------------------------
# Top-level builders
# -----------------------------------------------------------------------------

def build_template_kml(waypoints: List[Waypoint], model: DroneModel, params: dict) -> str:
    """Return the template.kml string for a mission."""
    if not waypoints:
        return _xml_header() + _kml_open() + "  <Document></Document></kml>"

    out = _xml_header() + _kml_open() + "<Document>\n"
    out += _mission_config(model, params)
    out += _payload_param(model, params)
    out += "  <Folder>\n"
    out += f"    <wpml:templateType>waypoint</wpml:templateType>\n"
    out += f"    <wpml:useModel>{escape(model.model_id)}</wpml:useModel>\n"
    out += _wayline_coord_sys(model, params)
    out += _gimbal_wayline_params(model, params)
    out += f"    <wpml:autoFlightSpeed>{_param(params, 'auto_flight_speed')}</wpml:autoFlightSpeed>\n"

    n = len(waypoints)
    for i, wp in enumerate(waypoints):
        out += _placemark(wp, model, params, is_last=(i == n - 1))

    out += "  </Folder>\n"
    out += "</Document>\n</kml>\n"
    return out


def build_waylines_wpml(waypoints: List[Waypoint], model: DroneModel, params: dict) -> str:
    """Return the waylines.wpml string (segment-by-segment for Pilot 2 map view)."""
    out = _xml_header() + _kml_open() + "<Document>\n"
    out += "  <Folder>\n"
    out += f"    <wpml:templateId>0</wpml:templateId>\n"
    out += f"    <wpml:useModel>{escape(model.model_id)}</wpml:useModel>\n"

    # Emit one Placemark per consecutive segment, with start / end coordinates.
    for i in range(len(waypoints) - 1):
        a = waypoints[i]
        b = waypoints[i + 1]
        height = (a.alt + b.alt) / 2
        out += (
            "    <Placemark>\n"
            f"      <wpml:index>{i}</wpml:index>\n"
            f"      <wpml:executeHeight>{height:.2f}</wpml:executeHeight>\n"
            f"      <wpml:waypointSpeed>{a.speed:.2f}</wpml:waypointSpeed>\n"
            "      <LineString>\n"
            "        <coordinates>\n"
            f"          {a.lon:.7f},{a.lat:.7f},{a.alt:.2f}\n"
            f"          {b.lon:.7f},{b.lat:.7f},{b.alt:.2f}\n"
            "        </coordinates>\n"
            "      </LineString>\n"
            "    </Placemark>\n"
        )
    out += "  </Folder>\n"
    out += "</Document>\n</kml>\n"
    return out


def mission_to_kmz(
    waypoints: List[Waypoint],
    project_name: str,
    model_id: str,
    params: dict,
) -> bytes:
    """Build a KMZ (zip) file in memory. Returns the bytes.

    The structure is:
      wpmz/template.kml
      wpmz/waylines.wpml
    """
    model = get_model(model_id)
    if not model:
        raise ValueError(f"Unknown drone model: {model_id}")

    template = build_template_kml(waypoints, model, params)
    waylines = build_waylines_wpml(waypoints, model, params)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("wpmz/template.kml", template)
        zf.writestr("wpmz/waylines.wpml", waylines)
    return buf.getvalue()
