"""build_active_etf_flags.build_flags()——前後兩日 PCF 快照 → per-ticker 旗標。

守：方向看真實股數差、consensus 疊加、新進/出清、降級、schema。
"""
from __future__ import annotations

import sys

import pandas as pd
import pytest

sys.path.insert(0, ".")
import build_active_etf_flags as b  # noqa: E402


def _df(rows: list[tuple], nav=1_000_000.0, units=100_000.0, date="2026-09-09") -> pd.DataFrame:
    """rows: (code, name, shares, weight[, price]).  nav 預設大到權重當量門檻好過。"""
    recs = []
    for rr in rows:
        c, n, s, w = rr[:4]
        px = rr[4] if len(rr) > 4 else 10.0
        recs.append({"stock_code": c, "stock_name": n, "shares": float(s), "weight": float(w),
                     "market_value": float(s) * px, "price": float(px),
                     "fund_nav": nav, "fund_units": units, "data_date": date})
    return pd.DataFrame(recs)


def _snap(prev, today, d_prev="2026-09-08", d_today="2026-09-09",
          units_prev=100_000.0, units_today=100_000.0, nav=1_000_000.0):
    return [(d_prev, _df(prev, nav=nav, units=units_prev, date=d_prev)),
            (d_today, _df(today, nav=nav, units=units_today, date=d_today))]


def test_加碼_淨賣_不動():
    snaps = {"00981A": _snap(
        prev=[("2330", "台積電", 1000_000, 10.0), ("2454", "聯發科", 500_000, 8.0),
              ("3017", "奇鋐", 200_000, 5.0)],
        today=[("2330", "台積電", 1200_000, 11.0),   # 權重 +1.0 → 加碼
               ("2454", "聯發科", 400_000, 6.5),      # 權重 -1.5 → 調節
               ("3017", "奇鋐", 200_000, 5.01)])}     # +0.01 < EPS → 不動
    out = b.build_flags(snaps)
    f, m = out["flags"], out["_meta"]
    assert m["anchor_date"] == "2026-09-09" and m["synced_etfs"] == 1
    assert f["2330"]["kind"] == "buy" and f["2330"]["net_shares"] == 200_000
    assert f["2330"]["buyers"] == ["00981A"] and f["2330"]["issuer_count"] == 1
    assert f["2454"]["kind"] == "sell" and f["2454"]["net_shares"] == -100_000
    assert "3017" not in f                            # 沒動 → 不出現


def test_股數不動_即使申贖發生也不誤判():
    # 2026-09-11 迴歸測試：真實 00403A 案例——申贖造成受益權單位數 -1.1%，但
    # 股數完全沒動的持股（用 flow 修正會把它誤判成加碼，見 build_active_etf_flags
    # 模組 docstring）。修法＝不再用 fund_units 做流量調整，直接看真實股數差，
    # 股數沒動 → d_shares=0 → 天然不算動作，不因為申贖發生就被牽連。
    prev = [("2330", "台積電", 1000_000, 40.0), ("2454", "聯發科", 500_000, 30.0),
            ("2317", "鴻海", 300_000, 30.0)]
    today = prev                                          # 股數原封不動
    out = b.build_flags({"00981A": _snap(prev, today,
                                         units_prev=100_000, units_today=98_900)})
    assert out["flags"] == {}
    assert out["_meta"]["funds"]["00981A"]["moved_n"] == 0


def test_consensus_多檔同向():
    prev = [("6515", "穎崴", 100_000, 3.0)]
    today = [("6515", "穎崴", 180_000, 4.5)]          # +1.5pp
    snaps = {"00981A": _snap(prev, today), "00992A": _snap(prev, today),
             "00982A": _snap(prev, today)}
    f = b.build_flags(snaps)["flags"]["6515"]
    assert f["kind"] == "consensus_buy" and f["consensus"] == 3
    assert f["consensus_strong"] is True
    assert f["buyers"] == ["00981A", "00982A", "00992A"] and f["issuer_count"] == 3


def test_買賣互抵_consensus_歸零():
    prev = [("2881", "富邦金", 100_000, 5.0)]
    up = [("2881", "富邦金", 150_000, 6.0)]
    down = [("2881", "富邦金", 60_000, 3.5)]
    snaps = {"00981A": _snap(prev, up), "00403A": _snap(prev, down)}
    f = b.build_flags(snaps)["flags"]["2881"]
    assert f["consensus"] == 0 and f["consensus_strong"] is False
    assert f["buyers"] == ["00981A"] and f["sellers"] == ["00403A"]
    # net_shares = +50k - 40k = +10k → kind buy
    assert f["kind"] == "buy" and f["net_shares"] == 10_000


def test_新進成分股_視為加碼():
    out = b.build_flags({"00991A": _snap(
        prev=[("2330", "台積電", 1000_000, 50.0)],
        today=[("2330", "台積電", 1000_000, 48.0), ("3661", "世芯-KY", 50_000, 4.0)])})
    assert out["flags"]["3661"]["kind"] == "buy"
    # 2330 股數沒動、只是被新部位稀釋權重 → 不算調節
    assert "2330" not in out["flags"]


def test_出清_視為調節():
    out = b.build_flags({"00991A": _snap(
        prev=[("2330", "台積電", 1000_000, 50.0), ("1101", "台泥", 80_000, 5.0)],
        today=[("2330", "台積電", 1000_000, 55.0)])})
    assert out["flags"]["1101"]["kind"] == "sell" and out["flags"]["1101"]["net_shares"] == -80_000


def test_net_amount_有價就算_缺價就_None():
    prev = [("2330", "台積電", 1000, 10.0, 1000.0)]
    today = [("2330", "台積電", 1500, 12.0, 1000.0)]
    df_prev, df_today = b.pd.DataFrame(), b.pd.DataFrame()
    snaps = {"00981A": [("2026-09-08", _df(prev)), ("2026-09-09", _df(today))]}
    assert b.build_flags(snaps)["flags"]["2330"]["net_amount"] == 500 * 1000

    # price + market_value 都缺 → net_amount None（nav 仍在 → 還是有 direction）
    d0 = _df([("2330", "台積電", 1000, 10.0)]); d0[["price", "market_value"]] = None
    d1 = _df([("2330", "台積電", 1500, 40.0)]); d1[["price", "market_value"]] = None
    snaps2 = {"00981A": [("2026-09-08", d0), ("2026-09-09", d1)]}
    f2 = b.build_flags(snaps2)["flags"]
    assert "2330" not in f2 or f2["2330"]["net_amount"] is None


def test_降級_只有一份快照():
    snaps = {"00981A": _snap([("2330", "x", 1, 5.0)], [("2330", "x", 2, 6.0)]),
             "00403A": [("2026-09-09", _df([("2330", "x", 1, 5.0)]))],   # 只有 1 份
             "00991A": []}                                               # 完全沒有
    m = b.build_flags(snaps)["_meta"]
    assert m["synced_etfs"] == 1 and m["stale_etfs"] == 2
    assert m["schema_ok"] is True
    assert m["funds"]["00403A"]["synced"] is False


def test_同日兩份不算差分():
    snaps = {"00981A": [("2026-09-09", _df([("2330", "x", 1, 5.0)])),
                        ("2026-09-09", _df([("2330", "x", 9, 9.0)]))]}
    out = b.build_flags(snaps)
    assert out["flags"] == {} and out["_meta"]["synced_etfs"] == 0


def test_全部只有一份_anchor_None():
    snaps = {f["code"]: [("2026-09-09", _df([("2330", "x", 1, 5.0)]))] for f in b.FUNDS}
    m = b.build_flags(snaps)["_meta"]
    assert m["anchor_date"] is None and m["synced_etfs"] == 0 and m["schema_ok"] is True


def test_輸出可_json_序列化():
    import json
    snaps = {"00981A": _snap([("2330", "x", 1, 5.0)], [("2330", "x", 9, 9.0)])}
    json.dumps(b.build_flags(snaps))          # 不拋＝沒有 set / DataFrame 殘留
