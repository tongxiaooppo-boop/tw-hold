"""推薦歷史（reference/history.py）：封存、狀態分類（空清單≠沒跑≠無資料）、搜尋、短線健康版本。"""
import json

import pandas as pd

from reference import history as H


def _short(asof, n, scanned=600, margin=True):
    return {"_meta": {"asof": asof, "scanned": scanned, "has_margin": margin, "has_chips": True},
            "stocks": [{"ticker": f"{1000+i}", "name": f"名{i}", "close": 10.0, "first_seen": asof, "streak_days": 1}
                       for i in range(n)]}


def test_seal_force_revisions(tmp_path):
    a, ln = H.short_line(_short("2026-10-13", 2), "live")
    assert H.add_line(a, "short", ln, out_dir=tmp_path) == "written"
    # 回填不得蓋掉 live
    assert H.add_line(a, "short", H.short_line(_short("2026-10-13", 5), "backfill-git")[1], out_dir=tmp_path) == "sealed"
    assert json.loads((tmp_path / f"{a}.json").read_text(encoding="utf-8"))["lines"]["short"]["n"] == 2
    # 同日 live 再跑且內容不同 → 以最後一版為準，舊版摘要進 revisions；內容相同則不動
    assert H.add_line(a, "short", H.short_line(_short("2026-10-13", 5), "live")[1], out_dir=tmp_path) == "revised"
    assert H.add_line(a, "short", H.short_line(_short("2026-10-13", 5), "live")[1], out_dir=tmp_path) == "sealed"
    ln = json.loads((tmp_path / f"{a}.json").read_text(encoding="utf-8"))["lines"]["short"]
    assert ln["n"] == 5 and len(ln["revisions"]) == 1


def test_degraded_line_is_replaced_by_a_healthy_one(tmp_path):
    a, bad = H.short_line(_short("2026-10-13", 3, margin=False), "live")
    assert bad["status"] == "degraded"
    H.add_line(a, "short", bad, out_dir=tmp_path)
    assert H.add_line(a, "short", H.short_line(_short("2026-10-13", 3), "backfill-git")[1], out_dir=tmp_path) == "revised"
    assert json.loads((tmp_path / f"{a}.json").read_text(encoding="utf-8"))["lines"]["short"]["status"] == "ok"


def test_lines_are_independent_in_one_file(tmp_path):
    H.add_line("2026-10-13", "short", H.short_line(_short("2026-10-13", 1), "live")[1], out_dir=tmp_path)
    H.add_line("2026-10-13", "swing", H.swing_line("2026-10-13", [], "live")[1], out_dir=tmp_path)
    assert set(json.loads((tmp_path / "2026-10-13.json").read_text(encoding="utf-8"))["lines"]) == {"short", "swing"}


def test_view_states(tmp_path):
    (tmp_path / "_holidays.json").write_text(json.dumps({"2026-10-09": "國慶補假"}), encoding="utf-8")
    H.add_line("2026-10-07", "short", H.short_line(_short("2026-10-07", 3), "backfill-git")[1], out_dir=tmp_path)
    H.add_line("2026-10-08", "short", H.short_line(_short("2026-10-08", 0), "backfill-git")[1], out_dir=tmp_path)
    H.add_line("2026-10-12", "short", H.short_line(_short("2026-10-12", 0, margin=False), "live")[1], out_dir=tmp_path)
    v = H.load_view("short", pd.Timestamp("2026-10-15"), hist_dir=tmp_path, window=7, today="2026-10-15")
    st = {d["d"]: d["state"] for d in v["days"]}
    assert st == {"2026-10-07": "ok", "2026-10-08": "zero", "2026-10-09": "holiday", "2026-10-12": "degraded",
                  "2026-10-13": "notrun", "2026-10-14": "notrun", "2026-10-15": "pending"}


def test_not_retained_between_backfill_and_live(tmp_path):
    H.add_line("2026-10-06", "long", H.long_line({"_meta": {"trading_date": "2026-10-06"}, "candidates_pool": []}, "backfill-git")[1], out_dir=tmp_path)
    H.add_line("2026-10-09", "long", H.long_line({"_meta": {"trading_date": "2026-10-09"}, "candidates_pool": []}, "live")[1], out_dir=tmp_path)
    v = H.load_view("long", pd.Timestamp("2026-10-09"), hist_dir=tmp_path, window=3)
    assert {d["d"]: d["state"] for d in v["days"]} == {"2026-10-07": "not_retained", "2026-10-08": "not_retained", "2026-10-09": "zero"}


def test_swing_merge_same_ticker_and_degraded_window():
    a, ln = H.swing_line("2026-10-05", [{"ticker": "1.TW", "name": "甲", "entry": 10, "stop": 9, "signal": "A"},
                                        {"ticker": "1.TW", "name": "甲", "entry": 10, "stop": 8.5, "signal": "B"}], "live")
    assert ln["n"] == 1 and ln["candidates"][0]["stop"] == 8.5 and ln["candidates"][0]["sig"] == "A、B"
    assert ln["status"] == "degraded"
    assert H.swing_line("2026-09-09", [], "live")[1]["status"] == "ok"


def test_search_fullwidth_and_degraded_hint(tmp_path):
    H.add_line("2026-10-07", "short", H.short_line(_short("2026-10-07", 3), "live")[1], out_dir=tmp_path)
    H.add_line("2026-10-08", "short", H.short_line(_short("2026-10-08", 0, margin=False), "live")[1], out_dir=tmp_path)
    v = H.load_view("short", pd.Timestamp("2026-10-08"), hist_dir=tmp_path, window=2)
    hits, deg = H.search([v], "１００１")
    assert len(hits) == 1 and "1001" in hits[0] and deg is True


def test_view_merges_recomputed_sidecar(tmp_path):
    (tmp_path / "recomputed").mkdir()
    H.add_line("2026-10-05", "swing", H.swing_line("2026-10-05", [], "backfill-csv")[1], out_dir=tmp_path)
    (tmp_path / "recomputed" / "2026-10-05.json").write_text(json.dumps({"lines": {"swing": {"candidates": [
        {"t": "2.TW", "nm": "乙", "px": 5, "stop": 4, "sig": "月營收創年高 + 估值便宜"}]}}}), encoding="utf-8")
    before = (tmp_path / "2026-10-05.json").read_bytes()
    d = H.load_view("swing", pd.Timestamp("2026-10-05"), hist_dir=tmp_path, window=1)["days"][0]
    assert d["state"] == "recomp" and d["n"] == 1 and d["c"][0]["src"] == "補算"
    assert (tmp_path / "2026-10-05.json").read_bytes() == before


def test_recompute_only_day_and_streaks_across_live_and_recomputed(tmp_path):
    (tmp_path / "recomputed").mkdir()
    # 9/08 只有補算（當時沒有這條線的紀錄）、9/09 有 live：同一檔連續兩日
    (tmp_path / "recomputed" / "2026-09-08.json").write_text(json.dumps({"lines": {"short": {"candidates": [
        {"t": "1101", "nm": "台泥", "px": 30.0}]}}}), encoding="utf-8")
    H.add_line("2026-09-09", "short", H.short_line(_short("2026-09-09", 1), "live")[1], out_dir=tmp_path)
    v = H.load_view("short", pd.Timestamp("2026-09-09"), hist_dir=tmp_path, window=2)
    d8, d9 = v["days"]
    assert d8["state"] == "recomp" and d8["c"][0]["src"] == "補算" and d8["n"] == 1
    assert d9["c"][0]["t"] == "1000" and d9["c"][0]["st"] == 1       # 9/09 的 1000 前一天沒出現 → 1
    # 同一檔跨補算＋live 連續
    H.add_line("2026-09-10", "short", H.short_line({"_meta": {"asof": "2026-09-10", "scanned": 600, "has_margin": True, "has_chips": True},
                                                    "stocks": [{"ticker": "1101", "name": "台泥", "close": 31.0}]}, "live")[1], out_dir=tmp_path)
    (tmp_path / "recomputed" / "2026-09-09.json").write_text(json.dumps({"lines": {"short": {"candidates": [
        {"t": "1101", "nm": "台泥", "px": 30.5}]}}}), encoding="utf-8")
    v = H.load_view("short", pd.Timestamp("2026-09-10"), hist_dir=tmp_path, window=3)
    c = [x for x in v["days"][-1]["c"] if x["t"] == "1101"][0]
    assert (c["fs"], c["st"]) == ("2026-09-08", 3)
