"""估值 2.0 股數基準（upgrade_guide §4-2）。預期值由 Opus 定，實作者不得改。"""
import math

import pandas as pd
import pytest

from reference import corporate_actions as ca
from reference import share_basis as sb

T = pd.Timestamp

EVENTS = {
    "9999": [
        {"date": "2020-01-10", "type": "ex_rights", "m": 1.1, "pf": None},
        {"date": "2022-06-01", "type": "par_change", "m": 4, "pf": 4},
        {"date": "2023-03-01", "type": "cap_reduction", "m": None, "pf": 0.9},
        {"date": "2025-05-20", "type": "cap_reduction", "m": None, "pf": 0.8},
    ]
}


@pytest.fixture
def fake_events(monkeypatch):
    monkeypatch.setattr(ca, "SPLITS", EVENTS)
    monkeypatch.setattr(ca, "EVENTS_OK", True)


def test_事件倍數_不含當天(fake_events):
    assert math.isclose(sb.share_factor_after("9999", T("2019-12-31")), 4.4)
    assert math.isclose(sb.share_factor_after("9999", T("2020-01-10")), 4.0)
    assert sb.share_factor_after("9999.TW", T("2024-01-01")) == 1.0
    assert sb.share_factor_after("1234", T("2020-01-01")) == 1.0


def test_面額推回(fake_events):
    assert math.isclose(sb.par_value_at("9999", T("2021-01-01"), 2.5), 10.0)
    assert math.isclose(sb.par_value_at("9999", T("2023-01-01"), 2.5), 2.5)
    assert sb.par_value_at("9999", T("2021-01-01"), None) is None


def test_現金減資區間剔除(fake_events):
    ex = sb.excluded_months("9999")
    # 2023-03-01 → 第一個季末 2023-03-31 → 期限 2023-05-15 → 剔除 3、4 月
    # 2025-05-20 → 季末 2025-06-30 → 期限 2025-08-14 → 剔除 5、6、7 月
    assert ex == {pd.Period(x, "M") for x in ("2023-03", "2023-04", "2025-05", "2025-06", "2025-07")}


def test_事件表讀不到要報錯(monkeypatch):
    monkeypatch.setattr(ca, "EVENTS_OK", False)
    with pytest.raises(sb.EventsUnavailable):
        sb.share_factor_after("2330", T("2020-01-01"))
