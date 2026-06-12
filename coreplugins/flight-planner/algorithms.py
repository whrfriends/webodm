"""
Mission planning algorithms - open source implementation.

All algorithms work in WGS84 lat/lon coordinates and produce waypoint lists
ready for KML export. NO DJI proprietary schema.

Algorithms:
- polygon_survey(): boustrophedon (lawnmower) coverage of an arbitrary polygon
- spiral(): Archimedean / logarithmic spiral from a center
- orbit(): N-point circle around a point of interest
- cable_cam(): evenly spaced waypoints along a polyline
- corkscrew(): helical climb along a centerline
- panel_grid(): 2D grid (rectangle) survey
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import List, Tuple, Optional


EARTH_R = 6_378_137.0  # WGS84 equatorial radius (meters)


def meters_per_degree_lat() -> float:
    return math.pi * EARTH_R / 180.0


def meters_per_degree_lon(lat_deg: float) -> float:
    return math.pi * EARTH_R * math.cos(math.radians(lat_deg)) / 180.0


@dataclass
class Waypoint:
    """A single waypoint in the mission.

    The default `action` value is "photo" (per-mission default action);
    per-waypoint overrides are common — pass `action="none"` to suppress
    the photo trigger at a specific point.
    """

    index: int
    lat: float
    lon: float
    alt: float  # meters above takeoff
    speed: float = 5.0  # m/s
    gimbal_pitch: int = -90  # degrees, -90 = straight down
    heading: Optional[int] = None  # degrees true north, None = auto
    heading_mode: Optional[str] = None  # None | auto | fixed | manual
    action: str = "photo"  # none | photo | video_start | video_stop | hover |
                         # gimbal_rotate | rotate_yaw | zoom | focus
    curve_radius: float = 0.0  # 0 = sharp turn, >0 = smooth corner
    hold_time: float = 0.0  # seconds (used by hover action)

    # Action-specific parameters
    action_pitch: Optional[int] = None    # target pitch for gimbal_rotate
    rotate_time: int = 2                  # seconds for gimbal_rotate animation
    focal_length: float = 24.0            # mm for zoom action
    focus_x: float = 0.5                  # 0-1 normalized for focus action
    focus_y: float = 0.5                  # 0-1 normalized for focus action

    # Hyper sampling
    hyperlateral: int = 0  # 0|1 (model must support_hyper)
    hypervertical: int = 0  # 0|1

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Polygon (lawnmower) survey
# ---------------------------------------------------------------------------

def polygon_survey(
    polygon_coords: List[Tuple[float, float]],
    altitude: float = 50.0,
    speed: float = 5.0,
    line_spacing: float = 30.0,
    angle_deg: float = 0.0,
    overlap: float = 0.7,
    gimbal_pitch: int = -90,
    action: str = "photo",
    start_at: str = "auto",
    margin: float = 0.0,
) -> List[Waypoint]:
    """Boustrophedon coverage of an arbitrary polygon (lat/lon vertices)."""
    from shapely.geometry import Polygon, LineString

    if len(polygon_coords) < 3:
        raise ValueError("Polygon needs at least 3 vertices")
    if abs(line_spacing) < 0.5:
        raise ValueError("line_spacing too small (< 0.5m)")

    c_lat = sum(p[0] for p in polygon_coords) / len(polygon_coords)
    c_lon = sum(p[1] for p in polygon_coords) / len(polygon_coords)
    m_per_lat = meters_per_degree_lat()
    m_per_lon = meters_per_degree_lon(c_lat)

    def to_local(coord):
        lat, lon = coord
        return ((lat - c_lat) * m_per_lat, (lon - c_lon) * m_per_lon)

    def to_geo(x, y):
        return (c_lat + x / m_per_lat, c_lon + y / m_per_lon)

    local_coords = [to_local(c) for c in polygon_coords]
    if local_coords[0] != local_coords[-1]:
        local_coords.append(local_coords[0])
    poly = Polygon(local_coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if margin > 0:
        poly = poly.buffer(-margin)
    if poly.is_empty or poly.area <= 0:
        raise ValueError("Polygon empty after margin/buffer")

    theta = math.radians(angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    def rotate(x, y):
        return (x * cos_t + y * sin_t, -x * sin_t + y * cos_t)

    def rotate_back(x, y):
        return (x * cos_t - y * sin_t, x * sin_t + y * cos_t)

    rotated = [rotate(x, y) for x, y in poly.exterior.coords]
    rotated_poly = Polygon(rotated)
    if not rotated_poly.is_valid:
        rotated_poly = rotated_poly.buffer(0)
    minx, miny, maxx, maxy = rotated_poly.bounds

    lines: List[LineString] = []
    x = minx
    while x <= maxx:
        line = LineString([(x, miny - 1), (x, maxy + 1)])
        clipped = line.intersection(rotated_poly)
        if not clipped.is_empty:
            if clipped.geom_type == "LineString":
                lines.append(clipped)
            elif clipped.geom_type == "MultiLineString":
                for ls in clipped.geoms:
                    lines.append(ls)
        x += line_spacing

    if not lines:
        raise ValueError("No flight lines generated inside polygon (check spacing vs polygon size)")

    lines.sort(key=lambda ln: ln.coords[0][1])
    ordered: List[LineString] = []
    for i, ln in enumerate(lines):
        if i % 2 == 1:
            coords = list(ln.coords)
            coords.reverse()
            ordered.append(LineString(coords))
        else:
            ordered.append(ln)

    waypoints: List[Waypoint] = []
    wp_idx = 0
    for ln in ordered:
        for x, y in ln.coords:
            rx, ry = rotate_back(x, y)
            lat, lon = to_geo(rx, ry)
            waypoints.append(
                Waypoint(
                    index=wp_idx,
                    lat=lat,
                    lon=lon,
                    alt=altitude,
                    speed=speed,
                    gimbal_pitch=gimbal_pitch,
                    heading=None,
                    action=action if wp_idx == 0 else "none",
                )
            )
            wp_idx += 1

    return waypoints


# ---------------------------------------------------------------------------
# Spiral
# ---------------------------------------------------------------------------

def spiral(
    center_lat: float,
    center_lon: float,
    start_radius: float = 10.0,
    end_radius: float = 100.0,
    turns: float = 5.0,
    start_alt: float = 30.0,
    end_alt: float = 80.0,
    speed: float = 4.0,
    gimbal_pitch: int = -90,
    points_per_turn: int = 36,
    inward: bool = False,
    heading_mode: str = "auto",
) -> List[Waypoint]:
    """Archimedean spiral with linear altitude ramp."""
    if start_radius < 0 or end_radius < 0:
        raise ValueError("radius must be positive")
    if points_per_turn < 6:
        raise ValueError("points_per_turn too small")

    m_per_lat = meters_per_degree_lat()
    m_per_lon = meters_per_degree_lon(center_lat)
    total_theta = 2.0 * math.pi * turns
    total_points = max(8, int(points_per_turn * turns))
    sign = -1.0 if inward else 1.0
    d_radius = (end_radius - start_radius) / max(1, total_points - 1)
    d_alt = (end_alt - start_alt) / max(1, total_points - 1)

    waypoints: List[Waypoint] = []
    for i in range(total_points):
        theta = sign * (total_theta * i / max(1, total_points - 1))
        r = start_radius + d_radius * i
        x = r * math.cos(theta)
        y = r * math.sin(theta)
        lat = center_lat + x / m_per_lat
        lon = center_lon + y / m_per_lon
        alt = start_alt + d_alt * i
        heading = None
        if heading_mode == "center":
            heading = (math.degrees(math.atan2(x, y)) + 360) % 360
        elif heading_mode == "tangent":
            heading = (math.degrees(theta) + 90) % 360
        waypoints.append(
            Waypoint(
                index=i,
                lat=lat,
                lon=lon,
                alt=alt,
                speed=speed,
                gimbal_pitch=gimbal_pitch,
                heading=int(heading) if heading is not None else None,
                action="none",
            )
        )
    return waypoints


# ---------------------------------------------------------------------------
# Orbit (POI circle)
# ---------------------------------------------------------------------------

def orbit(
    center_lat: float,
    center_lon: float,
    radius: float = 50.0,
    altitude: float = 40.0,
    speed: float = 3.0,
    points: int = 24,
    gimbal_pitch: int = -30,
    clockwise: bool = True,
    start_angle_deg: float = 0.0,
    center_lookat: bool = True,
) -> List[Waypoint]:
    """Circle around a point of interest."""
    if points < 3:
        raise ValueError("orbit points >= 3")
    m_per_lat = meters_per_degree_lat()
    m_per_lon = meters_per_degree_lon(center_lat)
    sign = -1.0 if clockwise else 1.0
    waypoints: List[Waypoint] = []
    for i in range(points):
        theta = math.radians(start_angle_deg) + sign * 2 * math.pi * i / points
        x = radius * math.cos(theta)
        y = radius * math.sin(theta)
        lat = center_lat + x / m_per_lat
        lon = center_lon + y / m_per_lon
        heading = None
        if center_lookat:
            heading = int((math.degrees(math.atan2(x, y)) + 360) % 360)
        waypoints.append(
            Waypoint(
                index=i,
                lat=lat,
                lon=lon,
                alt=altitude,
                speed=speed,
                gimbal_pitch=gimbal_pitch,
                heading=heading,
                action="none",
            )
        )
    return waypoints


# ---------------------------------------------------------------------------
# Cable cam
# ---------------------------------------------------------------------------

def cable_cam(
    path: List[Tuple[float, float]],
    samples: int = 20,
    altitude: float = 50.0,
    start_alt: Optional[float] = None,
    end_alt: Optional[float] = None,
    speed: float = 4.0,
    gimbal_pitch: int = -90,
    repeat: int = 1,
) -> List[Waypoint]:
    """Evenly spaced waypoints along a polyline."""
    from shapely.geometry import LineString

    if len(path) < 2:
        raise ValueError("cable_cam path needs >= 2 points")
    line = LineString([(lon, lat) for lat, lon in path])
    total_len = line.length
    if total_len <= 0:
        raise ValueError("cable_cam path has zero length")
    waypoints: List[Waypoint] = []
    idx = 0
    for r in range(repeat):
        for i in range(samples + 1):
            d = total_len * i / samples
            pt = line.interpolate(d)
            lat, lon = pt.y, pt.x
            if start_alt is not None and end_alt is not None:
                t = i / samples
                alt = start_alt + (end_alt - start_alt) * t
            else:
                alt = altitude
            waypoints.append(
                Waypoint(
                    index=idx,
                    lat=lat,
                    lon=lon,
                    alt=alt,
                    speed=speed,
                    gimbal_pitch=gimbal_pitch,
                    heading=None,
                    action="none",
                )
            )
            idx += 1
    return waypoints


# ---------------------------------------------------------------------------
# Corkscrew (helical climb)
# ---------------------------------------------------------------------------

def corkscrew(
    center_lat: float,
    center_lon: float,
    radius: float = 30.0,
    start_alt: float = 20.0,
    end_alt: float = 100.0,
    turns: float = 6.0,
    speed: float = 3.0,
    points_per_turn: int = 24,
    gimbal_pitch: int = -30,
) -> List[Waypoint]:
    """Helical corkscrew climb around a vertical centerline."""
    return spiral(
        center_lat=center_lat,
        center_lon=center_lon,
        start_radius=radius,
        end_radius=radius,
        turns=turns,
        start_alt=start_alt,
        end_alt=end_alt,
        speed=speed,
        gimbal_pitch=gimbal_pitch,
        points_per_turn=points_per_turn,
        inward=False,
        heading_mode="center",
    )


# ---------------------------------------------------------------------------
# Panel grid (rectangle survey)
# ---------------------------------------------------------------------------

def panel_grid(
    center_lat: float,
    center_lon: float,
    width: float = 100.0,
    height: float = 100.0,
    altitude: float = 50.0,
    speed: float = 5.0,
    line_spacing: float = 30.0,
    angle_deg: float = 0.0,
    gimbal_pitch: int = -90,
    action: str = "photo",
) -> List[Waypoint]:
    """Axis-aligned rectangle survey (4-corner polygon, internally optimized)."""
    half_w, half_h = width / 2, height / 2
    m_per_lat = meters_per_degree_lat()
    m_per_lon = meters_per_degree_lon(center_lat)
    corners_local = [(-half_w, -half_h), (half_w, -half_h),
                     (half_w, half_h), (-half_w, half_h)]
    corners_geo = []
    for x, y in corners_local:
        lat = center_lat + x / m_per_lat
        lon = center_lon + y / m_per_lon
        corners_geo.append((lat, lon))
    return polygon_survey(
        polygon_coords=corners_geo,
        altitude=altitude,
        speed=speed,
        line_spacing=line_spacing,
        angle_deg=angle_deg,
        gimbal_pitch=gimbal_pitch,
        action=action,
    )


# ---------------------------------------------------------------------------
# Stats & bounds
# ---------------------------------------------------------------------------

def waypoints_bounds(waypoints: List[Waypoint]) -> Tuple[float, float, float, float]:
    if not waypoints:
        return (0.0, 0.0, 0.0, 0.0)
    lats = [w.lat for w in waypoints]
    lons = [w.lon for w in waypoints]
    return (min(lats), min(lons), max(lats), max(lons))


def mission_stats(waypoints: List[Waypoint]) -> dict:
    if not waypoints:
        return {"waypoints": 0, "distance_m": 0.0, "duration_s": 0.0, "area_m2": 0.0}

    m_per_lat = meters_per_degree_lat()
    c_lat = sum(w.lat for w in waypoints) / len(waypoints)
    m_per_lon = meters_per_degree_lon(c_lat)

    total_dist = 0.0
    for a, b in zip(waypoints, waypoints[1:]):
        dx = (b.lon - a.lon) * m_per_lon
        dy = (b.lat - a.lat) * m_per_lat
        total_dist += math.sqrt(dx * dx + dy * dy)

    try:
        from shapely.geometry import Polygon as _P
        local = [((w.lon - waypoints[0].lon) * m_per_lon,
                  (w.lat - waypoints[0].lat) * m_per_lat) for w in waypoints]
        if len(local) >= 4:
            p = _P(local)
            if not p.is_valid:
                p = p.buffer(0)
            area = p.area
        else:
            area = 0.0
    except Exception:
        area = 0.0

    avg_speed = sum(w.speed for w in waypoints) / len(waypoints) or 1.0
    duration = total_dist / avg_speed

    return {
        "waypoints": len(waypoints),
        "distance_m": round(total_dist, 2),
        "duration_s": round(duration, 1),
        "area_m2": round(area, 2),
    }
