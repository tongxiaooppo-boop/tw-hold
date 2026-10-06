"""存「除權除息預告表」快照（證交所 TWT48U）——量測預告提前多久、預掛下一週的還原參數用。

TWT48U 只有未來事件、沒有歷史，所以每次存一份當天快照（原樣 JSON，附抓取日），累積後才知道各類事件實際預告提前幾天。
- 欄位：除權除息日期（民國）、除權息（權／息／權息）、無償配股率、現金增資配股率、現金增資認購價、現金股利。
- 官方請求：每次執行 1 次（每週一次的收集時順便跑，不增加頻率）。
- 輸出：data/selfhost/forecast_twt48u.jsonl（累積檔：一次抓取一列＝{_fetched, fields, data}；同抓取日重跑取代該列、只增不減）。
  放進 Release `selfhost-data`（selfhost_collect.yml 每週下載→補一列→上傳）。

用法：python scripts/selfhost_forecast_snapshot.py [--summary]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "selfhost" / "forecast_twt48u.jsonl"
URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT48U?response=json"
UA = {"User-Agent": "Mozilla/5.0"}


def _roc(s: str) -> pd.Timestamp:
    s = s.replace("年", "/").replace("月", "/").replace("日", "")
    y, m, d = s.split("/")
    return pd.Timestamp(int(y) + 1911, int(m), int(d))


def fetch() -> dict:
    r = requests.get(URL, headers=UA, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("stat") != "OK" or not j.get("data"):
        raise RuntimeError(f"TWT48U 回應異常：stat={j.get('stat')} rows={len(j.get('data') or [])}")
    return j


def load() -> list[dict]:
    if not OUT.exists():
        return []
    return [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()]


def save(rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: r["_fetched"])
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def summarize(j: dict) -> pd.DataFrame:
    asof = pd.Timestamp(j["_fetched"])
    f = j["fields"]
    rows = []
    for r in j["data"]:
        rows.append({"ticker": r[f.index("股票代號")], "ex": _roc(r[f.index("除權除息日期")]),
                     "kind": r[f.index("除權息")], "cash": r[f.index("現金股利")]})
    d = pd.DataFrame(rows)
    d["lead_days"] = (d["ex"] - asof).dt.days
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true", help="只印現有快照的提前天數分布")
    a = ap.parse_args(argv)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = load()
    if not a.summary:
        j = fetch()
        j = {"_fetched": date.today().isoformat(), "fields": j["fields"], "data": j["data"]}
        n0 = len(rows)
        rows = [r for r in rows if r["_fetched"] != j["_fetched"]] + [j]
        assert len(rows) >= n0, "累積檔不得變少"
        save(rows)
        print(f"[forecast] 已存 {j['_fetched']}：{len(j['data'])} 件（累積 {len(rows)} 份）")
    for r in rows:
        d = summarize(r)
        print(f"{r['_fetched']}：{len(d)} 件；除權息日距抓取日 {d['lead_days'].min()}～{d['lead_days'].max()} 天；"
              f"≤7 天 {int((d['lead_days'] <= 7).sum())} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
