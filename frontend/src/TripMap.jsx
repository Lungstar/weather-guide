import { memo, useEffect, useMemo, useRef } from "react";
import L from "leaflet";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, ZoomControl, useMap } from "react-leaflet";
import { COLORS, LEVELS, dateTime } from "./utils.js";

function FitRoutes({ routes }) {
  const map = useMap();
  useEffect(() => {
    if (routes.length) {
      const points = routes.flatMap((route) => route.geometry.coordinates.map(([lon, lat]) => [lat, lon]));
      map.fitBounds(points, { padding: [55, 55], maxZoom: 10 });
    }
  }, [map, routes]);
  return null;
}

function HeatLayer({ routes, hour, enabled }) {
  const map = useMap();
  const hourRef = useRef(hour);
  const redrawRef = useRef(null);
  useEffect(() => {
    hourRef.current = hour;
    redrawRef.current?.();
  }, [hour]);
  useEffect(() => {
    if (!enabled || !routes.length) return undefined;
    const canvas = L.DomUtil.create("canvas", "weather-canvas");
    const pane = map.getPane("weather") || map.createPane("weather");
    pane.style.zIndex = "390";
    pane.style.pointerEvents = "none";
    pane.appendChild(canvas);
    let frame;
    let projected = [];
    const project = () => {
      projected = routes.map((route) => {
        const points = route.checkpoints.map((point) => map.latLngToLayerPoint([point.lat, point.lon]));
        const segments = [];
        for (let i = 1; i < points.length; i++) {
          const vertices = [points[i - 1]];
          for (let j = route.checkpoints[i - 1].geometrySegment; j < route.checkpoints[i].geometrySegment; j++) {
            const [lon, lat] = route.geometry.coordinates[j];
            vertices.push(map.latLngToLayerPoint([lat, lon]));
          }
          vertices.push(points[i]);
          const simplified = L.LineUtil.simplify(vertices, 1.5);
          const path = new Path2D();
          path.moveTo(simplified[0].x, simplified[0].y);
          for (const point of simplified.slice(1)) path.lineTo(point.x, point.y);
          segments.push(path);
        }
        return { points, segments, checkpoints: route.checkpoints };
      });
    };
    const draw = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const size = map.getSize();
        const topLeft = map.containerPointToLayerPoint([0, 0]);
        L.DomUtil.setPosition(canvas, topLeft);
        canvas.width = size.x;
        canvas.height = size.y;
        const ctx = canvas.getContext("2d");
        ctx.translate(-topLeft.x, -topLeft.y);
        for (const route of projected) {
          for (let i = 1; i < route.points.length; i++) {
            const previous = route.checkpoints[i - 1];
            const current = route.checkpoints[i];
            const a = route.points[i - 1];
            const b = route.points[i];
            const gradient = ctx.createLinearGradient(a.x, a.y, b.x, b.y);
            gradient.addColorStop(0, COLORS[previous.forecastRisk[hourRef.current]]);
            gradient.addColorStop(1, COLORS[current.forecastRisk[hourRef.current]]);
            ctx.strokeStyle = gradient;
            ctx.lineCap = "round";
            for (const [width, alpha] of [[85, 0.025], [60, 0.045], [35, 0.075]]) {
              ctx.globalAlpha = alpha;
              ctx.lineWidth = width;
              ctx.stroke(route.segments[i - 1]);
            }
          }
          ctx.globalAlpha = 1;
          for (let i = 0; i < route.points.length; i++) {
            const pos = route.points[i];
            if (pos.x < topLeft.x - 80 || pos.y < topLeft.y - 80 || pos.x > topLeft.x + size.x + 80 || pos.y > topLeft.y + size.y + 80) continue;
            const point = route.checkpoints[i];
            const gradient = ctx.createRadialGradient(pos.x, pos.y, 3, pos.x, pos.y, 52);
            gradient.addColorStop(0, `${COLORS[point.forecastRisk[hourRef.current]]}55`);
            gradient.addColorStop(1, `${COLORS[point.forecastRisk[hourRef.current]]}00`);
            ctx.fillStyle = gradient;
            ctx.fillRect(pos.x - 52, pos.y - 52, 104, 104);
          }
        }
      });
    };
    const reproject = () => { project(); draw(); };
    project();
    redrawRef.current = draw;
    map.on("move resize", draw);
    map.on("zoomend", reproject);
    draw();
    return () => {
      cancelAnimationFrame(frame);
      redrawRef.current = null;
      map.off("move resize", draw);
      map.off("zoomend", reproject);
      canvas.remove();
    };
  }, [map, routes, enabled]);
  return null;
}

const EMPTY_ROUTES = [];

const RouteLayers = memo(function RouteLayers({ routes, selectedId, onSelect }) {
  const positions = useMemo(() => new Map(routes.map((route) => [route.id,
    route.geometry.coordinates.map(([lon, lat]) => [lat, lon])])), [routes]);
  const ordered = useMemo(() => [...routes].sort((a, b) => (a.id === selectedId ? 1 : 0) - (b.id === selectedId ? 1 : 0)), [routes, selectedId]);
  const selected = routes.find((route) => route.id === selectedId);
  return <>
    {ordered.map((route) => (
      <Polyline key={route.id} positions={positions.get(route.id)}
        pathOptions={{ color: route.id === selectedId ? "#236a65" : "#7c98a2", weight: route.id === selectedId ? 5 : 3, opacity: route.id === selectedId ? 0.95 : 0.7 }}
        eventHandlers={{ click: () => onSelect(route.id) }} />
    ))}
    {selected?.checkpoints.map((point, index) => (
      <CircleMarker key={index} center={[point.lat, point.lon]} radius={index === 0 || index === selected.checkpoints.length - 1 ? 7 : 4}
        pathOptions={{ color: "#fff", weight: 2, fillColor: COLORS[point.riskIndex], fillOpacity: 1 }}>
        <Popup>
          <strong>Mile {point.mile.toFixed(1)} · {point.risk}</strong><br />
          ETA {dateTime(point.eta)}<br />
          Wind gusts {point.windMph} mph<br />
          Rain {point.rainIn} in/hr · Snow {point.snowIn} in/hr
        </Popup>
      </CircleMarker>
    ))}
  </>;
});

export default function TripMap({ plan, selectedId, onSelect, hour, heatEnabled }) {
  const routes = plan?.routes || EMPTY_ROUTES;
  return (
    <MapContainer center={[39.8, -98.6]} zoom={4} zoomControl={false} className="map" preferCanvas>
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <ZoomControl position="topright" />
      <FitRoutes routes={routes} />
      <HeatLayer routes={routes} hour={hour} enabled={heatEnabled} />
      <RouteLayers routes={routes} selectedId={selectedId} onSelect={onSelect} />
    </MapContainer>
  );
}
