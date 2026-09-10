"""主動式 ETF 認養旗標 → `data/derived/active_etf_flags.json`（Streamlit app 只讀這裡）。

## 這是什麼

近一日「主動式 ETF」對個股的加碼／調節，攤成一個 per-ticker 旗標，給長波段候選池、
短線頁、個股查詢、多軌體檢的卡片／檢核表當 **context flag**——**不 gate 任何進出場**。

## 資料源：`etfinfo.tw`（第三方彙總，非官方）

`GET https://www.etfinfo.tw/api/active/summary`（~220KB JSON、免登入、帶 Referer/UA）。
用其中兩塊：
  - `flowRankings[]`：個股當日淨變動（netShares / netAmount / issuerCount / etfDetails）
  - `consensusSignals[]`：多檔主動 ETF 同向（buyers / sellers / netSignal / isStrong）

⚠️ **這不是官方三大法人／投信買賣超**，是「主動式 ETF 發行商」的 PCF 減法彙總，
且 etfinfo 有付費牆層、每次約 1/3 主動 ETF 尚未更新（`syncStatus.staleEtfs`）。
所以：抓不到 → 保留上次成功值、`::warning::`、**不讓 rebuild 變紅**；
過期（anchor 落後 > STALE_DAYS 交易日）或 schema 壞 → app 端整個隱藏旗標。

未來計畫：自建 PCF 上游（`docs/PLAN.md` Backlog）。

用法：
    python build_active_etf_flags.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DERIVED = Path(__file__).resolve().parent / "data" / "derived"
OUT = DERIVED / "active_etf_flags.json"

SUMMARY_URL = "https://www.etfinfo.tw/api/active/summary"
STALE_DAYS = 4                    # anchor 落後今天超過這麼多「天」→ app 端視為過期
CONSENSUS_MIN = 2                 # |netSignal| ≥ 此值 → 標為 consensus_buy / consensus_sell


def _taipei_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(timezone.utc)  # 存 UTC ISO，app 端不需要換算


def _fetch() -> dict:
    req = urllib.request.Request(SUMMARY_URL, headers={
        "User-Agent": "tw-hold-rebuild (+https://github.com/tongxiaooppo-boop/tw-hold)",
        "Referer": "https://www.etfinfo.tw/active",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def _check_schema(s: dict) -> None:
    """形狀不對就拋——呼叫端接住、保留上次成功值。"""
    if not isinstance(s, dict):
        raise ValueError("summary 不是 dict")
    for k in ("flowRankings", "consensusSignals", "anchorDate"):
        if k not in s:
            raise ValueError(f"summary 缺 {k}")
    if not isinstance(s["flowRankings"], list) or not isinstance(s["consensusSignals"], list):
        raise ValueError("flowRankings / consensusSignals 不是 list")
    if s["flowRankings"]:
        r0 = s["flowRankings"][0]
        for k in ("stockCode", "netShares", "issuerCount"):
            if k not in r0:
                raise ValueError(f"flowRankings 列缺 {k}")


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


def build(summary: dict) -> dict:
    _check_schema(summary)
    sync = summary.get("syncStatus") or {}
    anchor = summary.get("anchorDate")
    market = summary.get("latestMarketDate") or anchor

    cons = {c["stockCode"]: c for c in summary["consensusSignals"] if c.get("stockCode")}
    flags: dict[str, dict] = {}

    for r in summary["flowRankings"]:
        code = str(r.get("stockCode") or "").strip()
        if not code:
            continue
        c = cons.get(code, {})
        net_shares = r.get("netShares")
        consensus = int(c.get("netSignal") or 0)
        flags[code] = {
            "name": r.get("stockName"),
            "industry": r.get("industry"),
            "net_shares": net_shares,               # 淨張數（負 = 淨賣）
            "net_amount": r.get("netAmount"),
            "issuer_count": r.get("issuerCount"),
            "consensus": consensus,                  # +N 檔淨買 / -N 檔淨賣（來自 consensusSignals）
            "consensus_strong": bool(c.get("isStrong")),
            "buyers": c.get("buyers") or [],
            "sellers": c.get("sellers") or [],
            "kind": _kind(net_shares, consensus),
        }

    # consensusSignals 偶爾有 flowRankings 沒收錄的（例如買賣互抵、淨額小但共識強）
    for code, c in cons.items():
        if code in flags:
            continue
        consensus = int(c.get("netSignal") or 0)
        flags[code] = {
            "name": c.get("stockName"), "industry": None,
            "net_shares": None, "net_amount": None, "issuer_count": None,
            "consensus": consensus, "consensus_strong": bool(c.get("isStrong")),
            "buyers": c.get("buyers") or [], "sellers": c.get("sellers") or [],
            "kind": _kind(None, consensus),
        }

    return {
        "_meta": {
            "source": "etfinfo.tw",
            "endpoint": "/api/active/summary",
            "anchor_date": anchor,
            "market_date": market,
            "fetched_at": _taipei_now().isoformat(timespec="seconds"),
            "total_etfs": sync.get("totalEtfs"),
            "synced_etfs": sync.get("syncedEtfs"),
            "stale_etfs": sync.get("staleEtfs"),
            "schema_ok": True,
        },
        "flags": flags,
    }


def main() -> int:
    DERIVED.mkdir(parents=True, exist_ok=True)
    try:
        payload = build(_fetch())
    except Exception as e:  # noqa: BLE001  網路 / JSON / schema 都走這
        if OUT.exists():
            print(f"::warning::主動式 ETF 旗標抓取失敗（{type(e).__name__}: {e}）——沿用上次成功的 {OUT.name}")
            return 0
        OUT.write_text(json.dumps(
            {"_meta": {"source": "etfinfo.tw", "schema_ok": False,
                       "fetched_at": _taipei_now().isoformat(timespec="seconds"),
                       "error": f"{type(e).__name__}: {e}"},
             "flags": {}}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"::warning::主動式 ETF 旗標抓取失敗且無舊檔——寫入 schema_ok:false 空殼")
        return 0

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    m = payload["_meta"]
    print(f"-> {OUT}　（{len(payload['flags'])} 檔；anchor {m['anchor_date']}；"
          f"{m['stale_etfs']}/{m['total_etfs']} 檔 ETF 未更新）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
