"""長波段模擬單（輕量版，`screener/swing_paper.py`）。"""

from __future__ import annotations

from screener.swing_paper import (BACKTEST_BASELINE, N_MIN, build, compute_stats,
                                  find_new_exits, merge_history)


def _stopped(entry, exit_price, entry_date="2026-01-05", exit_date="2026-02-10", name="測試"):
    return {"name": name, "first_seen": entry_date, "entry_price": entry,
            "exit_date": exit_date, "exit_price": exit_price, "status": "stopped_out"}


def _candidate(entry_date="2026-01-05", entry=100.0):
    return {"name": "測試", "first_seen": entry_date, "entry_price": entry,
            "exit_date": None, "exit_price": None, "status": "candidate"}


def test_find_new_exits_抓到剛結算的():
    prev = {"1001": _candidate()}
    new = {"1001": _stopped(100.0, 90.0)}
    out = find_new_exits(prev, new)
    assert len(out) == 1
    r = out[0]
    assert r["ticker"] == "1001" and abs(r["ret_pct"] - (-0.10)) < 1e-9


def test_find_new_exits_同一筆不重複抓():
    prev = {"1001": _stopped(100.0, 90.0)}
    new = {"1001": _stopped(100.0, 90.0)}          # 同一天重跑，exit_date 沒變
    assert find_new_exits(prev, new) == []


def test_find_new_exits_舊出場被新一輪蓋掉_不會漏記():
    """swing_stops 同一檔重新達標會開新一輪、蓋掉舊出場資訊——但那筆舊出場
    在被蓋掉**之前**那次 build_lists 執行時就該已經被記進歷史了，這裡只驗證
    「新一輪的 candidate 狀態不會被誤判成新出場」。"""
    prev = {"1001": _stopped(100.0, 90.0, exit_date="2026-02-10")}
    new = {"1001": _candidate(entry_date="2026-03-01", entry=95.0)}   # 重新達標，開新一輪
    assert find_new_exits(prev, new) == []


def test_merge_history_去重():
    h1 = [{"ticker": "1001", "entry_date": "2026-01-05", "ret_pct": -0.1}]
    h2 = [{"ticker": "1001", "entry_date": "2026-01-05", "ret_pct": -0.1},
         {"ticker": "1002", "entry_date": "2026-01-06", "ret_pct": 0.2}]
    merged = merge_history(h1, h2)
    assert len(merged) == 2


def test_compute_stats_樣本不足_勝率顯示None():
    history = [{"ticker": str(i), "entry_date": "2026-01-01", "exit_date": "2026-02-01",
               "ret_pct": 0.05} for i in range(N_MIN - 1)]
    st = compute_stats(history)
    assert st["n"] == N_MIN - 1
    assert st["win_rate"] is None and st["vs_backtest"] is None
    assert st["by_month"]                          # 月度表不受樣本門檻限制


def test_compute_stats_樣本足夠_算勝率跟對照回測():
    history = ([{"ticker": str(i), "entry_date": "2026-01-01", "exit_date": "2026-02-01",
                "ret_pct": 0.10} for i in range(6)]
              + [{"ticker": str(i), "entry_date": "2026-01-01", "exit_date": "2026-02-01",
                "ret_pct": -0.05} for i in range(4)])
    st = compute_stats(history)
    assert st["n"] == 10
    assert abs(st["win_rate"] - 0.6) < 1e-9
    assert st["vs_backtest"]["backtest_win_rate"] == BACKTEST_BASELINE["win_rate"]
    assert st["vs_backtest"]["gap_pp"] is not None


def test_compute_stats_月度分解():
    history = [
        {"ticker": "1001", "entry_date": "2026-01-01", "exit_date": "2026-02-10", "ret_pct": 0.1},
        {"ticker": "1002", "entry_date": "2026-01-01", "exit_date": "2026-02-20", "ret_pct": -0.1},
        {"ticker": "1003", "entry_date": "2026-01-01", "exit_date": "2026-03-05", "ret_pct": 0.2},
    ]
    st = compute_stats(history)
    ym = {row["ym"]: row for row in st["by_month"]}
    assert ym["2026-02"]["n"] == 2 and ym["2026-03"]["n"] == 1


def test_build_累積不遺失_跨輪執行():
    prev_tracked = {"1001": _candidate()}
    new_tracked1 = {"1001": _stopped(100.0, 110.0)}
    p1 = build({}, prev_tracked, new_tracked1)
    assert len(p1["trades"]) == 1

    # 下一輪：1001 重新達標開新一輪（蓋掉舊出場），另一檔也結算了
    new_tracked2 = {"1001": _candidate(entry_date="2026-03-01", entry=95.0),
                    "1002": _stopped(50.0, 45.0)}
    p2 = build(p1, new_tracked1, new_tracked2)
    assert len(p2["trades"]) == 2                  # 舊那筆沒有因為被蓋掉而消失
    assert {t["ticker"] for t in p2["trades"]} == {"1001", "1002"}
