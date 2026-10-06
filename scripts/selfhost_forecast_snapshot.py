"""存「除權除息預告表」快照（證交所 TWT48U）——量測預告提前多久、預掛下一週的還原參數用。

TWT48U 只有未來事件、沒有歷史，所以每次存一份當天快照，累積後才知道各類事件實際預告提前幾天。
- **來源順序：OpenAPI `TWT48U_ALL`（官方開放授權，OGDL）→ 失敗才退回網站端點 `rwd/zh/exRight/TWT48U`。**
  2026-10-06 實測兩者內容完全相同（62 件、(代號,日期) 集合一致、配股率／現增配股率／認購價／現金股利全部相同；
  網站版的「待公告」＝OpenAPI 的空字串）。OpenAPI 多 4 個欄位（SharesOffered 等，只有現增事件有值），目前不存。
- 官方請求：每次執行 1 次（每週一次的收集時順便跑，不增加頻率）。
- 輸出：data/selfhost/forecast_twt48u.jsonl（累積檔：一次抓取一列＝{_fetched, source, rows}；同抓取日重跑取代該列、只增不減）。
  舊格式（`fields`／`data`，網站版原樣）讀取時自動轉成同一種 rows。
  放進 Release `selfhost-data`（selfhost_collect.yml 每週下載→補一列→上傳）。
- rows 欄位：code、name、ex（除權除息日，ISO）、kind（權／息／權息）、stock_ratio（無償配股率）、sub_ratio（現增配股率）、
  sub_price（認購價）、cash（現金股利；「待公告」＝None，ETF 常見）。

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
URL_OPENAPI = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"
URL_WEB = "https://www.twse.com.tw/rwd/zh/exRight/TWT48U?response=json"
UA = {"User-Agent": "Mozilla/5.0"}


def _roc_web(s: str) -> str:
    s = s.replace("年", "/").replace("月", "/").replace("日", "")
    y, m, d = s.split("/")
    return pd.Timestamp(int(y) + 1911, int(m), int(d)).date().isoformat()


def _roc7(s: str) -> str:
    s = str(s).strip()
    return pd.Timestamp(int(s[:-4]) + 1911, int(s[-4:-2]), int(s[-2:])).date().isoformat()


def _num(x):
    """空字串（OpenAPI）／文字（網站版「待公告」）→ None；數字字串 → float。"""
    x = str(x).strip()
    if x == "":
        return None
    try:
        return float(x)
    except ValueError:
        return None


def normalize_openapi(j: list[dict]) -> list[dict]:
    return [{"code": r["Code"], "name": r.get("Name", ""), "ex": _roc7(r["Date"]), "kind": r.get("Exdividend", ""),
             "stock_ratio": _num(r.get("StockDividendRatio")), "sub_ratio": _num(r.get("SubscriptionRatio")),
             "sub_price": _num(r.get("SubscriptionPricePerShare")), "cash": _num(r.get("CashDividend"))} for r in j]


def normalize_web(fields: list[str], data: list[list]) -> list[dict]:
    i = {k: fields.index(k) for k in ("除權除息日期", "股票代號", "名稱", "除權息", "無償配股率", "現金增資配股率", "現金增資認購價", "現金股利")}
    return [{"code": r[i["股票代號"]], "name": r[i["名稱"]], "ex": _roc_web(r[i["除權除息日期"]]), "kind": r[i["除權息"]],
             "stock_ratio": _num(r[i["無償配股率"]]), "sub_ratio": _num(r[i["現金增資配股率"]]),
             "sub_price": _num(r[i["現金增資認購價"]]), "cash": _num(r[i["現金股利"]])} for r in data]


def fetch() -> tuple[str, list[dict]]:
    """OpenAPI 優先；失敗（連線、非 JSON、0 筆）才退回網站端點。回 (來源, rows)。"""
    try:
        r = requests.get(URL_OPENAPI, headers=UA, timeout=60)
        r.raise_for_status()
        rows = normalize_openapi(r.json())
        if rows:
            return "openapi", rows
        print("[forecast] OpenAPI 回 0 筆，改用網站端點")
    except Exception as e:  # noqa: BLE001
        print(f"[forecast] OpenAPI 失敗（{type(e).__name__}: {e}），改用網站端點")
    r = requests.get(URL_WEB, headers=UA, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("stat") != "OK" or not j.get("data"):
        raise RuntimeError(f"TWT48U 回應異常：stat={j.get('stat')} rows={len(j.get('data') or [])}")
    return "web", normalize_web(j["fields"], j["data"])


def _upgrade(rec: dict) -> dict:
    """舊格式（fields／data）轉成 rows。"""
    if "rows" in rec:
        return rec
    return {"_fetched": rec["_fetched"], "source": "web", "rows": normalize_web(rec["fields"], rec["data"])}


def load() -> list[dict]:
    if not OUT.exists():
        return []
    return [_upgrade(json.loads(x)) for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()]


def save(rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: r["_fetched"])
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def summarize(rec: dict) -> pd.DataFrame:
    rec = _upgrade(rec)
    d = pd.DataFrame(rec["rows"])
    d["ex"] = pd.to_datetime(d["ex"])
    d["lead_days"] = (d["ex"] - pd.Timestamp(rec["_fetched"])).dt.days
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true", help="只印現有快照的提前天數分布")
    a = ap.parse_args(argv)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    recs = load()
    if not a.summary:
        src, rows = fetch()
        rec = {"_fetched": date.today().isoformat(), "source": src, "rows": rows}
        n0 = len(recs)
        recs = [r for r in recs if r["_fetched"] != rec["_fetched"]] + [rec]
        assert len(recs) >= n0, "累積檔不得變少"
        save(recs)
        print(f"[forecast] 已存 {rec['_fetched']}（{src}）：{len(rows)} 件（累積 {len(recs)} 份）")
    for r in recs:
        d = summarize(r)
        print(f"{r['_fetched']}（{r.get('source', 'web')}）：{len(d)} 件；除權息日距抓取日 {d['lead_days'].min()}～{d['lead_days'].max()} 天；"
              f"≤7 天 {int((d['lead_days'] <= 7).sum())} 件；現金股利待公告 {int(d['cash'].isna().sum())} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
