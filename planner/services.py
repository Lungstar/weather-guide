import math
import os
import threading
import time
import logging
from datetime import datetime, timedelta, timezone

import requests

from .risk import LEVELS, rank_key, summarize, weather_risk

MILES_PER_METER = 0.000621371192
MAX_CHECKPOINTS = 150
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": os.environ.get("ROUTEPILOT_USER_AGENT", "RoutePilotDemo/1.0")})
GEOCODE_LOCK = threading.Lock()
last_geocode = 0.0
logger = logging.getLogger(__name__)
US_STATES = dict(zip(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split(),
    ("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|District of Columbia").split("|")))


class ServiceError(Exception):
    pass


def get_json(url, params=None):
    try:
        response = SESSION.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ServiceError(f"An upstream service could not complete the request: {exc}") from exc


def geocode(query):
    global last_geocode
    # Nominatim's public service permits at most one request per second.
    with GEOCODE_LOCK:
        delay = 1.05 - (time.monotonic() - last_geocode)
        if delay > 0:
            time.sleep(delay)
        try:
            results = get_json("https://nominatim.openstreetmap.org/search",
                               {"q": query, "format": "jsonv2", "limit": 1})
        except ServiceError as exc:
            logger.warning("Nominatim unavailable; trying locality-only geocoding: %s", exc)
            return geocode_locality(query)
        finally:
            last_geocode = time.monotonic()
    if not results:
        raise ServiceError(f'No location found for "{query}". Try adding a city, state, or country.')
    result = results[0]
    return {"lat": float(result["lat"]), "lon": float(result["lon"]), "name": result["display_name"],
            "source": "Nominatim"}


def geocode_locality(query):
    parts = [part.strip() for part in query.split(",") if part.strip()]
    if not parts:
        raise ServiceError("Enter a city or town.")
    data = get_json("https://geocoding-api.open-meteo.com/v1/search",
                    {"name": parts[0], "count": 100, "language": "en", "format": "json"})
    for result in data.get("results", []):
        context = [str(result.get(key, "")).casefold() for key in ("admin1", "admin2", "country", "country_code")]
        if all(US_STATES.get(part.upper(), part).casefold() in context for part in parts[1:]):
            name = ", ".join(str(result[key]) for key in ("name", "admin1", "country") if result.get(key))
            return {"lat": result["latitude"], "lon": result["longitude"], "name": name,
                    "source": "Open-Meteo locality fallback"}
    raise ServiceError(f'Could not locate "{query}" with the fallback city search. Try a city, state, and country.')


def route_request(points, alternatives=False):
    coords = ";".join(f'{p["lon"]:.6f},{p["lat"]:.6f}' for p in points)
    base = os.environ.get("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
    data = get_json(f"{base}/route/v1/driving/{coords}",
                    {"alternatives": "3" if alternatives else "false", "overview": "full",
                     "geometries": "geojson", "steps": "false", "annotations": "duration"})
    if data.get("code") != "Ok":
        raise ServiceError(f'Routing service: {data.get("message", data.get("code", "unknown error"))}')
    return data["routes"]


def haversine(a, b):
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000 * math.asin(min(1, math.sqrt(h)))


def point_at(coords, cumulative, target):
    import bisect
    index = min(max(1, bisect.bisect_left(cumulative, target)), len(coords) - 1)
    span = cumulative[index] - cumulative[index - 1]
    fraction = (target - cumulative[index - 1]) / span if span else 0
    start, end = coords[index - 1], coords[index]
    return [start[0] + (end[0] - start[0]) * fraction, start[1] + (end[1] - start[1]) * fraction]


def route_signature(route):
    coords = route["geometry"]["coordinates"]
    cumulative = geometry_distances(coords)
    return [point_at(coords, cumulative, cumulative[-1] * fraction) for fraction in (0.25, 0.5, 0.75)]


def distinct(candidate, routes):
    signature = route_signature(candidate)
    for route in routes:
        other = route_signature(route)
        # Similar alternatives are not presented as different routes.
        if sum(haversine(a, b) for a, b in zip(signature, other)) / 3 < 3000:
            return False
    return True


def generate_routes(origin, destination):
    initial = route_request([origin, destination], alternatives=True)
    routes = []
    for route in initial:
        if distinct(route, routes):
            routes.append(route)
        if len(routes) == 3:
            return routes
    # Ask the routing engine for real routes through points on either side of
    # the midpoint when its alternatives endpoint returns fewer than three.
    mid_lat = (origin["lat"] + destination["lat"]) / 2
    mid_lon = (origin["lon"] + destination["lon"]) / 2
    lat_diff = destination["lat"] - origin["lat"]
    lon_diff = (destination["lon"] - origin["lon"]) * max(0.2, math.cos(math.radians(mid_lat)))
    for scale in (0.18, -0.18, 0.35, -0.35):
        via = {"lat": max(-85, min(85, mid_lat + lon_diff * scale)),
               "lon": max(-180, min(180, mid_lon - lat_diff * scale / max(0.2, math.cos(math.radians(mid_lat)))))}
        try:
            candidates = route_request([origin, via, destination])
        except ServiceError as exc:
            logger.warning("Alternative via-point routing failed: %s", exc)
            continue
        for route in candidates:
            if distinct(route, routes):
                routes.append(route)
                break
        if len(routes) == 3:
            break
    if len(routes) < 3:
        raise ServiceError("The routing service could not find three distinct routes for these locations. Try another trip.")
    return routes


def geometry_distances(coords):
    distances = [0.0]
    for a, b in zip(coords, coords[1:]):
        distances.append(distances[-1] + haversine(a, b))
    if distances[-1] <= 0:
        raise ServiceError("The routing service returned an empty route.")
    return distances


def sample_route(route, spacing):
    coords = route["geometry"]["coordinates"]
    if len(coords) < 2:
        raise ServiceError("The routing service returned an invalid route geometry.")
    cumulative = geometry_distances(coords)
    durations = [duration for leg in route["legs"] for duration in leg["annotation"]["duration"]]
    if len(durations) != len(coords) - 1:
        raise ServiceError("The routing service returned inconsistent timing data.")
    cumulative_time = [0.0]
    for duration in durations:
        cumulative_time.append(cumulative_time[-1] + duration)
    distance_miles = route["distance"] * MILES_PER_METER
    count = math.ceil(distance_miles / spacing) + 1
    if count > MAX_CHECKPOINTS:
        raise ServiceError(f"This trip requires more than {MAX_CHECKPOINTS} checkpoints per route. Choose a larger sampling interval.")
    samples = []
    for i in range(count):
        mile = min(i * spacing, distance_miles)
        fraction = mile / distance_miles if distance_miles else 0
        target = cumulative[-1] * fraction
        lon, lat = point_at(coords, cumulative, target)
        import bisect
        segment = min(max(1, bisect.bisect_left(cumulative, target)), len(coords) - 1)
        span = cumulative[segment] - cumulative[segment - 1]
        part = (target - cumulative[segment - 1]) / span if span else 0
        elapsed = cumulative_time[segment - 1] + durations[segment - 1] * part
        # Scale annotations to the route's total duration, including turn penalties.
        elapsed *= route["duration"] / cumulative_time[-1] if cumulative_time[-1] else 0
        samples.append({"lat": round(lat, 5), "lon": round(lon, 5), "mile": mile, "elapsed": elapsed,
                        "geometrySegment": segment})
    return samples


def fetch_weather(points):
    forecasts = []
    # Multi-location requests are batched to keep URLs and responses manageable.
    for start in range(0, len(points), 40):
        batch = points[start:start + 40]
        data = get_json("https://api.open-meteo.com/v1/forecast", {
            "latitude": ",".join(str(p["lat"]) for p in batch),
            "longitude": ",".join(str(p["lon"]) for p in batch),
            "hourly": "wind_gusts_10m,rain,snowfall",
            "wind_speed_unit": "mph", "timezone": "GMT", "forecast_days": 8,
        })
        if isinstance(data, dict):
            data = [data]
        if len(data) != len(batch):
            raise ServiceError("The weather service returned an incomplete forecast.")
        forecasts.extend(data)
    return forecasts


def hour_index(times, instant):
    # Open-Meteo precipitation and gusts describe the preceding hour.
    first = datetime.fromisoformat(times[0]).replace(tzinfo=timezone.utc)
    index = math.ceil((instant - first).total_seconds() / 3600)
    if index < 0 or index >= len(times):
        raise ServiceError("The trip extends beyond the available hourly weather forecast.")
    return index


def weather_at(hourly, index, load):
    try:
        wind = hourly["wind_gusts_10m"][index]
        rain = hourly["rain"][index] / 25.4
        snow = hourly["snowfall"][index] / 2.54
        if wind is None or not all(math.isfinite(v) and v >= 0 for v in (wind, rain, snow)):
            raise ValueError("Invalid weather value")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ServiceError("The weather service returned missing or invalid forecast data.") from exc
    risk = weather_risk(wind, rain, snow, load)
    return {"windMph": round(wind, 1), "rainIn": round(rain, 3), "snowIn": round(snow, 3),
            "risk": LEVELS[risk], "riskIndex": risk}


def build_plan(origin_text, destination_text, departure, load, spacing, now=None):
    now = now or datetime.now(timezone.utc)
    origin, destination = geocode(origin_text), geocode(destination_text)
    raw_routes = generate_routes(origin, destination)
    all_samples = [sample_route(route, spacing) for route in raw_routes]
    forecasts = iter(fetch_weather([point for samples in all_samples for point in samples]))
    routes = []
    slider_start = now.replace(minute=0, second=0, microsecond=0)
    for index, (route, samples) in enumerate(zip(raw_routes, all_samples)):
        checkpoints = []
        for sample in samples:
            hourly = next(forecasts)["hourly"]
            eta = departure + timedelta(seconds=sample["elapsed"])
            weather = weather_at(hourly, hour_index(hourly["time"], eta), load)
            heat = [weather_at(hourly, hour_index(hourly["time"], slider_start + timedelta(hours=h)), load)["riskIndex"]
                    for h in range(49)]
            checkpoints.append({"lat": sample["lat"], "lon": sample["lon"], "mile": sample["mile"],
                                "eta": eta.isoformat(), "geometrySegment": sample["geometrySegment"],
                                **weather, "forecastRisk": heat})
        summary = summarize(checkpoints, route["duration"], route["distance"] * MILES_PER_METER)
        routes.append({"id": index + 1, "geometry": route["geometry"], "checkpoints": checkpoints,
                       "summary": summary})
    ranked = sorted(routes, key=rank_key)
    for rank, route in enumerate(ranked, 1):
        route["rank"] = rank
    recommended = ranked[0] if ranked[0]["summary"]["riskMiles"]["No Travel"] == 0 else None
    return {"origin": origin, "destination": destination, "departure": departure.isoformat(),
            "load": load, "spacing": spacing, "forecastStart": slider_start.isoformat(),
            "routes": routes, "recommendedId": recommended["id"] if recommended else None}
