"""B6：daily_merge.main 端到端——每日事件窗口併進 corp_actions，events_through／events_gap_days 跟著前進。"""
from __future__ import annotations

import json
import sys

import pandas as pd

sys.path.insert(0, "scripts")
import selfhost_daily_merge as dm  # noqa: E402

INST_COLS = ["foreign_net", "fi_prop_net", "trust_net", "dealer_net", "total_net"]
MARGIN_COLS = ["margin_balance", "margin_buy", "margin_sell", "margin_redeem", "short_balance", "short_buy",
               "short_sell", "short_redeem", "offset"]


def _px(days, tickers=(("2330", "TW"), ("6129", "TWO"))):
    rows = [(t, mk, d) for d in days for t, mk in tickers]
    df = pd.DataFrame(rows, columns=["ticker", "market", "date"])
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close"):
        df[c] = 10.0
    df["volume"], df["value"], df["chg"] = 1000.0, 1.0, 0.0
    return df


def _chips(days, cols):
    return pd.concat([pd.DataFrame({"date": pd.to_datetime(d), "ticker": ["2330", "6129"], "market": ["TW", "TWO"],
                                    **{c: 1.0 for c in cols}}) for d in days], ignore_index=True)


def _setup(tmp_path, with_meta: bool):
    w, dd, o = tmp_path / "w", tmp_path / "d", tmp_path / "o"
    w.mkdir(), dd.mkdir()
    _px(["2026-10-05"]).to_parquet(w / "raw_prices.parquet")
    _chips(["2026-10-05"], INST_COLS).to_parquet(w / "inst.parquet")
    _chips(["2026-10-05"], MARGIN_COLS).to_parquet(w / "margin.parquet")
    d = ["2026-10-06", "2026-10-07"]
    _px(d).to_parquet(dd / "openapi_prices.parquet")
    _chips(d, INST_COLS).to_parquet(dd / "openapi_inst.parquet")
    _chips(d, MARGIN_COLS).to_parquet(dd / "openapi_margin.parquet")
    wev = pd.DataFrame({"ticker": ["2330"], "market": ["TW"], "date": pd.to_datetime(["2026-09-01"]), "type": ["ex_div"],
                        "prev_close": [100.0], "ref_price": [99.0], "factor": [0.99], "source": ["twse_ex"], "detail": ["{}"]})
    wev.to_parquet(w / "corp_actions.parquet")
    dev = pd.DataFrame({"ticker": ["6129"], "market": ["TWO"], "date": pd.to_datetime(["2026-10-07"]), "type": ["ex_both"],
                        "prev_close": [15.0], "ref_price": [14.11], "factor": [14.11 / 15.0], "source": ["tpex_ex"],
                        "detail": ["{}"], "fetched_at": pd.Timestamp("2026-10-07 20:00")})
    dev.to_parquet(dd / "openapi_events.parquet")
    if with_meta:
        (dd / "openapi_events_meta.json").write_text(json.dumps({"through": "2026-10-07", "fetched_at": "2026-10-07 20:00"}),
                                                     encoding="utf-8")
    return w, dd, o


def _run(w, dd, o):
    assert dm.main(["--weekly-dir", str(w), "--daily-dir", str(dd), "--out-dir", str(o)]) == 0
    return json.loads((o / "merge_manifest.json").read_text(encoding="utf-8"))


def test_每日事件併進corp_actions_through前進_無事件缺口(tmp_path):
    w, dd, o = _setup(tmp_path, with_meta=True)
    man = _run(w, dd, o)
    assert man["complete_day"] == "2026-10-07"
    assert man["events_through"] == "2026-10-07" and man["events_gap_days"] == []
    assert man["events_from_daily"] == 1
    ev = pd.read_parquet(o / "corp_actions.parquet")
    assert set(ev["ticker"]) == {"2330", "6129"}                                    # 每日事件有進來


def test_沒有meta時_事件仍併入但through停在週收集日_缺口要講(tmp_path):
    w, dd, o = _setup(tmp_path, with_meta=False)
    man = _run(w, dd, o)
    assert man["events_through"] == "2026-10-05"
    assert man["events_gap_days"] == ["2026-10-06", "2026-10-07"]                   # 不靜默：沒有「抓成功」的證據就不宣稱涵蓋
    assert man["events_from_daily"] == 1


def test_內容雜湊_每日事件變了就變(tmp_path):
    w, dd, o = _setup(tmp_path, with_meta=True)
    h1 = _run(w, dd, tmp_path / "o1")["input_hash"]
    assert _run(w, dd, tmp_path / "o2")["input_hash"] == h1                         # 冪等
    dev = pd.read_parquet(dd / "openapi_events.parquet")
    dev2 = pd.concat([dev, dev.assign(ticker="1101", market="TW", source="twse_ex")], ignore_index=True)
    dev2.to_parquet(dd / "openapi_events.parquet")
    assert _run(w, dd, tmp_path / "o3")["input_hash"] != h1                          # 新事件 → 重做還原與 zip
