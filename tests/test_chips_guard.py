"""法人籌碼讀取端自保（2026-10-05 上櫃自營欄空白事件）。"""
import pandas as pd

from reference.chips_guard import fill_dealer, identity_stats


def _df(rows):
    return pd.DataFrame(rows, columns=["date", "ticker", "foreign_net", "trust_net", "dealer_net", "total_net"])


def test_fill_dealer_from_total():
    d = fill_dealer(_df([["2026-10-02", "6488", -862867, 105839, None, -530472]]))
    assert d["dealer_net"].iloc[0] == 226556


def test_fill_dealer_keeps_existing_and_does_not_invent():
    d = fill_dealer(_df([
        ["2026-10-02", "2330", 100, 10, 5, 115],        # 已有自營 → 不動
        ["2026-10-02", "9999", 100, 10, None, None],    # 沒合計 → 維持空，不補 0
        ["2026-10-02", "8888", None, 10, None, 50],     # 外資缺 → 無法推，維持空
    ]))
    assert d["dealer_net"].iloc[0] == 5
    assert pd.isna(d["dealer_net"].iloc[1]) and pd.isna(d["dealer_net"].iloc[2])


def test_identity_stats_flags_blank_dealer_and_mismatch():
    rows = [["2026-10-01", f"T{i}", 100, 10, None, 115] for i in range(9)]   # 自營缺 9 列
    rows.append(["2026-10-01", "BAD", 100, 10, 5, 999])                      # 不符 1 列
    s = identity_stats(_df(rows))
    assert s["dealer_missing"] == 0.9 and s["mismatch"] == 1.0
    assert identity_stats(fill_dealer(_df(rows)))["dealer_missing"] == 0.0


def test_identity_stats_empty_safe():
    assert identity_stats(_df([]))["rows"] == 0
