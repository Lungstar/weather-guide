import { test } from "node:test";
import { strict as assert } from "node:assert";
import { duration, localInputDate, LEVELS } from "./utils.js";

test("duration rounds minutes and formats hours", () => {
  assert.equal(duration(3599), "1h 00m");
  assert.equal(duration(3900), "1h 05m");
});

test("local input date retains local components", () => {
  assert.equal(localInputDate(new Date(2026, 0, 2, 3, 4)), "2026-01-02T03:04");
  assert.equal(LEVELS.length, 5);
});
