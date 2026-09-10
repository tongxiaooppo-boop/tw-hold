"""主動式 ETF 認養旗標 → `data/derived/active_etf_flags.json`（Streamlit app 只讀這裡）。

## 這是什麼

規模前五大「主動式 ETF」（統一 00981A/00403A、復華 00991A、群益 00982A/00992A）
**前後兩個交易日 PCF 持股的差分**，攤成一個 per-ticker 旗標，給長波段候選池、短線頁、
個股查詢、多軌體檢當 **context flag**——**不 gate 任何進出場 / verdict / 排名**。

## 資料流

`scripts/snapshot_pcf.py`（rebuild.yml 每天跑）抓各投信官網每日揭露 PCF →
落 `data/pcf/<code>/<date>.parquet`。這支讀每檔最近兩份快照做差分。

- **方向看權重變化**（`d_weight`），不看原始股數差——這樣申購/贖回造成的整體等比縮放
  不會被誤判成加碼/調節（申贖時各檔權重大致不動）。`net_shares`（原始股數差）仍照舊
  輸出給卡片顯示。門檻 `EPS_W`＝0.03pp。
- 新進成分股 → 視為加碼；完全出清 → 視為調節（權重差夠大，自然被 EPS 抓到）。

## ⚠️ 界線（一定要標在頁面上）

**非官方三大法人／投信買賣超，非機構認養背書。** 是「主動式 ETF 發行商」的持股差分，
申贖也會動到（雖然已用權重法濾掉大部分）。永不 gate。

## 降級

- 某檔只有 1 份快照（首次上線 / 抓失敗）→ 該檔不貢獻，計入 `stale_etfs`。
- 全部都只有 1 份 → `flags` 空、`anchor_date` None → app 端整組隱藏。
- `anchor_date` 落後今天 > 4 天 → app 端整組隱藏。

用法：
    python build_active_etf_flags.py
    python build_active_etf_flags.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pandas as pd                                             # noqa: E402

from scripts.pcf_fetchers import FUNDS                          # noqa: E402

PCF_DIR = REPO / "data" / "pcf"
OUT = REPO / "data" / "derived" / "active_etf_flags.json"

EPS_W = 0.03            # 主動買賣的權重當量門檻（百分點）——低於此視為沒動作
REL_EPS = 0.03          # 沒有 nav/price 時的退路：主動股數差 / 部位 ≥ 3%
CONSENSUS_MIN = 2       # |buyers - sellers| ≥ 此值 → consensus_buy / consensus_sell
SOURCE = "自建 PCF（統一／復華／群益官網每日揭露）"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _kind(net_shares, consensus: int) -> str:
    if consensus >= CONSENSUS_MIN:
        return "consensus_buy"
    if consensus <= -CONSENSUS_MIN:
        return "consensus_sell"
    if net_shares and net_shares > 0:
        return "buy"
    if net_shares and net_shares < 0:
        return "sell"
    return "neutral"


def _latest_two(code: str) -> list[tuple[str, pd.DataFrame]]:
    d = PCF_DIR / code
    if not d.is_dir():
        return []
    snaps = sorted(d.glob("20*.parquet"))[-2:]
    return [(p.stem, pd.read_parquet(p)) for p in snaps]


def _scalar(df: pd.DataFrame, col: str):
    if col not in df.columns or df.empty:
        return None
    v = df[col].iloc[0]
    return None if pd.isna(v) else float(v)


def _fund_moves(today: pd.DataFrame, prev: pd.DataFrame) -> pd.DataFrame:
    """回 per-stock：d_shares（已還原申贖流量的主動股數差）/ direction / price。

    申贖（受益權單位數變動）會等比縮放所有持股 → 用 flow = units_T / units_prev
    把前一日股數放大到「若無主動交易時的預期值」，再跟今日相減。方向用主動股數差
    的權重當量（|active_d| × price / nav），對申贖與市值漂移都免疫。
    """
    t = today.set_index("stock_code")
    p = prev.set_index("stock_code")
    codes = t.index.union(p.index)

    u_t, u_p = _scalar(today, "fund_units"), _scalar(prev, "fund_units")
    nav_t = _scalar(today, "fund_nav")
    flow = (u_t / u_p) if (u_t and u_p and u_p > 0) else 1.0

    sh_t = t["shares"].reindex(codes).fillna(0.0)
    sh_p = p["shares"].reindex(codes).fillna(0.0)
    base = sh_p * flow                                   # 無主動交易時的預期今日股數
    active_d = sh_t - base

    price = t["price"].reindex(codes)
    price = price.fillna((t["market_value"] / t["shares"]).reindex(codes))
    price = price.fillna(p["price"].reindex(codes))           # 出清的個股用前一日價

    out = pd.DataFrame(index=codes)
    out["stock_name"] = t["stock_name"].reindex(codes).fillna(p["stock_name"].reindex(codes))
    out["d_shares"] = active_d
    out["price"] = price
    if nav_t and nav_t > 0:
        wt_eq = (active_d * price.fillna(0)).abs() / nav_t * 100
        out["direction"] = 0
        out.loc[(active_d > 0) & (wt_eq >= EPS_W), "direction"] = 1
        out.loc[(active_d < 0) & (wt_eq >= EPS_W), "direction"] = -1
    else:                                                # 沒 nav → 用相對部位比例
        rel = active_d / base.where(base > 0)
        out["direction"] = 0
        out.loc[(base <= 0) & (sh_t > 0), "direction"] = 1          # 新進
        out.loc[(sh_t <= 0) & (base > 0), "direction"] = -1         # 出清
        out.loc[rel >= REL_EPS, "direction"] = 1
        out.loc[rel <= -REL_EPS, "direction"] = -1
    return out.reset_index(names="stock_code")


def build_flags(snaps: dict[str, list[tuple[str, pd.DataFrame]]],
                meta: dict[str, dict] | None = None) -> dict:
    """`snaps`：{code: [(date, df), ...]}（每檔最多 2 份，時間升冪）。
    `meta`：{code: {"issuer","name"}}，缺就從 FUNDS 補。"""
    meta = meta or {f["code"]: f for f in FUNDS}
    total = len(snaps) or len(FUNDS)

    per_stock: dict[str, dict] = {}
    synced, anchor = 0, ""
    fund_detail: dict[str, dict] = {}

    for code, hist in snaps.items():
        if len(hist) < 2:
            fund_detail[code] = {"synced": False,
                                 "date": hist[-1][0] if hist else None, "moved_n": 0}
            continue
        (pd_date, prev), (td_date, today) = hist[-2], hist[-1]
        if td_date <= pd_date:                               # 同日 / 或抓到更舊的
            fund_detail[code] = {"synced": False, "date": td_date, "moved_n": 0}
            continue
        synced += 1
        anchor = max(anchor, td_date)
        mv = _fund_moves(today, prev)
        moved = int((mv["direction"] != 0).sum())
        fund_detail[code] = {"synced": True, "date": td_date, "prev_date": pd_date,
                             "moved_n": moved}

        for r in mv.itertuples(index=False):
            if r.direction == 0 and not r.d_shares:
                continue
            s = per_stock.setdefault(r.stock_code, {
                "name": r.stock_name, "net_shares": 0.0, "net_amount": 0.0,
                "_amt_ok": True, "buyers": [], "sellers": []})
            s["net_shares"] += float(r.d_shares)
            if r.price and pd.notna(r.price):
                s["net_amount"] += float(r.d_shares) * float(r.price)
            else:
                s["_amt_ok"] = False
            if r.direction > 0:
                s["buyers"].append(code)
            elif r.direction < 0:
                s["sellers"].append(code)

    flags: dict[str, dict] = {}
    for sc, s in per_stock.items():
        buyers, sellers = sorted(s["buyers"]), sorted(s["sellers"])
        consensus = len(buyers) - len(sellers)
        if not buyers and not sellers:
            continue
        strong = (len(buyers) >= CONSENSUS_MIN and not sellers) or \
                 (len(sellers) >= CONSENSUS_MIN and not buyers)
        ns = round(s["net_shares"])
        flags[sc] = {
            "name": s["name"],
            "industry": None,                    # PCF 沒產業別；app 端容忍 None
            "net_shares": ns,
            "net_amount": round(s["net_amount"]) if s["_amt_ok"] else None,
            "issuer_count": len(buyers) + len(sellers),
            "consensus": consensus,
            "consensus_strong": bool(strong),
            "buyers": buyers,
            "sellers": sellers,
            "kind": _kind(ns, consensus),
        }

    return {
        "_meta": {
            "source": SOURCE,
            "anchor_date": anchor or None,
            "market_date": anchor or None,
            "fetched_at": _now_iso(),
            "total_etfs": total,
            "synced_etfs": synced,
            "stale_etfs": total - synced,
            "funds": fund_detail,
            "schema_ok": True,
        },
        "flags": flags,
    }


def _empty(reason: str) -> dict:
    return {"_meta": {"source": SOURCE, "schema_ok": False, "fetched_at": _now_iso(),
                      "error": reason}, "flags": {}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    snaps = {f["code"]: _latest_two(f["code"]) for f in FUNDS}
    try:
        payload = build_flags(snaps)
    except Exception as e:                                      # noqa: BLE001
        if OUT.exists():
            print(f"::warning::主動式 ETF 旗標計算失敗（{type(e).__name__}: {e}）——沿用上次成功值")
            return 0
        payload = _empty(f"{type(e).__name__}: {e}")

    m = payload["_meta"]
    print(f"anchor={m.get('anchor_date')}　synced={m.get('synced_etfs')}/{m.get('total_etfs')}"
          f"　flags={len(payload['flags'])} 檔")
    for c, fd in (m.get("funds") or {}).items():
        print(f"  {c}: {'✓' if fd.get('synced') else '·'} {fd.get('date')} "
              f"(prev {fd.get('prev_date', '—')}) 動 {fd.get('moved_n', 0)} 檔")

    if args.dry_run:
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
