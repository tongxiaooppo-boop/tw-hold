"""統一（00981A／00403A）PCF 快照日期修補：把標早一天的快照改回真實資料日、補回被覆蓋而消失的交易日。

## 為什麼
統一 ezmoney 的 GetPCF 有時回 ASP.NET `/Date(ms)/`（台北午夜 epoch），舊版 `_isodate` 用 UTC 取日期 → **少一天**
（週一變週日）。快照檔名與檔內 `data_date` 都用這個日期，所以 ①標早一天 ②後一天的內容蓋掉前一天（同檔名）→ 真實交易日消失。
2026-10-13 盤點：兩檔各 15 份快照約 10 份標早 1 天，各有 2～3 個真實交易日不見。修正在 `pcf_fetchers._isodate`；本腳本修補**既有資料**。

## 做法（不靠猜）
1. 統一 API 可以依「生效日」查歷史（`specificDate=true`；回應的 data_date＝前一個交易日、PostDate＝查詢日）。
   對每個平日查一次，**只收 `post_date == 查詢日` 的回應**（API 不保證回哪一天，不符就丟，免得再造出錯日期）。
   得到「真實資料日 → 完整持股」的對照表（truth）。
2. 每份既有快照用**持股內容**（每檔股票的股數逐檔相同）對回 truth 的真實日期——不是用檔名推算。對不到的原樣保留、列在報告裡。
3. 同一真實日有多份（標對的與標早一天的重複）→ 留一份（優先檔名已是真實日的；內容相同，欄位以留下的為準）。
4. 真實日在保留窗口內、卻沒有任何快照 → 用 API 內容補回（沒有收盤價欄位，`fund_close` 空 → 該日折溢價會被略過，安全）。
5. 每檔只留最近 `KEEP` 份（跟 `snapshot_pcf` 一致）。

預設**只印計畫、不寫檔**；`--apply` 才改 `data/pcf/`。要先 `refdata_sync.py pull --only pcf --strict`、事後 `push data/pcf`
（CI：`.github/workflows/pcf_repair.yml`，與 rebuild／pcf_retry 同一個 concurrency 群組，避免和每日抓取互蓋）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pandas as pd                                             # noqa: E402

from scripts import pcf_fetchers as pf                          # noqa: E402

PCF_DIR = REPO / "data" / "pcf"
TONGYI = {f["code"]: f["fund_id"] for f in pf.FUNDS if f["fetch"] == "tongyi"}


def holdings_key(df: pd.DataFrame) -> tuple:
    """持股內容指紋：(股票代號, 股數) 排序後的 tuple。同一天的 PCF 必然相同；不同交易日幾乎不可能全部相同。"""
    return tuple(sorted((str(c), float(s)) for c, s in zip(df["stock_code"], df["shares"])))


def fetch_truth(fund_id: str, since: date, until: date, fetch_day=None, sleep: float = 0.5) -> dict[str, dict]:
    """真實資料日 → 解析後的 PCF（`pf._parse_tongyi` 格式）。只收 post_date == 查詢日 的回應。"""
    fetch_day = fetch_day or _fetch_day_live()
    out: dict[str, dict] = {}
    d = since
    while d <= until:
        if d.weekday() < 5:
            got = None
            for _ in range(3):
                try:
                    got = fetch_day(fund_id, d)
                    break
                except Exception:                                # noqa: BLE001  網路／HTML 錯誤頁：重試
                    time.sleep(1.0)
            if got and got["holdings"] and got["post_date"] == d.isoformat():
                out[got["data_date"]] = got
            time.sleep(sleep)
        d += timedelta(days=1)
    return out


def _fetch_day_live():
    op = pf._tongyi_opener()

    def f(fund_id: str, d: date):
        body = json.dumps({"fundCode": fund_id, "date": pf._roc(datetime(d.year, d.month, d.day)),
                           "specificDate": True}).encode()
        req = urllib.request.Request(
            pf._EZ_BASE + "/ETF/Transaction/GetPCF", data=body, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8", "X-Requested-With": "XMLHttpRequest",
                     "Referer": pf._EZ_BASE + "/ETF/Transaction/PCF"})
        return pf._parse_tongyi(json.loads(op.open(req, timeout=30).read().decode("utf-8")), "")
    return f


def plan_fund(stored: dict[str, pd.DataFrame], truth: dict[str, dict], keep: int) -> dict:
    """純函式（好測）。`stored`：檔名日期 → DataFrame；回傳計畫：
    relabel{舊檔名→真實日}、drop[舊檔名]（重複）、fill[真實日]（補回）、unmatched[檔名]、keep_final[最後留下的日期]。"""
    by_key = {holdings_key(pd.DataFrame({"stock_code": [h["stock_code"] for h in t["holdings"]],
                                         "shares": [h["shares"] for h in t["holdings"]]})): d
              for d, t in truth.items()}
    match: dict[str, str | None] = {lab: by_key.get(holdings_key(df)) for lab, df in stored.items()}
    unmatched = sorted(l for l, t in match.items() if t is None)
    groups: dict[str, list[str]] = {}
    for lab, td in match.items():
        if td:
            groups.setdefault(td, []).append(lab)
    relabel, drop = {}, []
    for td, labs in groups.items():
        survivor = td if td in labs else sorted(labs)[0]
        for lab in labs:
            if lab == survivor:
                if lab != td:
                    relabel[lab] = td
            else:
                drop.append(lab)
    final = set(groups) | {l for l in unmatched}
    start = min(groups) if groups else None
    fill = sorted(d for d in truth if start and d >= start and d not in groups)
    final |= set(fill)
    ordered = sorted(final)
    kept = ordered[-keep:]
    return {"relabel": relabel, "drop": sorted(drop), "fill": [d for d in fill if d in kept],
            "unmatched": unmatched, "keep_final": kept, "pruned": [d for d in ordered if d not in kept]}


def apply_fund(fund_dir: Path, stored: dict[str, pd.DataFrame], truth: dict[str, dict], plan: dict) -> None:
    """兩階段：**先**刪掉所有被改標／重複的舊檔，**再**寫新檔。改標會連鎖（9/21→9/22、9/22→9/23…），
    邊改邊刪會把剛寫好的 9/22 當成「舊的 9/22」刪掉。內容都在 `stored` 記憶體裡，不會因先刪而遺失。"""
    from scripts.snapshot_pcf import _frame                       # noqa: PLC0415
    outputs: dict[str, pd.DataFrame] = {}
    for lab, td in plan["relabel"].items():
        df = stored[lab].copy()
        df["data_date"] = td
        outputs[td] = df
    for td in plan["fill"]:
        t = truth[td]
        outputs[td] = _frame({"holdings": t["holdings"], "nav": t.get("nav"), "units": t.get("units"),
                              "close": None, "close_date": None, "data_date": td})
    for lab in [*plan["relabel"], *plan["drop"]]:
        (fund_dir / f"{lab}.parquet").unlink()
    for td, df in outputs.items():
        df.to_parquet(fund_dir / f"{td}.parquet", index=False)
    keep = set(plan["keep_final"])
    for p in fund_dir.glob("20*.parquet"):
        if p.stem not in keep:
            p.unlink()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的改 data/pcf/（預設只印計畫）")
    ap.add_argument("--pcf-dir", default=str(PCF_DIR))
    ap.add_argument("--funds", default=",".join(TONGYI))
    a = ap.parse_args(argv)
    from scripts.snapshot_pcf import KEEP                           # noqa: PLC0415
    pcf_dir = Path(a.pcf_dir)
    idx_path = pcf_dir / "_index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    today = datetime.now(timezone(timedelta(hours=8))).date()
    changed = False
    for code in [c for c in a.funds.split(",") if c]:
        fund_dir = pcf_dir / code
        files = sorted(fund_dir.glob("20*.parquet"))
        if not files:
            print(f"{code}：沒有快照，略過")
            continue
        stored = {p.stem: pd.read_parquet(p) for p in files}
        since = datetime.fromisoformat(min(stored)).date() - timedelta(days=4)
        truth = fetch_truth(TONGYI[code], since, today + timedelta(days=1))
        print(f"\n== {code}：既有 {len(stored)} 份，API 查到 {len(truth)} 個真實交易日")
        if len(truth) < 5:
            print("::error::API 查到的交易日太少，不做任何修補（網路／格式異常？）")
            return 1
        plan = plan_fund(stored, truth, KEEP)
        for lab in sorted(stored):
            td = next((t for t in [plan["relabel"].get(lab)] if t), None)
            tag = (f"改標 {lab} → {td}" if td else ("重複，刪除" if lab in plan["drop"] else
                                                    ("內容對不到 API，原樣保留" if lab in plan["unmatched"] else "標籤正確")))
            print(f"  {lab}：{tag}")
        print(f"  補回（API 內容，無收盤價）：{plan['fill']}；窗口外清掉：{plan['pruned']}")
        print(f"  修補後 {len(plan['keep_final'])} 份：{plan['keep_final']}")
        if a.apply:
            apply_fund(fund_dir, stored, truth, plan)
            if code in idx.get("funds", {}) and plan["keep_final"]:
                last = max(plan["keep_final"])
                idx["funds"][code]["latest_date"] = last
                if last in truth:
                    idx["funds"][code]["post_date"] = truth[last]["post_date"]
            changed = True
    if a.apply and changed:
        if idx:
            idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\n已寫入 data/pcf/。接著要：build_active_etf_flags.py → refdata_sync.py push data/pcf")
    elif not a.apply:
        print("\n（試算，沒有改任何檔案；加 --apply 才寫入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
