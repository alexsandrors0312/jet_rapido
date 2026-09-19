"""Identidade geográfica e distâncias sem dependência de provedor."""

from hashlib import sha256
from math import asin, cos, radians, sin, sqrt

from .importer import normalized_text


def delivery_point_key(address: str, neighborhood: str, city: str, postal_code: str) -> str:
    identity = "|".join(normalized_text(value) for value in (address, neighborhood, city, postal_code))
    return sha256(identity.encode("utf-8")).hexdigest()


def haversine_meters(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    radius_m = 6_371_008.8
    lat_a, lat_b = radians(latitude_a), radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = radians(longitude_b - longitude_a)
    value = sin(delta_lat / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    return 2 * radius_m * asin(sqrt(value))
