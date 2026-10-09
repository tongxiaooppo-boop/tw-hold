"""B6 M1／M2／M3：同鍵值不同新者勝、同檔同日同類別 type 不同的衝突、官方更正事件日的重複警告。"""
from __future__ import annotations

import json
import sys

import pandas as pd

sys.path.insert(0, "scripts")
import selfhost_adjust as sa  # noqa: E402
import selfhost_daily_merge as dm  # noqa: E402
import selfhost_events as se  # noqa: E402

ASOF = pd.Timestamp("2026-10-08 21:00")          # 週收集事件表的時間（UTC）


def _ev(rows):
    df = pd.DataFrame(rows, columns=["ticker", "market", "date", "type", "prev_close", "ref_price", "source"])
    df["factor"] = df["ref_price"] / df["prev_close"]
    df["detail"] = "{}"
    df["date"] = pd.to_datetime(df["date"])
    return df[se.COLS]


def _daily(rows, fetched):
    d = _ev(rows)
    d["fetched_at"] = pd.Timestamp(fetched)
    return d


# ───────────── M1：同鍵值不同，新者勝 ─────────────
def test_M1_每日列較新_每日勝_週收集的舊值被取代():
    w = _ev([("2330", "TW", "2026-10-12", "ex_div", 100.0, 99.0, "twse_ex")])
    d = _daily([("2330", "TW", "2026-10-12", "ex_div", 100.0, 98.5, "twse_ex")], "2026-10-09 10:00")   # 週收集之後才看到
    out, st = dm.merge_events(w, d, ASOF)
    assert st["conflicts"] == 1 and st["daily_won"] == 1 and st["weekly_won"] == 0
    assert len(out) == 1 and out.iloc[0]["ref_price"] == 98.5
    assert st["examples"][0]["winner"] == "daily"


def test_M1_每日列較舊_週收集勝_官方在兩者之間又更正過():
    w = _ev([("2330", "TW", "2026-10-12", "ex_div", 100.0, 99.0, "twse_ex")])
    d = _daily([("2330", "TW", "2026-10-12", "ex_div", 100.0, 98.5, "twse_ex")], "2026-10-07 10:00")   # 週收集之前就看到
    out, st = dm.merge_events(w, d, ASOF)
    assert st["weekly_won"] == 1 and out.iloc[0]["ref_price"] == 99.0


def test_M1_值相同_不算衝突():
    w = _ev([("2330", "TW", "2026-10-12", "ex_div", 100.0, 99.0, "twse_ex")])
    d = _daily([("2330", "TW", "2026-10-12", "ex_div", 100.0, 99.0, "twse_ex")], "2026-10-09 10:00")
    out, st = dm.merge_events(w, d, ASOF)
    assert st["conflicts"] == 0 and len(out) == 1


# ───────────── M2：同檔同日同類別、type 不同 ─────────────
def test_M2_官方把息更正成權息_每日較新_舊的那筆被丟掉_只剩一筆():
    w = _ev([("2330", "TW", "2026-10-12", "ex_div", 100.0, 99.0, "twse_ex")])
    d = _daily([("2330", "TW", "2026-10-12", "ex_both", 100.0, 95.0, "twse_ex")], "2026-10-09 10:00")
    out, st = dm.merge_events(w, d, ASOF)
    assert st["conflicts"] == 1 and st["daily_won"] == 1
    assert list(out["type"]) == ["ex_both"]                                         # 不會讓 resolve_events 靠字母序亂挑
    res = sa.resolve_events(out.assign(date=pd.to_datetime(out["date"])))
    assert len(res) == 1 and abs(res.iloc[0]["factor"] - 0.95) < 1e-9


def test_M2_每日較舊_週收集勝_每日那筆不併入():
    w = _ev([("2330", "TW", "2026-10-12", "ex_both", 100.0, 95.0, "twse_ex")])
    d = _daily([("2330", "TW", "2026-10-12", "ex_div", 100.0, 99.0, "twse_ex")], "2026-10-07 10:00")
    out, st = dm.merge_events(w, d, ASOF)
    assert st["weekly_won"] == 1 and list(out["type"]) == ["ex_both"]


def test_M2_因子相近視為同一件_留週收集():
    w = _ev([("2330", "TW", "2026-10-12", "ex_div", 100.0, 99.0, "twse_ex")])
    d = _daily([("2330", "TW", "2026-10-12", "ex_both", 100.0, 99.1, "twse_ex")], "2026-10-09 10:00")   # 差 ~0.1% < 0.5%
    out, st = dm.merge_events(w, d, ASOF)
    assert st["conflicts"] == 0 and len(out) == 1 and list(out["type"]) == ["ex_div"]


def test_M2_週收集只有FinMind列_每日官方列照加_由resolve_events依優先序處理():
    w = _ev([("0050", "TW", "2025-06-18", "split", 100.0, 25.0, "fm_split")])
    d = _daily([("0050", "TW", "2025-06-18", "par_change", 100.0, 25.0, "twse_par")], "2026-10-09 10:00")
    out, st = dm.merge_events(w, d, ASOF)
    assert st["from_daily"] == 1 and len(out) == 2


def test_沒有asof_每日永遠不贏():
    w = _ev([("2330", "TW", "2026-10-12", "ex_div", 100.0, 99.0, "twse_ex")])
    d = _daily([("2330", "TW", "2026-10-12", "ex_div", 100.0, 98.5, "twse_ex")], "2026-10-09 10:00")
    out, st = dm.merge_events(w, d, None)
    assert st["weekly_won"] == 1 and out.iloc[0]["ref_price"] == 99.0


# ───────────── M3：官方更正事件日 → 新舊兩筆都留下 ─────────────
def test_M3_14天內因子完全相同日期不同_要警告():
    ev = _ev([("2330", "TW", "2026-10-07", "ex_div", 100.0, 99.0, "twse_ex"),
              ("2330", "TW", "2026-10-08", "ex_div", 100.0, 99.0, "twse_ex")])
    s = dm.date_shift_suspects(ev)
    assert len(s) == 1 and s[0]["dates"] == ["2026-10-07", "2026-10-08"]


def test_M3_正常的連續兩期股利_因子不同_不警告():
    ev = _ev([("2330", "TW", "2026-10-07", "ex_div", 100.0, 99.0, "twse_ex"),
              ("2330", "TW", "2026-10-08", "ex_div", 100.0, 98.0, "twse_ex")])
    assert dm.date_shift_suspects(ev) == []


def test_M3_超過14天或不同類別_不警告():
    ev = _ev([("2330", "TW", "2026-09-01", "ex_div", 100.0, 99.0, "twse_ex"),
              ("2330", "TW", "2026-10-08", "ex_div", 100.0, 99.0, "twse_ex"),
              ("2330", "TW", "2026-10-09", "cap_reduction", 100.0, 99.0, "twse_red")])
    assert dm.date_shift_suspects(ev) == []


def test_M3_缺欄位的事件表不崩():
    assert dm.date_shift_suspects(pd.DataFrame({"ticker": ["x"]})) == []
    assert dm.date_shift_suspects(None) == []


# ───────────── main：manifest 欄位與 --weekly-corp-updated ─────────────
def test_main_manifest有衝突統計_asof來源(tmp_path):
    from tests.test_selfhost_events_daily_merge_main import _setup
    (tmp_path / "x").mkdir()
    w, dd, o = _setup(tmp_path / "x", with_meta=True)
    # 週收集已有 6129 同事件但值不同；每日（fetched_at 2026-10-07 20:00）比週收集資產時間（10/5 20:00Z）新 → 每日勝
    wev = pd.read_parquet(w / "corp_actions.parquet")
    row = wev.iloc[0].copy()
    row["ticker"], row["market"], row["date"], row["type"], row["source"] = "6129", "TWO", pd.Timestamp("2026-10-07"), "ex_both", "tpex_ex"
    row["prev_close"], row["ref_price"], row["factor"] = 15.0, 14.5, 14.5 / 15.0
    pd.concat([wev, pd.DataFrame([row])], ignore_index=True).to_parquet(w / "corp_actions.parquet")
    assert dm.main(["--weekly-dir", str(w), "--daily-dir", str(dd), "--out-dir", str(o),
                    "--weekly-corp-updated", "2026-10-05T20:00:00Z"]) == 0
    man = json.loads((o / "merge_manifest.json").read_text(encoding="utf-8"))
    assert man["events_daily_conflicts"]["daily_won"] == 1
    assert man["events_weekly_asof"]["source"] == "asset"
    ev = pd.read_parquet(o / "corp_actions.parquet")
    assert abs(ev[ev["ticker"] == "6129"].iloc[0]["ref_price"] - 14.11) < 1e-9
    # 不給時間 → 用代理值（週收集日線最後一天 21:00 UTC）
    assert dm.main(["--weekly-dir", str(w), "--daily-dir", str(dd), "--out-dir", str(tmp_path / "o2")]) == 0
    man2 = json.loads((tmp_path / "o2" / "merge_manifest.json").read_text(encoding="utf-8"))
    assert man2["events_weekly_asof"]["source"] == "proxy"
