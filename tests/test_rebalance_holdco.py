"""換股日挪到金控法定期限＋1 天（使用者 2026-11-22 拍板）——框架測試，預期值不准改。"""
from datetime import date

import pytest

import build_lists as bl
import build_classification as bc

D = date


def test_HOLDCO_13家():
    assert len(bl.HOLDCO) == 13 and len(set(bl.HOLDCO)) == 13
    assert "2888" not in bl.HOLDCO and "5880" in bl.HOLDCO


@pytest.mark.parametrize("asof,expect", [
    (D(2026, 11, 22), D(2026, 11, 14)),   # 切換前：舊表
    (D(2026, 11, 30), D(2026, 11, 14)),
    (D(2026, 12, 1), D(2026, 12, 1)),     # 切換日
    (D(2027, 3, 30), D(2026, 12, 1)),
    (D(2027, 3, 31), D(2027, 3, 31)),
    (D(2027, 5, 20), D(2027, 3, 31)),     # 舊 5/15 不再是換股日
    (D(2027, 6, 1), D(2027, 6, 1)),
    (D(2027, 8, 31), D(2027, 6, 1)),
    (D(2027, 9, 1), D(2027, 9, 1)),
    (D(2026, 9, 8), D(2026, 8, 14)),      # 舊測試的案例仍成立
])
def test_current_rebalance_新舊換股日切換(asof, expect):
    assert bl.current_rebalance(asof) == expect


@pytest.mark.parametrize("rb,expect", [
    (D(2026, 12, 1), D(2026, 9, 30)),
    (D(2027, 3, 31), D(2026, 12, 31)),
    (D(2027, 6, 1), D(2027, 3, 31)),
    (D(2027, 9, 1), D(2027, 6, 30)),
    (D(2026, 11, 14), D(2026, 9, 30)),    # 舊表
    (D(2026, 5, 15), D(2026, 3, 31)),
])
def test_target_quarter_end(rb, expect):
    assert bl.target_quarter_end(rb) == expect


def test_target_quarter_end_非換股日報錯():
    with pytest.raises(ValueError):
        bl.target_quarter_end(D(2026, 12, 2))


LATEST = {"2881": "2026-09-30", "2882": "2026-06-30", "2880": "2026-06-30",
          "2887": "2025-12-31", "2883": None}


def test_holdco_missing_只列缺新季且有上一季的():
    # 2887 停在更早季、2883 沒資料 → 不算；2881 已到
    assert bl.holdco_missing(LATEST, D(2026, 12, 1)) == ["2880", "2882"]
    assert bl.holdco_missing({"2881": "2026-09-30"}, D(2026, 12, 1)) == []


def test_rebalance_status_金控未到齊先不換():
    st = bl.rebalance_status(D(2026, 12, 3), set(), LATEST)
    assert st == {"period": D(2026, 11, 14), "waiting": ["2880", "2882"], "stale": []}


def test_rebalance_status_到齊就換():
    st = bl.rebalance_status(D(2026, 12, 3), set(), {"2881": "2026-09-30", "2882": "2026-09-30"})
    assert st == {"period": D(2026, 12, 1), "waiting": [], "stale": []}


def test_rebalance_status_等滿14天照換():
    assert bl.rebalance_status(D(2026, 12, 14), set(), LATEST)["period"] == D(2026, 11, 14)
    st = bl.rebalance_status(D(2026, 12, 15), set(), LATEST)
    assert st == {"period": D(2026, 12, 1), "waiting": [], "stale": ["2880", "2882"]}


def test_rebalance_status_不給金控資料就不檢查():
    assert bl.rebalance_status(D(2026, 12, 3), set(), None)["period"] == D(2026, 12, 1)


def test_rebalance_status_切換前不檢查金控():
    # 11/14 期是舊表，就算金控缺 Q3 也不往前退
    assert bl.rebalance_status(D(2026, 11, 22), set(), LATEST)["period"] == D(2026, 11, 14)


def test_rebalance_status_暫緩檔在新表也有效():
    st = bl.rebalance_status(D(2026, 12, 20), {D(2026, 12, 1)}, {"2881": "2026-09-30"})
    assert st["period"] == D(2026, 11, 14)


def test_effective_rebalance_回傳period():
    assert bl.effective_rebalance(D(2026, 12, 3), set(), LATEST) == D(2026, 11, 14)
    assert bl.effective_rebalance(D(2026, 12, 3), set()) == D(2026, 12, 1)


def test_分類季更換股日跟新表一致():
    got = sorted((v[0], v[1]) for v in bc.REBALANCE_FOR_QUARTER.values())
    assert got == sorted(bl.REBALANCE_MD)
    assert bc.rebalance_date_for("2026-09-30") == __import__("pandas").Timestamp("2026-12-01")
    assert bc.rebalance_date_for("2026-12-31") == __import__("pandas").Timestamp("2027-03-31")
