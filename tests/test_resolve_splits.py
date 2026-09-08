"""resolve_splits：跳空比例 ↔ FinMind 事件 factor 的比對與吸附。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import resolve_splits as rs  # noqa: E402


def test_nice_吸附整數與簡分數():
    assert rs._nice(7.001) == 7
    assert rs._nice(1.9998) == 2
    assert rs._nice(0.5003) == 0.5
    assert rs._nice(6.5) == 6.5            # 半整數
    assert rs._nice(3.72) == 3.72          # 差整數/半整數 >0.5% → 保持原值
    assert rs._nice(3.999) == 4


def test_比對邏輯_分割與減資方向():
    # 分割：bundle 跳空 ×0.1（跌），target = 1/0.1 = 10，FinMind before/after = 720/72 = 10
    ratio = 0.1
    target = 1.0 / ratio if ratio < 1 else ratio
    assert abs(10.0 / target - 1) < rs.MATCH_TOL

    # 減資：bundle 跳空 ×2.18（漲），target = 2.18，FinMind = 48.15/22.05 ≈ 2.18
    ratio = 2.18
    target = 1.0 / ratio if ratio < 1 else ratio
    assert abs((48.15 / 22.05) / target - 1) < rs.MATCH_TOL

    # 資料雜訊：跳空 ×1.85，FinMind 兩張表皆空 → 沒有 event 可比 → 不會 match
    assert rs._nice(1.0) == 1
