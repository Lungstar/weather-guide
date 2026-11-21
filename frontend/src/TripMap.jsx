import { useEffect, useMemo } from "react";
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
  useEffect(() => {
    if (!enabled || !routes.length) return undefined;
    const canvas = L.DomUtil.create("canvas", "weather-canvas");
    map.getPanes().overlayPane.appendChild(canvas);
    let frame;
    const draw = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const size = map.getSize();
        const topLeft = map.containerPointToLayerPoint([0, 0]);
        L.DomUtil.setPosition(canvas, topLeft);
        canvas.width = size.x;
        canvas.height = size.y;
        const ctx = canvas.getContext("2d");
        for (const route of routes) {
          for (let i = 1; i < route.checkpoints.length; i++) {
            const previous = route.checkpoints[i - 1];
            const current = route.checkpoints[i];
            const a = map.latLngToContainerPoint([previous.lat, previous.lon]);
            const b = map.latLngToContainerPoint([current.lat, current.lon]);
            const gradient = ctx.createLinearGradient(a.x, a.y, b.x, b.y);
            gradient.addColorStop(0, COLORS[previous.forecastRisk[hour]]);
            gradient.addColorStop(1, COLORS[current.forecastRisk[hour]]);
            ctx.strokeStyle = gradient;
            ctx.lineCap = "round";
            const path = new Path2D();
            path.moveTo(a.x, a.y);
            for (let j = previous.geometrySegment; j < current.geometrySegment; j++) {
              const [lon, lat] = route.geometry.coordinates[j];
              const p = map.latLngToContainerPoint([lat, lon]);
              path.lineTo(p.x, p.y);
            }
            path.lineTo(b.x, b.y);
            for (const [width, alpha] of [[85, 0.035], [60, 0.07], [35, 0.12]]) {
              ctx.globalAlpha = alpha;
              ctx.lineWidth = width;
              ctx.stroke(path);
            }
          }
          ctx.globalAlpha = 1;
          for (const point of route.checkpoints) {
            const pos = map.latLngToContainerPoint([point.lat, point.lon]);
            if (pos.x < -80 || pos.y < -80 || pos.x > size.x + 80 || pos.y > size.y + 80) continue;
            const gradient = ctx.createRadialGradient(pos.x, pos.y, 3, pos.x, pos.y, 52);
            gradient.addColorStop(0, `${COLORS[point.forecastRisk[hour]]}88`);
            gradient.addColorStop(1, `${COLORS[point.forecastRisk[hour]]}00`);
            ctx.fillStyle = gradient;
            ctx.fillRect(pos.x - 52, pos.y - 52, 104, 104);
          }
        }
      });
    };
    map.on("move zoom resize", draw);
    draw();
    return () => {
      cancelAnimationFrame(frame);
      map.off("move zoom resize", draw);
      canvas.remove();
    };
  }, [map, routes, hour, enabled]);
  return null;
}

export default function TripMap({ plan, selectedId, onSelect, hour, heatEnabled }) {
  const routes = plan?.routes || [];
  const selected = routes.find((route) => route.id === selectedId);
  const mapRoutes = useMemo(() => [...routes].sort((a, b) => (a.id === selectedId ? 1 : 0) - (b.id === selectedId ? 1 : 0)), [routes, selectedId]);
  return (
    <MapContainer center={[39.8, -98.6]} zoom={4} zoomControl={false} className="map" preferCanvas>
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <ZoomControl position="topright" />
      <FitRoutes routes={routes} />
      <HeatLayer routes={routes} hour={hour} enabled={heatEnabled} />
      {mapRoutes.map((route) => (
        <Polyline key={route.id} positions={route.geometry.coordinates.map(([lon, lat]) => [lat, lon])}
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
    </MapContainer>
  );
}
