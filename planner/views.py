import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone

from django.core import signing
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .services import ServiceError, build_plan, complete_plan, prepare_plan

logger = logging.getLogger(__name__)


@require_POST
def plan(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError("Request must be a JSON object.")
        origin, destination = data.get("origin"), data.get("destination")
        if not all(isinstance(value, str) and 1 <= len(value.strip()) <= 200 for value in (origin, destination)):
            raise ValueError("Enter an origin and destination (up to 200 characters each).")
        departure = datetime.fromisoformat(data["departure"].replace("Z", "+00:00"))
        if departure.tzinfo is None:
            raise ValueError("Departure must include a time zone.")
        departure = departure.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        if departure < now - timedelta(minutes=5) or departure > now + timedelta(hours=48):
            raise ValueError("Departure must be within the next 48 hours.")
        load = float(data["load"])
        if not math.isfinite(load) or load < 0 or load > 200000:
            raise ValueError("Load weight must be between 0 and 200,000 lb.")
        spacing = data["spacing"]
        if isinstance(spacing, bool) or spacing not in (10, 25, 50):
            raise ValueError("Sampling interval must be 10, 25, or 50 miles.")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
        return JsonResponse({"error": str(exc) or "Invalid request."}, status=400)
    try:
        if data.get("browserWeather") is True and not os.environ.get("OPEN_METEO_API_KEY", "").strip():
            prepared = prepare_plan(origin.strip(), destination.strip(), departure, load, spacing, now)
            points = [{"lat": p["lat"], "lon": p["lon"]} for samples in prepared["samples"] for p in samples]
            result = {"weatherPoints": points, "planToken": signing.dumps(prepared, compress=True)}
        else:
            result = build_plan(origin.strip(), destination.strip(), departure, load, spacing, now)
    except ServiceError as exc:
        logger.warning("Trip planning failed: %s", exc)
        return JsonResponse({"error": str(exc)}, status=502)
    return JsonResponse(result)


@require_POST
def finish_plan(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict) or not isinstance(data.get("planToken"), str):
            raise ValueError("Invalid trip data.")
        prepared = signing.loads(data["planToken"], max_age=900)
        result = complete_plan(prepared, data.get("forecasts"))
    except (json.JSONDecodeError, ValueError, TypeError, signing.BadSignature) as exc:
        logger.warning("Invalid trip completion request: %s", exc)
        return JsonResponse({"error": "Trip data is invalid or expired. Please plan the trip again."}, status=400)
    except ServiceError as exc:
        logger.warning("Trip completion failed: %s", exc)
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(result)
