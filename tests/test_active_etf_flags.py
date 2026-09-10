"""build_active_etf_flags.build()——把 etfinfo summary 瘦成 per-ticker 旗標。

守：只留該留的欄位、kind 判定對、NaN/缺欄不炸、schema 壞會被擋。
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")
import build_active_etf_flags as b  # noqa: E402


def _summary(**over):
    s = {
        "anchorDate": "2026-09-09", "latestMarketDate": "2026-09-09",
        "syncStatus": {"totalEtfs": 40, "syncedEtfs": 26, "staleEtfs": 14},
        "flowRankings": [
            {"stockCode": "2892", "stockName": "第一金", "industry": "金融保險業",
             "netShares": 1803000, "netAmount": 68153400, "issuerCount": 1,
             "etfDetails": [{"etfCode": "00404A"}]},
            {"stockCode": "2845", "stockName": "遠東銀", "industry": "金融保險業",
             "netShares": -2240000, "netAmount": -30352000, "issuerCount": 1,
             "etfDetails": []},
        ],
        "consensusSignals": [
            {"stockCode": "6515", "stockName": "穎崴", "buyCount": 4, "sellCount": 0,
             "buyers": ["00994A", "00992A", "00404A", "00408A"], "sellers": [],
             "netSignal": 4, "isStrong": True},
        ],
    }
    s.update(over)
    return s


def test_基本轉換():
    out = b.build(_summary())
    m, f = out["_meta"], out["flags"]
    assert m["schema_ok"] and m["anchor_date"] == "2026-09-09" and m["stale_etfs"] == 14
    # flowRankings 淨買 → buy；淨賣 → sell
    assert f["2892"]["kind"] == "buy" and f["2892"]["net_shares"] == 1803000
    assert f["2845"]["kind"] == "sell"
    # consensusSignals 只在 consensus，且沒進 flowRankings → consensus_buy
    assert f["6515"]["kind"] == "consensus_buy"
    assert f["6515"]["consensus"] == 4 and f["6515"]["consensus_strong"] is True


def test_consensus_疊加到_flowRanking():
    s = _summary(consensusSignals=[
        {"stockCode": "2892", "buyers": ["a", "b"], "sellers": [], "netSignal": 2,
         "isStrong": False, "stockName": "第一金"}])
    f = b.build(s)["flags"]
    assert f["2892"]["kind"] == "consensus_buy"      # 有淨買 + 2 檔共識 → 升級
    assert f["2892"]["consensus"] == 2


@pytest.mark.parametrize("bad", [
    {"flowRankings": None},
    {"consensusSignals": "x"},
    {},
])
def test_schema_guard(bad):
    s = _summary()
    if bad == {}:
        del s["anchorDate"]
    else:
        s.update(bad)
    with pytest.raises(ValueError):
        b.build(s)
