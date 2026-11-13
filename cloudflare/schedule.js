export const REPO = "tongxiaooppo-boop/tw-hold";
export const REF = "main";

function range(a, b) {
  const out = [];
  for (let i = a; i <= b; i++) out.push(i);
  return out;
}

// 時間一律台北時間 "HH:MM"；weekdays 用 JS getUTCDay 編號（0=週日…6=週六），null=不限；days＝每月幾號，null=不限
export const SCHEDULE = [
  { workflow: "global_macro.yml",      times: ["05:17", "06:17", "07:13"],          weekdays: [2,3,4,5,6], days: null },
  { workflow: "chip_flow_evening.yml", times: ["15:23", "16:43"],                   weekdays: [1,2,3,4,5], days: null },
  { workflow: "openapi_daily.yml",     times: ["16:07", "18:07", "20:07", "23:07"], weekdays: [1,2,3,4,5], days: null },
  { workflow: "openapi_daily.yml",     times: ["04:07"],                            weekdays: [2,3,4,5,6], days: null },
  { workflow: "heartbeat.yml",         times: ["08:23"],                            weekdays: [1,2,3,4,5], days: null },
  { workflow: "revenue_watch.yml",     times: ["18:47", "21:43", "23:23"],          weekdays: null, days: range(1, 17) },
  { workflow: "revenue_watch.yml",     times: ["07:47"],                            weekdays: null, days: range(2, 18) },
];

const pad = (n) => String(n).padStart(2, "0");

// 把 UTC 的 Date 轉成台北（固定 +8，台灣沒有夏令時間）
export function taipeiParts(date) {
  const d = new Date(date.getTime() + 8 * 3600 * 1000);
  return {
    hhmm: `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`,
    weekday: d.getUTCDay(),
    day: d.getUTCDate(),
  };
}

// 該時刻（只看到分鐘）要 dispatch 的 workflow 檔名，依 SCHEDULE 順序、去重
export function dueWorkflows(date) {
  const { hhmm, weekday, day } = taipeiParts(date);
  const out = [];
  for (const e of SCHEDULE) {
    if (!e.times.includes(hhmm)) continue;
    if (e.weekdays && !e.weekdays.includes(weekday)) continue;
    if (e.days && !e.days.includes(day)) continue;
    if (!out.includes(e.workflow)) out.push(e.workflow);
  }
  return out;
}

// SCHEDULE 裡出現過的所有分鐘值，去重、由小到大
export function cronMinutes() {
  const set = new Set();
  for (const e of SCHEDULE) for (const t of e.times) set.add(Number(t.split(":")[1]));
  return [...set].sort((a, b) => a - b);
}
