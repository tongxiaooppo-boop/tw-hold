"""台指選擇權 Put/Call Ratio——市場情緒/避險程度的領先指標，跟台指期夜盤收盤是
互補資訊（一個是「價」、一個是「還沒發生但市場在防的方向」）。

## 資料源

TAIFEX 官方 OpenAPI `https://openapi.taifex.com.tw/v1/PutCallRatio`——免金鑰、
免登入，JSON。跟 `fetch_tx_futures.py` 用的 `DailyMarketReportFut` 不一樣的是，
**這支自帶約 21 個交易日的歷史**（不是只有最新一天），所以第一次跑就有一個月
份可看，之後每天呼叫會自然疊上新的一天、也會重疊蓋掉舊的（用 date 去重、
keep last，跟 `fetch_global_macro.py` 的精神一致：新抓到的贏）。

欄位：`PutVolume`/`CallVolume`/`PutCallVolumeRatio%`（成交量比）、
`PutOI`/`CallOI`/`PutCallOIRatio%`（未平倉比）。Ratio 是「Put/Call ×100」，
例如 107.09 代表 Put 量是 Call 量的 1.0709 倍——>100 偏防守（怕跌買 Put 的比
買 Call 的多）、<100 偏樂觀，數字本身沒有官方「多空分界線」，趨勢比單點有意義。

## 排程

掛在 `global_macro.yml` 同一個 job——這支資料是選擇權「盤中」成交量+未平倉
統計（不分日盤夜盤本身這個概念，是整天的量），收盤後就定案，06:00 抓絕對
夠新。

用法：
    python scripts/fetch_put_call_ratio.py
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pandas as pd

URL = "https://openapi.taifex.com.tw/v1/PutCallRatio"
OUT = Path(__file__).resolve().parents[1] / "data" / "reference" / "put_call_ratio.parquet"

#: TAIFEX 原始欄位 -> 內部欄名（snake_case，跟其他 reference 模組一致）。
_FIELDS = {
    "PutVolume": "put_volume", "CallVolume": "call_volume",
    "PutCallVolumeRatio%": "put_call_volume_ratio",
    "PutOI": "put_oi", "CallOI": "call_oi",
    "PutCallOIRatio%": "put_call_oi_ratio",
}


def fetch() -> pd.DataFrame:
    with urllib.request.urlopen(URL, timeout=20) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    records = []
    for r in rows:
        rec = {"date": pd.Timestamp(r["Date"])}
        for src, dst in _FIELDS.items():
            v = r.get(src, "")
            rec[dst] = float(v) if v not in ("", "-", "NULL", None) else None
        records.append(rec)
    return pd.DataFrame.from_records(records).sort_values("date").reset_index(drop=True)


def main() -> None:
    new = fetch()
    if new.empty:
        print("⚠️ 沒抓到資料（TAIFEX 還沒更新或格式改了）")
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        old = pd.read_parquet(OUT)
        combined = pd.concat([old, new], ignore_index=True).drop_duplicates(
            subset=["date"], keep="last")
    else:
        combined = new
    combined = combined.sort_values("date").reset_index(drop=True)
    combined.to_parquet(OUT, index=False)

    last = combined.iloc[-1]
    print(f"  {last['date'].date()}　量比 {last['put_call_volume_ratio']:.2f}%"
          f"　未平倉比 {last['put_call_oi_ratio']:.2f}%")
    print(f"寫入 {OUT}：累積 {len(combined)} 筆（這次抓到 {len(new)} 天，{new['date'].min().date()}"
          f" ~ {new['date'].max().date()}）")


if __name__ == "__main__":
    main()
