"""自建事件表 → 股數變動事件 → `reference/corporate_actions_resolved.json`（v2）。

為什麼改（2026-10-30）：舊版靠 bundle 價格跳空偵測再去 FinMind 查 factor；tw-swing
2026-10-13 改吃自建包（價格已還原、沒有跳空）之後**永遠抓不到新事件**，配股（除權）
本來也不在範圍——6669 2026-09-02 配股 ×2.98 就是這樣漏掉的。現在直接讀自建事件表
`data/selfhost/corp_actions.parquet`（rebuild.yml 從 tw-hold-data Release 下載）。

股數比 m（新股數 ÷ 舊股數）怎麼算：
  - split / par_change：m ＝ 前收 ÷ 參考價（吸附整數／半整數）；
  - cap_reduction 彌補虧損：m ＝ 前收 ÷ 參考價（< 1）；
    現金減資（退還股款）：m ＝ None——IAS 33.29 不追溯調整、財報 EPS 也不重編，
    只留 pf 給價格還原；
  - ex_rights / ex_both：m ＝ 1 ＋ 無償配股（每千股）÷ 1000。**不能用前收 ÷ 參考價**：
    除權還包含現金增資（股東掏錢認購，財報不追溯），也混著現金股利。
    無償配股率：上櫃在事件 detail 裡；上市要打 TWT49UDetail（本機回填檔
    `ev_twse_ca_detail.parquet` ＋ 這份 json 的 `twse_bonus` 快取，只打還沒查過的）。
pf（價格比）＝ 前收 ÷ 參考價，只給 split / par_change / cap_reduction。

讀不到事件表 → 不動既有 json（exit 0，CI 不因這支變紅）。`--write` 才落檔。

用法：
    python scripts/resolve_splits.py                     # 只看差異
    python scripts/resolve_splits.py --write             # 落檔（rebuild.yml 用這個）
    python scripts/resolve_splits.py --corp-actions PATH --max-fetch 0
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from reference import corporate_actions as ca                      # noqa: E402

RESOLVED = REPO / "reference" / "corporate_actions_resolved.json"
SH = REPO / "data" / "selfhost"
CORP = SH / "corp_actions.parquet"
TWSE_DETAIL = SH / "ev_twse_ca_detail.parquet"

#: 減資原因：這些是「不退錢」→ 財報追溯調整
NONCASH_REDUCTION = {"彌補虧損", "Making up losses"}
CASH_REDUCTION = {"退還股款", "現金減資", "Cash refund"}
#: 同一 (ticker, date, type) 多個來源時的優先序（官方先）
SRC_RANK = {"twse_ex": 0, "tpex_ex": 0, "twse_par": 0, "tpex_par": 0, "twse_red": 0,
            "tpex_red": 0, "fm_split": 1, "fm_par": 1, "fm_reduction": 1}


def _nice(f: float) -> float:
    """7.001 → 7、2.0 → 2、0.5003 → 0.5：靠整數/簡分數 0.5% 內就吸附。"""
    for cand in (round(f), round(f * 2) / 2):
        if cand and abs(f / cand - 1) < 0.005:
            return cand
    return round(f, 6)


def _key(tk: str, d) -> str:
    return f"{tk}:{pd.Timestamp(d).date()}"


def _tpex_bonus(detail: str):
    try:
        v = json.loads(detail or "{}").get("stock_div_per_1000")
        return float(v) if v not in (None, "") else None
    except Exception:
        return None


def build_events(corp: pd.DataFrame, twse_bonus: dict[str, float]) -> tuple[dict, list[str]]:
    """純函式：事件表 + 上市配股率查表 → (`{ticker: [event...]}`, 缺配股率的 key 清單)。

    event＝`{date, type, m, pf, src}`（m/pf 可能是 None），每檔依日期排序。
    """
    c = corp.copy()
    c["date"] = pd.to_datetime(c["date"])
    c["rank"] = c["source"].map(SRC_RANK).fillna(9)
    c = (c.sort_values(["ticker", "date", "type", "rank"])
          .drop_duplicates(["ticker", "date", "type"], keep="first"))
    out: dict[str, list[dict]] = {}
    missing: list[str] = []
    for r in c.itertuples(index=False):
        tk, typ = str(r.ticker), r.type
        pre, ref = float(r.prev_close or 0), float(r.ref_price or 0)
        ratio = pre / ref if (pre > 0 and ref > 0) else None
        m = pf = None
        if typ in ("split", "par_change"):
            if ratio is None:
                continue
            m = pf = _nice(ratio)
        elif typ == "cap_reduction":
            if ratio is None:
                continue
            pf = round(ratio, 6)
            reason = str(getattr(r, "reason", "") or "")
            m = pf if reason in NONCASH_REDUCTION else None
        elif typ in ("ex_rights", "ex_both"):
            if r.source == "tpex_ex":
                b = _tpex_bonus(r.detail)
            else:
                b = twse_bonus.get(_key(tk, r.date))
                if b is None:
                    missing.append(_key(tk, r.date))
                    continue
            if not b or b <= 0:
                continue                       # 純現增／只有息
            m = round(1.0 + b / 1000.0, 6)
        else:
            continue
        if m is not None and not (0.01 < m < 100):
            continue
        out.setdefault(tk, []).append({"date": str(r.date.date()), "type": typ,
                                       "m": m, "pf": pf, "src": r.source})
    return out, missing


def _fetch_twse(keys: list[str], cap: int) -> dict[str, float]:
    if cap <= 0 or not keys:
        return {}
    import requests
    from selfhost_twse_ca_detail import fetch
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    got = {}
    for k in keys[:cap]:
        tk, d = k.split(":")
        r = fetch(tk, pd.Timestamp(d), s)
        if r is not None:
            got[k] = float(r["bonus_per_1000"])
        time.sleep(0.6)
    return got


def _diff(old: dict, new: dict) -> list[str]:
    lines = []
    for tk in sorted(set(old) | set(new)):
        a = {(e["date"], e.get("type")): e for e in old.get(tk, [])}
        b = {(e["date"], e.get("type")): e for e in new.get(tk, [])}
        for k in sorted(set(b) - set(a)):
            lines.append(f"+ {tk} {k[0]} {k[1]} m={b[k].get('m')} pf={b[k].get('pf')}")
        for k in sorted(set(a) - set(b)):
            lines.append(f"- {tk} {k[0]} {k[1]}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--corp-actions", default=str(CORP))
    ap.add_argument("--max-fetch", type=int, default=80,
                    help="這次最多打幾次 TWT49UDetail（上市配股率；查過的會進快取）")
    args = ap.parse_args(argv)

    cp = Path(args.corp_actions)
    if not cp.exists():
        print(f"::warning::找不到事件表 {cp}——股數事件表維持原樣（不更新）")
        return 0
    corp = pd.read_parquet(cp)
    old = json.loads(RESOLVED.read_text(encoding="utf-8")) if RESOLVED.exists() else {}
    cache = {k: float(v) for k, v in old.get("twse_bonus", {}).items()}
    if TWSE_DETAIL.exists():
        det = pd.read_parquet(TWSE_DETAIL, columns=["ticker", "date", "bonus_per_1000"])
        for r in det.itertuples(index=False):
            cache.setdefault(_key(str(r.ticker), r.date), float(r.bonus_per_1000 or 0))

    events, missing = build_events(corp, cache)
    if missing:
        got = _fetch_twse(sorted(missing, reverse=True), args.max_fetch)   # 新的先查
        cache.update(got)
        events, missing = build_events(corp, cache)
        print(f"TWT49UDetail：查 {len(got)} 筆；仍缺 {len(missing)} 筆（下次再查）")
        for k in missing[:20]:
            print(f"::warning::上市除權 {k} 還查不到無償配股率——這筆暫不調整每股數字")

    lines = _diff(old.get("events", {}), events)
    print(f"事件表 {cp.name}：{len(corp)} 列、最新 {pd.to_datetime(corp['date']).max().date()}；"
          f"股數事件 {sum(len(v) for v in events.values())} 筆（{len(events)} 檔）；"
          f"和既有差 {len(lines)} 筆")
    for ln in lines[:60]:
        print("  " + ln)
    # 大事件（|ln m| ≥ ln 1.5）自動加進來要出聲：每股 EPS／股利的基準會跟著變
    for ln in lines:
        if ln.startswith("+") and "m=None" not in ln:
            m = float(ln.split("m=")[1].split()[0])
            if abs(np.log(m)) >= np.log(1.5):
                print(f"::warning::新股數事件 {ln[2:]}——事件前的每股 EPS／股利會 ÷ m；"
                      "覺得錯就到 reference/corporate_actions.py 的 _MANUAL 蓋掉")

    if args.write and (lines or cache != {k: float(v) for k, v in old.get("twse_bonus", {}).items()}):
        RESOLVED.write_text(json.dumps({
            "version": 2,
            "_note": "scripts/resolve_splits.py 從 corp_actions.parquet 自動產出——手動改請改 "
                     "reference/corporate_actions.py 的 _MANUAL（同代號整檔覆蓋這裡）",
            "corp_actions_max_date": str(pd.to_datetime(corp["date"]).max().date()),
            "events": {tk: events[tk] for tk in sorted(events)},
            "twse_bonus": {k: cache[k] for k in sorted(cache)},
        }, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
        ca.reload()
        print(f"→ 寫入 {RESOLVED.relative_to(REPO)}")
    elif lines:
        print("（--write 才落檔）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
