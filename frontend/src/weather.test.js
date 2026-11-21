import { test, afterEach } from "node:test";
import { strict as assert } from "node:assert";
import { fetchForecasts } from "./weather.js";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

test("requests all checkpoints in batches and preserves order", async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    const params = new URL(url).searchParams;
    const latitudes = params.get("latitude").split(",");
    calls.push(latitudes.length);
    return { ok: true, json: async () => latitudes.map((lat) => ({ hourly: { lat } })) };
  };
  const points = Array.from({ length: 41 }, (_, lat) => ({ lat, lon: -1 }));
  const forecasts = await fetchForecasts(points);
  assert.deepEqual(calls, [40, 1]);
  assert.equal(forecasts[40].hourly.lat, "40");
});

test("surfaces rate limits without pretending to have weather", async () => {
  globalThis.fetch = async () => ({ ok: false, status: 429 });
  await assert.rejects(fetchForecasts([{ lat: 1, lon: 2 }]), /rate-limiting/);
});

test("rejects incomplete responses", async () => {
  globalThis.fetch = async () => ({ ok: true, json: async () => [] });
  await assert.rejects(fetchForecasts([{ lat: 1, lon: 2 }]), /incomplete/);
});
