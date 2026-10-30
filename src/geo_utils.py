import math
from shapely.geometry import Point, shape
from rasterio import warp

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def range_bearing_km(ref_lat, ref_lon, lat, lon):
    dist_m = haversine_m(ref_lat, ref_lon, lat, lon)
    y = math.sin(math.radians(lon - ref_lon)) * math.cos(math.radians(lat))
    x = (math.cos(math.radians(ref_lat)) * math.sin(math.radians(lat))
         - math.sin(math.radians(ref_lat)) * math.cos(math.radians(lat))
         * math.cos(math.radians(lon - ref_lon)))
    bearing = math.degrees(math.atan2(y, x))
    return dist_m / 1000.0, (bearing + 360) % 360

def dead_reckon(lat, lon, sog_knots, cog_deg, dt_seconds):
    R = 6371000.0
    dist_m = sog_knots * 0.514444 * dt_seconds
    delta = dist_m / R
    lat2 = math.asin(math.sin(math.radians(lat)) * math.cos(delta)
                     + math.cos(math.radians(lat)) * math.sin(delta)
                     * math.cos(math.radians(cog_deg)))
    lon2 = (math.radians(lon) + math.atan2(
        math.sin(math.radians(cog_deg)) * math.sin(delta) * math.cos(math.radians(lat)),
        math.cos(delta) - math.sin(math.radians(lat)) * math.sin(math.radians(lat2))))
    return math.degrees(lat2), math.degrees(lon2)

def point_in_polygon(lat, lon, polygon_geojson):
    return Point(lon, lat).within(shape(polygon_geojson))

def pixel_to_lonlat(transform, col, row):
    lon, lat = warp.transform(transform, [col], [row])
    return float(lon[0]), float(lat[0])

def lonlat_to_pixel(transform, lon, lat):
    col, row = warp.transform(transform, [lon], [lat], direction="inverse")
    return int(col[0]), int(row[0])
