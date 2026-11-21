import { useState } from "react";
import { AlertTriangle, ArrowDown, ArrowRight, CalendarDays, Check, ChevronDown, Clock3, CloudSun, Compass, Gauge, Layers2, MapPin, Navigation, Route, ShieldCheck, SlidersHorizontal, Truck, Wind } from "lucide-react";
import TripMap from "./TripMap.jsx";
import { COLORS, LEVELS, dateTime, duration, localInputDate } from "./utils.js";

function Logo() {
  return <div className="brand"><div className="brand-icon"><Navigation size={19} fill="currentColor" /></div><div>route<span>pilot</span><small>DRIVE WITH CONFIDENCE</small></div></div>;
}

function RiskBadge({ route }) {
  const miles = route.summary.riskMiles;
  const risk = [...LEVELS].reverse().find((level) => miles[level] > 0) || "Low";
  return <span className="risk-badge" style={{ "--risk-color": COLORS[LEVELS.indexOf(risk)] }}><i />{risk} risk</span>;
}

function RouteCard({ route, selected, recommended, onClick }) {
  const { summary } = route;
  return <button type="button" className={`route-card ${selected ? "selected" : ""}`} onClick={onClick}>
    <div className="route-card-top"><div className="route-title"><span className="route-number">{route.id}</span><strong>Route {route.id}</strong>{recommended && <span className="recommended"><Check size={11} /> RECOMMENDED</span>}</div><RiskBadge route={route} /></div>
    <div className="route-stats"><span><Clock3 size={15} /> <b>{duration(summary.durationSeconds)}</b></span><span><Route size={15} /> {summary.distanceMiles.toLocaleString()} mi</span><span><Gauge size={15} /> {summary.averageRisk.toFixed(2)} avg</span></div>
    <div className="risk-bar">{LEVELS.map((level, index) => <span key={level} title={`${level}: ${summary.riskMiles[level]} mi`} style={{ width: `${summary.riskMiles[level] / summary.distanceMiles * 100}%`, background: COLORS[index] }} />)}</div>
    <div className="risk-breakdown">{LEVELS.map((level, index) => <span key={level}><i style={{ background: COLORS[index] }} />{level}: {summary.riskMiles[level].toFixed(1)} mi</span>)}</div>
    <div className="route-foot"><span>{summary.riskMiles.Severe + summary.riskMiles["No Travel"] > 0 ? `${(summary.riskMiles.Severe + summary.riskMiles["No Travel"]).toFixed(1)} mi severe / no travel` : "No severe conditions"}</span><span>View route <ArrowRight size={13} /></span></div>
  </button>;
}

export default function App() {
  const [origin, setOrigin] = useState("Chicago, IL");
  const [destination, setDestination] = useState("Detroit, MI");
  const [departure, setDeparture] = useState(() => localInputDate(new Date(Date.now() + 60 * 60 * 1000)));
  const [load, setLoad] = useState("35000");
  const [spacing, setSpacing] = useState(25);
  const [plan, setPlan] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [hour, setHour] = useState(0);
  const [heatEnabled, setHeatEnabled] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setError("");
    const date = new Date(departure);
    if (!Number.isFinite(date.getTime())) { setError("Enter a valid departure date and time."); return; }
    setPlan(null);
    setSelectedId(null);
    setLoading(true);
    try {
      const response = await fetch("/api/plan", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ origin, destination, departure: date.toISOString(), load: Number(load), spacing }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Unable to plan the trip.");
      setPlan(data);
      setSelectedId(data.recommendedId ?? data.routes.find((route) => route.rank === 1).id);
      setHour(0);
    } catch (err) {
      setError(err.message || "Unable to reach the trip planning service.");
    } finally { setLoading(false); }
  }

  const selected = plan?.routes.find((route) => route.id === selectedId);
  const forecastTime = plan ? new Date(new Date(plan.forecastStart).getTime() + hour * 3600000) : null;
  return <div className="app">
    <header className="header"><Logo /><div className="header-right"><span><span className="online-dot" /> WEATHER-AWARE ROUTING</span><div className="header-divider" /><span className="header-tag"><ShieldCheck size={16} /> Built for the road ahead</span></div></header>
    <main className="workspace">
      <aside className="sidebar">
        <div className="sidebar-inner">
          <div className="eyebrow"><span /> YOUR TRIP PLANNER</div>
          <h1>A safer way<br /><em>forward.</em></h1>
          <p className="intro">Make the road ahead a little more predictable.</p>
          <form onSubmit={submit}>
            <div className="section-title"><span>01</span> YOUR JOURNEY</div>
            <div className="location-fields">
              <div className="location-line" />
              <label><span className="field-label">ORIGIN</span><div className="input-wrap"><MapPin size={17} className="origin-icon" /><input value={origin} onChange={(e) => setOrigin(e.target.value)} placeholder="Where are you starting?" required maxLength={200} /></div></label>
              <label><span className="field-label">DESTINATION</span><div className="input-wrap"><MapPin size={17} className="destination-icon" /><input value={destination} onChange={(e) => setDestination(e.target.value)} placeholder="Where are you headed?" required maxLength={200} /></div></label>
            </div>
            <div className="field-grid">
              <label><span className="field-label">DEPARTURE</span><div className="input-wrap"><CalendarDays size={16} /><input type="datetime-local" value={departure} onChange={(e) => setDeparture(e.target.value)} required /></div></label>
              <label><span className="field-label">LOAD WEIGHT</span><div className="input-wrap"><Truck size={16} /><input type="number" min="0" max="200000" step="1" value={load} onChange={(e) => setLoad(e.target.value)} required /><span className="input-suffix">lb</span></div></label>
            </div>
            <label className="sampling-label"><span className="field-label">WEATHER CHECKPOINTS</span><div className="select-wrap"><SlidersHorizontal size={16} /><select value={spacing} onChange={(e) => setSpacing(Number(e.target.value))}><option value={10}>Every 10 miles</option><option value={25}>Every 25 miles</option><option value={50}>Every 50 miles</option></select><ChevronDown size={15} /></div></label>
            <button className="submit" disabled={loading} type="submit">{loading ? <><span className="spinner" /> Finding your routes...</> : <>Find safer routes <ArrowRight size={17} /></>}</button>
            {error && <div className="error" role="alert"><AlertTriangle size={16} />{error}</div>}
          </form>
          {plan && <div className="results">
            <div className="section-title"><span>02</span> YOUR ROUTE OPTIONS <small>3 ROUTES</small></div>
            <p className="results-intro">Ranked for weather safety, then travel time.</p>
            {(plan.origin.source !== "Nominatim" || plan.destination.source !== "Nominatim") && <div className="error"><AlertTriangle size={16} />City-level geocoding fallback was used. Verify the resolved locations: {plan.origin.name} → {plan.destination.name}.</div>}
            {plan.recommendedId === null && <div className="error" role="alert"><AlertTriangle size={16} />All routes include No Travel conditions. Do not travel; consider a different departure time.</div>}
            {[...plan.routes].sort((a, b) => a.rank - b.rank).map((route) => <RouteCard key={route.id} route={route} selected={route.id === selectedId} recommended={route.id === plan.recommendedId} onClick={() => setSelectedId(route.id)} />)}
            {selected && <div className="checkpoints"><div className="checkpoint-heading"><strong>Checkpoint forecast</strong><span>{selected.checkpoints.length} stops</span></div><p>Conditions at estimated arrival time</p>
              <div className="checkpoint-list">{selected.checkpoints.map((point, index) => <div className="checkpoint-row" key={index}><span className="checkpoint-dot" style={{ background: COLORS[point.riskIndex] }} /><div><strong>Mile {point.mile.toFixed(1)}</strong><small>{dateTime(point.eta)}</small></div><div className="checkpoint-weather"><strong>{point.risk}</strong><small>{point.windMph} mph gusts · {point.rainIn}″ rain · {point.snowIn}″ snow / hr</small></div></div>)}</div>
            </div>}
          </div>}
          <div className="safety-note"><ShieldCheck size={17} /><span><b>Plan smart. Drive safe.</b> Routes use a car routing profile, not truck restrictions. Verify clearances, road closures, forecasts and regulations before driving.</span></div>
        </div>
      </aside>
      <section className="map-area" aria-label="Route and weather map">
        <TripMap plan={plan} selectedId={selectedId} onSelect={setSelectedId} hour={hour} heatEnabled={heatEnabled} />
        <div className="map-top"><div className="map-heading"><span className="map-heading-icon"><Compass size={18} /></span><div><strong>{plan ? "Your route overview" : "The road, in perspective"}</strong><small>{plan ? `${plan.origin.name.split(",")[0]} to ${plan.destination.name.split(",")[0]}` : "Plan a trip to explore your route"}</small></div></div><button className={`layer-button ${heatEnabled ? "active" : ""}`} onClick={() => setHeatEnabled(!heatEnabled)} aria-pressed={heatEnabled}><Layers2 size={16} /> Weather layer</button></div>
        {!plan && <div className="empty-map"><div className="empty-icon"><Navigation size={24} /></div><strong>Adventure is out there.</strong><p>Enter your trip details to see routes and weather conditions along the way.</p><span><ArrowDown size={14} /> YOUR JOURNEY STARTS HERE</span></div>}
        {plan && <div className="map-bottom"><div className="legend"><span>WEATHER RISK</span>{LEVELS.map((level, index) => <div key={level}><i style={{ background: COLORS[index] }} />{level}</div>)}</div><div className="forecast-control"><div className="forecast-header"><div><CloudSun size={20} /><span><b>Weather along the way</b><small>Forecast corridor · {dateTime(forecastTime)}</small></span></div><span className="hour-pill">+{hour} HR</span></div><input aria-label="Forecast hour" type="range" min="0" max="48" step="1" value={hour} onChange={(e) => setHour(Number(e.target.value))} /><div className="slider-labels"><span>NOW</span><span>+12H</span><span>+24H</span><span>+36H</span><span>+48H</span></div></div></div>}
      </section>
    </main>
  </div>;
}
