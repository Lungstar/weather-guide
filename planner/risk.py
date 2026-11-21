"""Weather classification and route ranking. All values use US customary units."""

LEVELS = ("Low", "Moderate", "High", "Severe", "No Travel")


def weather_risk(wind, rain, snow, load):
    wind_level = 4 if wind >= 55 else 3 if wind >= 45 else 2 if wind >= 35 else 1 if wind >= 25 else 0
    rain_level = 4 if rain > 1 else 3 if rain > 0.5 else 2 if rain > 0.25 else 1 if rain >= 0.1 else 0
    snow_level = 4 if snow > 3 else 3 if snow > 2 else 2 if snow > 1 else 1 if snow >= 0.5 else 0
    if wind >= 45 and load > 30000:
        wind_level = 4
    elif wind >= 35 and load > 40000:
        wind_level = max(wind_level, 3)
    return max(wind_level, rain_level, snow_level)


def summarize(checkpoints, duration_seconds, distance_miles):
    """Conservatively assign each interval the worse risk of its endpoints."""
    miles = {level: 0.0 for level in LEVELS}
    weighted = 0.0
    for left, right in zip(checkpoints, checkpoints[1:]):
        length = right["mile"] - left["mile"]
        risk = max(left["riskIndex"], right["riskIndex"])
        miles[LEVELS[risk]] += length
        weighted += risk * length
    return {
        "riskMiles": miles,
        "averageRisk": weighted / distance_miles if distance_miles else 0,
        "durationSeconds": duration_seconds,
        "distanceMiles": round(distance_miles, 1),
    }


def rank_key(route):
    summary = route["summary"]
    miles = summary["riskMiles"]
    # No Travel is a stronger constraint than the four requested tie-breakers.
    return (miles["No Travel"], miles["Severe"], miles["High"],
            summary["averageRisk"], summary["durationSeconds"])
