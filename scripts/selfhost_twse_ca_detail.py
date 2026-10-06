"""TWSE 現金增資明細回填：對上市除權／除權息事件逐件打 TWT49UDetail（官方 rwd 端點）。

端點：https://www.twse.com.tw/rwd/zh/exRight/TWT49UDetail?response=json&STK_NO=<代號>&T1=<YYYYMMDD>
（openapi 版回 HTML、exchangeReport 版 404；欄位以此端點實測為準）
輸出 data/selfhost/ev_twse_ca_detail.parquet（可續跑，已抓過的跳過）。
"""
import re, sys, time, json
from pathlib import Path
import pandas as pd, requests

SH = Path(__file__).resolve().parent.parent / "data" / "selfhost"
OUT = SH / "ev_twse_ca_detail.parquet"
URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT49UDetail"


def _num(s):
    m = re.search(r"[\d,]+(?:\.\d+)?", s or "")
    return float(m.group(0).replace(",", "")) if m else 0.0


def fetch(tk, d, s):
    for _ in range(4):
        try:
            j = s.get(URL, params={"response": "json", "STK_NO": tk, "T1": d.strftime("%Y%m%d")}, timeout=25).json()
        except Exception:
            time.sleep(3); continue
        if j.get("stat") == "ok" and j.get("data"):
            r = j["data"][0]
            return {"cash_div": _num(r[2]), "bonus_per_1000": _num(r[4]), "ca_shares": _num(r[6]),
                    "ca_price": _num(r[7]), "ca_public": _num(r[8]), "ca_staff": _num(r[9]),
                    "ca_orig": _num(r[10]), "ca_per_1000": _num(r[11])}
        time.sleep(3)
    return None


def main():
    c = pd.read_parquet(SH / "corp_actions.parquet")
    t = c[(c.market == "TW") & c.event.isin(["除權", "除權息"])][["ticker", "date"]]
    done = pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame(columns=["ticker", "date"])
    if "ca_orig" not in done.columns:                       # 舊版沒存原股東認購股數：只重抓有現增的
        done = done[~(done.get("ca_shares", 0) > 0)]
    seen = set(zip(done.ticker, done.date))
    rows = done.to_dict("records")
    s = requests.Session()
    for i, (tk, d) in enumerate(zip(t.ticker, t.date)):
        if (tk, d) in seen:
            continue
        r = fetch(tk, d, s)
        rows.append({"ticker": tk, "date": d, **(r or {"cash_div": None})})
        time.sleep(0.6)
        if i % 100 == 0:
            pd.DataFrame(rows).to_parquet(OUT); print(i, len(t), flush=True)
    pd.DataFrame(rows).to_parquet(OUT)


if __name__ == "__main__":
    main()
