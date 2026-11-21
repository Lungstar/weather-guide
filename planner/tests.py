import json
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

from django.test import Client, SimpleTestCase

from .risk import rank_key, summarize, weather_risk
from .services import ServiceError, build_plan, geocode_locality, hour_index, sample_route, weather_at


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
        hourly["rain"][1] = None
        with self.assertRaises(ServiceError):
            weather_at(hourly, 1, 0)

    def test_sampling_includes_end_and_uses_segment_times(self):
        route = {"geometry": {"coordinates": [[0, 0], [1, 0], [2, 0]]},
                 "distance": 160934.4, "duration": 1000,
                 "legs": [{"annotation": {"duration": [100, 900]}}]}
        samples = sample_route(route, 25)
        self.assertEqual(len(samples), 5)
        self.assertAlmostEqual(samples[2]["elapsed"], 100, places=5)
        self.assertAlmostEqual(samples[-1]["elapsed"], 1000)
        self.assertAlmostEqual(samples[-1]["mile"], 100, places=3)

    @patch("planner.services.fetch_weather")
    @patch("planner.services.generate_routes")
    @patch("planner.services.geocode", return_value={"lat": 0, "lon": 0, "name": "Place"})
    def test_all_no_travel_routes_are_not_recommended(self, geocode, generate, fetch):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        route = {"geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]},
                 "distance": 16093.44, "duration": 3600,
                 "legs": [{"annotation": {"duration": [3600]}}]}
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
