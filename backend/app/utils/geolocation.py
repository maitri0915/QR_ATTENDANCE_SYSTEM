"""
Straight-line distance between two GPS points (Haversine formula).
Used to reject a QR scan if the student's device isn't near the classroom —
mitigates a student handing their unlocked phone to a friend elsewhere.
"""
import math

EARTH_RADIUS_METERS = 6371000
DEFAULT_MAX_DISTANCE_METERS = 100  # tune per classroom/building size


def distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_METERS * c
