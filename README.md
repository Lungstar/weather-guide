# RoutePilot

A React and Django trip planner that compares three weather-aware route options, samples forecasts at estimated arrival times, and displays a 48-hour weather-risk corridor.

> **Safety limitation:** The public OSRM endpoint uses a **car** profile, not a truck profile. It does not account for truck height, weight restrictions, hazmat, road closures, driver hours, actual traffic, or real-time road conditions. Weather is a forecast, not an observation or a guarantee. Never rely on this app as the sole basis for a driving decision. Verify the route and conditions with authoritative sources.

## Run locally

Requires Python 3.10+ and Node.js 20+. In a terminal at the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py runserver
```

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open the Vite URL shown in the terminal (normally `http://127.0.0.1:5173/static/`). The development server proxies API requests to Django at port 8000. To serve the built UI from Django, run `npm run build` in `frontend`, then `python manage.py collectstatic --noinput` and open `http://127.0.0.1:8000/`.

Run tests with `python manage.py test` and `npm test` in `frontend`. Build the frontend with `npm run build`.

## How it works

1. Nominatim geocodes the input. If it is unavailable, Open-Meteo's city-level geocoder is used as a fallback and the resolved locations are shown for verification; street addresses are not supported by this fallback. OSRM requests alternative routes; if fewer than three distinct routes are returned, additional routes are requested through intermediate waypoints. If three distinct routes cannot be obtained, the app reports an error instead of inventing routes.
2. The route is sampled at the chosen 10, 25, or 50 mile interval, including both endpoints. Estimated checkpoint arrival times use OSRM's per-segment duration annotations scaled to the route's total duration. Traffic and mandatory breaks are not included. Longer trips may need a larger interval: the limit is 150 checkpoints **per route**.
3. Open-Meteo's hourly wind gusts at 10 m, rain and snowfall are used. Open-Meteo provides rain in mm and snowfall in cm; these are converted to inches. Gusts and precipitation represent the preceding hour, so a checkpoint between hourly timestamps uses the next hour's forecast. Missing data or a trip beyond the available forecast is an error, never silently treated as safe. Departures must be within the next 48 hours; forecasts cover eight days.
4. The overall checkpoint risk is the worst condition after applying the load rules. For adjacent thresholds sharing an endpoint, the stated upper endpoint is inclusive: rain 0.25/0.50/1.00 and snow 1.0/2.0/3.0 remain in the lower band. Wind thresholds start at 25/35/45/55 mph. Load comparisons are strictly greater than 30,000 or 40,000 lb, as specified.
5. Each interval is conservatively assigned the worse risk of its two endpoints. Risk miles are distance-weighted, and average risk uses scores Low=0 through No Travel=4. Routes are ranked lexicographically by **No Travel miles**, Severe miles, High miles, average risk, then duration. No Travel is prioritized above the requested criteria because it is a stronger safety constraint. If every route has No Travel miles, the app displays a warning and does not label any route recommended. The ranking is a comparison, not a declaration that a route is safe.
6. The slider displays risk forecasts from the current UTC hour through +48 hours at all sampled points. Its translucent corridor follows the route geometry and interpolates visually between samples; it is **not** a gridded regional weather forecast. Checkpoint markers and the list always show conditions at the truck's ETA, independently of the slider. Times are displayed in the browser's local time zone.

## APIs and operations

No API key is required for the demo: [OSRM](https://project-osrm.org/), [Nominatim](https://nominatim.org/), [Open-Meteo](https://open-meteo.com/) and [OpenStreetMap](https://www.openstreetmap.org/copyright) provide routing, geocoding, weather, and map tiles. These public endpoints have usage policies, rate limits, availability limits, and may not be suitable for commercial production. Set `ROUTEPILOT_USER_AGENT` to identify your application and contact email, per Nominatim's policy. The bundled deployment uses one worker so its per-process one-request-per-second geocoding limiter is effective; multiple instances require a shared limiter. `OSRM_URL` may point to a compatible self-hosted OSRM instance. For a real trucking product, use an appropriately licensed truck-specific routing provider and operational-grade forecast/tile/geocoding services.

Open-Meteo warns that its free API can rate-limit shared hosting IPs, including Render. For reliable hosted usage, obtain an [Open-Meteo customer API key](https://open-meteo.com/en/pricing) and set `OPEN_METEO_API_KEY` as a secret environment variable in Render. The backend then uses Open-Meteo's authenticated customer forecast endpoint. Never commit the key. A customer subscription may incur charges; review the provider's terms and pricing before subscribing. Without a key, the public API remains in use and may return rate-limit errors. The key applies to forecast requests, not the separate Open-Meteo geocoding fallback.

Without a customer key the web UI requests forecasts directly from Open-Meteo in the visitor's browser, rather than from the hosting provider's shared outbound IP. Checkpoint coordinates and the visitor's IP address are therefore sent to Open-Meteo. The browser sends the returned data to Django for risk calculation; this is client-supplied data and can be altered by the client, so results must not be used as trusted server-side records. Direct requests remain subject to Open-Meteo's terms and limits and can fail if a browser extension, network policy or the provider blocks them. The original server-side `/api/plan` remains available for API clients.

## Deployment

The included Dockerfile builds the React app and serves it with Django, WhiteNoise and Gunicorn. `render.yaml` can be used to create a Render web service from a GitHub repository. Set `ROUTEPILOT_USER_AGENT` to a real application name and contact, and use `DJANGO_DEBUG=0`, a strong `DJANGO_SECRET_KEY`, and `DJANGO_ALLOWED_HOSTS` for your host; Render's external hostname is accepted automatically. The application is stateless and needs no database.

To publish: create a GitHub repository, push this folder, create a Render Blueprint from it, set the contact value, and deploy. Public service availability and third-party terms must be reviewed before deployment. No credentials or hosting account are included.

## Walkthrough outline (5–10 minutes)

1. Explain the safety and truck-routing limitations.
2. Enter origin, destination, departure and load; choose a checkpoint interval and plan.
3. Compare the three route cards, selection, recommendation and risk-mile summaries.
4. Inspect checkpoint ETAs and weather; click markers and move the 0–48-hour corridor slider.
5. Walk through the threshold/load rules, conservative interval scoring and lexicographic ranking.
6. Show the tests and explain how to deploy and replace the public API providers.
