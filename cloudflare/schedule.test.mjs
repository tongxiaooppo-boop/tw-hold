import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dueWorkflows, cronMinutes } from "./schedule.js";
import worker, { dispatch } from "./worker.js";

const cases = [
  ["global_macro_週二0517", "2026-11-16T21:17:00Z", ["global_macro.yml"]],
  ["global_macro_週一0517不跑", "2026-11-15T21:17:00Z", []],
  ["openapi_週六0407", "2026-11-13T20:07:00Z", ["openapi_daily.yml"]],
  ["openapi_週一0407不跑", "2026-11-15T20:07:00Z", []],
  ["openapi_週一1607", "2026-11-16T08:07:00Z", ["openapi_daily.yml"]],
  ["openapi_週六1607不跑", "2026-11-14T08:07:00Z", []],
  ["heartbeat_週一0823", "2026-11-16T00:23:00Z", ["heartbeat.yml"]],
  ["chip_週一1523", "2026-11-16T07:23:00Z", ["chip_flow_evening.yml"]],
  ["revenue_17號1847", "2026-11-17T10:47:00Z", ["revenue_watch.yml"]],
  ["revenue_18號1847不跑", "2026-11-18T10:47:00Z", []],
  ["revenue_18號0747", "2026-11-17T23:47:00Z", ["revenue_watch.yml"]],
  ["revenue_19號0747不跑", "2026-11-18T23:47:00Z", []],
  ["revenue_1號0747不跑", "2026-11-30T23:47:00Z", []],
  ["非表定分鐘", "2026-11-16T08:13:00Z", []],
  ["秒數不影響", "2026-11-16T08:07:42Z", ["openapi_daily.yml"]],
];
for (const [name, utc, want] of cases) {
  test(name, () => assert.deepEqual(dueWorkflows(new Date(utc)), want));
}

test("cron分鐘與wrangler一致", () => {
  const toml = readFileSync(new URL("./wrangler.toml", import.meta.url), "utf8");
  const m = toml.match(/crons\s*=\s*\[([^\]]*)\]/);
  const crons = [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
  assert.equal(crons.length, 1);
  const mins = crons[0].split(/\s+/)[0].split(",").map(Number).sort((a, b) => a - b);
  assert.deepEqual(mins, cronMinutes());
});

test("避開整點半點", () => {
  for (const m of cronMinutes()) {
    assert.ok(!(m >= 57 || m <= 3), `minute ${m} near hour`);
    assert.ok(!(m >= 27 && m <= 33), `minute ${m} near half hour`);
  }
});

function withFetch(impl, fn) {
  const orig = globalThis.fetch;
  globalThis.fetch = impl;
  return Promise.resolve(fn()).finally(() => { globalThis.fetch = orig; });
}

test("worker_命中時dispatch", async () => {
  const calls = [];
  await withFetch(async (url, init) => { calls.push([url, init]); return { status: 204, text: async () => "" }; },
    () => worker.scheduled({ scheduledTime: Date.parse("2026-11-16T08:07:00Z") }, { GH_TOKEN: "t" }, {}));
  assert.equal(calls.length, 1);
  assert.ok(calls[0][0].endsWith("/actions/workflows/openapi_daily.yml/dispatches"));
  assert.equal(calls[0][1].method, "POST");
  assert.equal(calls[0][1].body, JSON.stringify({ ref: "main" }));
  assert.equal(calls[0][1].headers.Authorization, "Bearer t");
});

test("worker_不命中不呼叫", async () => {
  let n = 0;
  await withFetch(async () => { n++; return { status: 204, text: async () => "" }; },
    () => worker.scheduled({ scheduledTime: Date.parse("2026-11-16T08:13:00Z") }, { GH_TOKEN: "t" }, {}));
  assert.equal(n, 0);
});

test("dispatch_失敗重試一次", async () => {
  let n = 0;
  const f = async () => (++n === 1 ? { status: 500, text: async () => "boom" } : { status: 204, text: async () => "" });
  const r = await dispatch("heartbeat.yml", "t", f);
  assert.equal(n, 2);
  assert.equal(r.ok, true);
});
