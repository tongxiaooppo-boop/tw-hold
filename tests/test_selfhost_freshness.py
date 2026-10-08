"""新鮮度紅燈：完整日落後 ≥2 個交易日要紅，長假/週末不誤報。"""
from __future__ import annotations

import json
import sys
from datetime import date

sys.path.insert(0, "scripts")
import selfhost_freshness as fr  # noqa: E402


def test_落後交易日數():
    assert fr.lag_trading_days(date(2026, 10, 7), date(2026, 10, 8), None) == 0        # 昨天的完整日＝正常
    assert fr.lag_trading_days(date(2026, 10, 6), date(2026, 10, 8), None) == 1
    assert fr.lag_trading_days(date(2026, 10, 2), date(2026, 10, 5), None) == 0        # 週五完整日、週一看＝週末不算
    assert fr.lag_trading_days(date(2026, 10, 8), date(2026, 10, 13), {date(2026, 10, 9)}) == 1   # 10/9 補假不算：只剩 10/12


def test_紅燈門檻(tmp_path, monkeypatch):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"complete_day": "2026-10-06"}), encoding="utf-8")

    class _D(fr.datetime):
        @classmethod
        def now(cls, tz=None):
            return fr.datetime(2026, 10, 9, 8, 0, tzinfo=tz)
    monkeypatch.setattr(fr, "datetime", _D)
    monkeypatch.setattr("last_trading_day_guard.fetch_closed", lambda: None)
    assert fr.main(["--manifest", str(m)]) == 1                                       # 10/6 → 10/9：落後 10/7、10/8 兩個交易日
    m.write_text(json.dumps({"complete_day": "2026-10-07"}), encoding="utf-8")
    assert fr.main(["--manifest", str(m)]) == 0                                       # 落後 1 → 只警告
    assert fr.main(["--manifest", str(tmp_path / "none.json")]) == 0                   # 還沒發佈過 → 略過
