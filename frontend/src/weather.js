export async function fetchForecasts(points) {
  const forecasts = [];
  for (let start = 0; start < points.length; start += 40) {
    const batch = points.slice(start, start + 40);
    const params = new URLSearchParams({
      latitude: batch.map((point) => point.lat).join(","),
      longitude: batch.map((point) => point.lon).join(","),
      hourly: "wind_gusts_10m,rain,snowfall",
      wind_speed_unit: "mph",
      timezone: "GMT",
      forecast_days: "8",
    });
    let response;
    try {
      response = await fetch(`https://api.open-meteo.com/v1/forecast?${params}`);
    } catch {
      throw new Error("Cannot reach Open-Meteo from your browser. Check your connection or browser restrictions.");
    }
    if (!response.ok) {
      if (response.status === 429) throw new Error("Open-Meteo is rate-limiting this connection. Please try again later.");
      throw new Error(`Open-Meteo returned HTTP ${response.status}. Please try again later.`);
    }
    const data = await response.json();
    const results = Array.isArray(data) ? data : [data];
    if (results.length !== batch.length || results.some((forecast) => !forecast.hourly)) {
      throw new Error("Open-Meteo returned an incomplete forecast.");
    }
    forecasts.push(...results.map(({ hourly }) => ({ hourly })));
  }
  return forecasts;
}
