import json
import os
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

import requests
from django.core import signing
from django.test import Client, SimpleTestCase

from .risk import rank_key, summarize, weather_risk
from .services import ServiceError, build_plan, fetch_weather, geocode_locality, get_json, hour_index, sample_route, weather_at


class RiskTests(TestCase):
    def test_wind_boundaries_and_load_rules(self):
        cases = [
            (24.99, 0, 0), (25, 0, 1), (34.99, 0, 1), (35, 40000, 2),
            (35, 40001, 3), (44.99, 40001, 3), (45, 30000, 3),
            (45, 30001, 4), (54.99, 0, 3), (55, 0, 4),
        ]
        for wind, load, expected in cases:
            with self.subTest(wind=wind, load=load):
                self.assertEqual(weather_risk(wind, 0, 0, load), expected)

    def test_rain_and_snow_boundaries(self):
        for rain, expected in [(0.099, 0), (0.1, 1), (0.25, 1), (0.251, 2),
                               (0.5, 2), (0.501, 3), (1, 3), (1.001, 4)]:
            self.assertEqual(weather_risk(0, rain, 0, 0), expected)
        for snow, expected in [(0.49, 0), (0.5, 1), (1, 1), (1.01, 2),
                               (2, 2), (2.01, 3), (3, 3), (3.01, 4)]:
            self.assertEqual(weather_risk(0, 0, snow, 0), expected)
        self.assertEqual(weather_risk(25, 0, 2.5, 0), 3)

    def test_segments_use_worse_endpoint_and_rank_safety_first(self):
        checkpoints = [{"mile": 0, "riskIndex": 0}, {"mile": 10, "riskIndex": 3},
                       {"mile": 25, "riskIndex": 2}]
        summary = summarize(checkpoints, 100, 25)
        self.assertEqual(summary["riskMiles"]["Severe"], 25)
        self.assertEqual(summary["averageRisk"], 3)
        safe = {"summary": summary}
        no_travel = {"summary": summarize([{"mile": 0, "riskIndex": 4}, {"mile": 1, "riskIndex": 0}], 1, 1)}
        self.assertLess(rank_key(safe), rank_key(no_travel))

    def test_ranking_tiebreakers_and_precision(self):
        def route(no_travel=0, severe=0, high=0, average=0, seconds=100):
            return {"summary": {"riskMiles": {"No Travel": no_travel, "Severe": severe, "High": high},
                                "averageRisk": average, "durationSeconds": seconds}}
        self.assertLess(rank_key(route(severe=0.001, seconds=200)), rank_key(route(severe=0.002, seconds=1)))
        self.assertLess(rank_key(route(high=1, average=4)), rank_key(route(high=2, average=0)))
        self.assertLess(rank_key(route(average=1, seconds=200)), rank_key(route(average=2, seconds=1)))
        self.assertLess(rank_key(route(seconds=100)), rank_key(route(seconds=101)))


class ForecastTests(TestCase):
    @patch("planner.services.get_json")
    def test_weather_customer_endpoint_and_public_fallback(self, get_json_mock):
        points = [{"lat": 41.0, "lon": -87.0}]
        get_json_mock.return_value = {"hourly": {}}
        with patch.dict(os.environ, {"OPEN_METEO_API_KEY": "test-key"}):
            self.assertEqual(fetch_weather(points), [{"hourly": {}}])
            args, kwargs = get_json_mock.call_args
            self.assertEqual(args[0], "https://customer-api.open-meteo.com/v1/forecast")
            self.assertEqual(args[1]["apikey"], "test-key")
            self.assertEqual(kwargs["service"], "Weather service")
        with patch.dict(os.environ, {"OPEN_METEO_API_KEY": ""}):
            fetch_weather(points)
            args, _ = get_json_mock.call_args
            self.assertEqual(args[0], "https://api.open-meteo.com/v1/forecast")
            self.assertNotIn("apikey", args[1])

    @patch("planner.services.SESSION.get")
    def test_weather_errors_do_not_expose_urls_or_keys(self, get):
        response = requests.Response()
        response.status_code = 429
        response.url = "https://example.test/forecast?apikey=secret-value"
        get.return_value = response
        with self.assertRaises(ServiceError) as error:
            get_json("https://example.test/forecast", service="Weather service")
        self.assertIn("rate-limited", str(error.exception))
        self.assertNotIn("secret-value", str(error.exception))
        self.assertNotIn("https://", str(error.exception))

    @patch("planner.services.get_json")
    def test_locality_fallback_matches_state_instead_of_guessing(self, get_json):
        get_json.return_value = {"results": [
            {"name": "Springfield", "latitude": 1, "longitude": 2, "admin1": "Massachusetts", "country": "United States", "country_code": "US"},
            {"name": "Springfield", "latitude": 3, "longitude": 4, "admin1": "Illinois", "country": "United States", "country_code": "US"},
        ]}
        result = geocode_locality("Springfield, IL")
        self.assertEqual(result["lat"], 3)
        with self.assertRaises(ServiceError):
            geocode_locality("Springfield, TX")

    def test_preceding_hour_and_units(self):
        times = ["2026-01-01T00:00", "2026-01-01T01:00", "2026-01-01T02:00"]
        self.assertEqual(hour_index(times, datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)), 1)
        hourly = {"time": times, "wind_gusts_10m": [0, 35, 0],
                  "rain": [0, 6.35, 0], "snowfall": [0, 2.54, 0]}
        result = weather_at(hourly, 1, 0)
        self.assertEqual(result["risk"], "High")
        self.assertAlmostEqual(result["rainIn"], 0.25)
        self.assertAlmostEqual(result["snowIn"], 1)
        with self.assertRaises(ServiceError):
            hour_index(times, datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc))
        with self.assertRaises(ServiceError):
            hour_index(times, datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc))
        hourly["rain"][1] = None
        with self.assertRaises(ServiceError):
            weather_at(hourly, 1, 0)

    def test_sampling_includes_end_and_uses_segment_times(self):
        route = {"geometry": {"coordinates": [[0, 0], [1, 0], [2, 0]]},
                 "distance": 160934.4, "duration": 1000,
                 "legs": [{"annotation": {"distance": [80467.2, 80467.2], "duration": [100, 900]}}]}
        samples = sample_route(route, 25)
        self.assertEqual(len(samples), 5)
        self.assertAlmostEqual(samples[2]["elapsed"], 100, places=5)
        self.assertAlmostEqual(samples[-1]["elapsed"], 1000)
        self.assertAlmostEqual(samples[-1]["mile"], 100, places=3)

    def test_sampling_uses_road_segment_distances_not_geometry_lengths(self):
        route = {"geometry": {"coordinates": [[0, 0], [1, 0], [2, 0]]},
                 "distance": 160934.4, "duration": 1000,
                 "legs": [{"annotation": {"distance": [40233.6, 120700.8], "duration": [400, 600]}}]}
        samples = sample_route(route, 25)
        self.assertAlmostEqual(samples[1]["lon"], 1.0, places=4)
        self.assertAlmostEqual(samples[1]["elapsed"], 400, places=4)
        self.assertAlmostEqual(samples[2]["lon"], 1 + 1 / 3, places=4)
        self.assertAlmostEqual(samples[2]["elapsed"], 600, places=4)
        self.assertAlmostEqual(samples[-1]["lon"], 2, places=4)

    def test_all_supported_spacing_intervals_include_final_partial_segment(self):
        route = {"geometry": {"coordinates": [[0, 0], [1, 0]]},
                 "distance": 177027.84, "duration": 3600,
                 "legs": [{"annotation": {"distance": [177027.84], "duration": [3600]}}]}
        for spacing, expected in ((10, 12), (25, 6), (50, 4)):
            with self.subTest(spacing=spacing):
                samples = sample_route(route, spacing)
                self.assertEqual(len(samples), expected)
                for left, right in zip(samples[:-2], samples[1:-1]):
                    self.assertAlmostEqual(right["mile"] - left["mile"], spacing)
                self.assertGreater(samples[-1]["mile"] - samples[-2]["mile"], 0)
                self.assertLessEqual(samples[-1]["mile"] - samples[-2]["mile"], spacing)
                self.assertAlmostEqual(samples[-1]["mile"], 110, places=3)
                self.assertAlmostEqual(samples[-1]["elapsed"], 3600)

    def test_sampling_rejects_missing_or_invalid_annotations(self):
        route = {"geometry": {"coordinates": [[0, 0], [1, 0]]}, "distance": 10,
                 "duration": 10, "legs": [{"annotation": {"duration": [10]}}]}
        with self.assertRaises(ServiceError):
            sample_route(route, 10)
        route["legs"][0]["annotation"]["distance"] = [float("nan")]
        with self.assertRaises(ServiceError):
            sample_route(route, 10)

    @patch("planner.services.fetch_weather")
    @patch("planner.services.generate_routes")
    @patch("planner.services.geocode", return_value={"lat": 0, "lon": 0, "name": "Place"})
    def test_all_no_travel_routes_are_not_recommended(self, geocode, generate, fetch):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        route = {"geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]},
                 "distance": 16093.44, "duration": 3600,
                 "legs": [{"annotation": {"distance": [16093.44], "duration": [3600]}}]}
        generate.return_value = [route, route, route]
        times = [(now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(72)]
        forecast = {"hourly": {"time": times, "wind_gusts_10m": [55] * 72,
                               "rain": [0] * 72, "snowfall": [0] * 72}}
        fetch.return_value = [forecast] * 6
        result = build_plan("A", "B", now, 0, 25, now)
        self.assertIsNone(result["recommendedId"])
        self.assertEqual(len(result["routes"]), 3)
        self.assertEqual(result["routes"][0]["checkpoints"][-1]["eta"], (now + timedelta(hours=1)).isoformat())
        self.assertGreater(result["routes"][0]["summary"]["riskMiles"]["No Travel"], 0)
        self.assertEqual(len(result["routes"][0]["checkpoints"][0]["forecastRisk"]), 49)


class ApiTests(SimpleTestCase):
    def setUp(self):
        self.client = Client()

    def test_invalid_requests_are_explicit(self):
        response = self.client.post("/api/plan", data=json.dumps({"origin": "", "destination": "x"}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("origin and destination", response.json()["error"])
        self.assertEqual(self.client.get("/api/plan").status_code, 405)

    @patch("planner.views.build_plan", return_value={"routes": []})
    def test_valid_request(self, build):
        departure = datetime.now(timezone.utc).isoformat()
        response = self.client.post("/api/plan", data=json.dumps({"origin": "A", "destination": "B",
                                    "departure": departure, "load": 30000, "spacing": 25}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(build.call_args.args[3:], (30000, 25, build.call_args.args[5]))

    @patch.dict(os.environ, {"OPEN_METEO_API_KEY": ""})
    @patch("planner.views.prepare_plan")
    def test_browser_weather_prepare_and_finish(self, prepare):
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        route = {"geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]},
                 "distance": 16093.44, "duration": 3600}
        sample = {"lat": 0, "lon": 0, "mile": 0, "elapsed": 0, "geometrySegment": 1}
        end = {**sample, "mile": 10, "elapsed": 3600, "lon": 1}
        prepare.return_value = {"origin": {"name": "A"}, "destination": {"name": "B"},
                                "departure": now.isoformat(), "now": now.isoformat(),
                                "load": 0, "spacing": 25, "rawRoutes": [route] * 3,
                                "samples": [[sample, end]] * 3}
        response = self.client.post("/api/plan", data=json.dumps({"origin": "A", "destination": "B",
                                    "departure": datetime.now(timezone.utc).isoformat(), "load": 0,
                                    "spacing": 25, "browserWeather": True}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["weatherPoints"]), 6)
        token = response.json()["planToken"]
        times = [(now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(72)]
        forecast = {"hourly": {"time": times, "wind_gusts_10m": [0] * 72,
                               "rain": [0] * 72, "snowfall": [0] * 72}}
        payload = {"planToken": token, "forecasts": [forecast] * 6}
        response = self.client.post("/api/plan/finish", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["routes"]), 3)
        payload["planToken"] += "tampered"
        self.assertEqual(self.client.post("/api/plan/finish", data=json.dumps(payload),
                                        content_type="application/json").status_code, 400)
        payload["planToken"] = token
        payload["forecasts"] = [forecast]
        self.assertEqual(self.client.post("/api/plan/finish", data=json.dumps(payload),
                                        content_type="application/json").status_code, 400)
        payload["planToken"] = signing.dumps(prepare.return_value)
        payload["forecasts"] = [{**forecast, "hourly": {**forecast["hourly"], "time": ["bad"] * 72}}] * 6
        self.assertEqual(self.client.post("/api/plan/finish", data=json.dumps(payload),
                                        content_type="application/json").status_code, 400)
