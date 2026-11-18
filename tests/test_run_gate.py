"""reference.run_gate／scripts.run_gate 的純邏輯測試（固定 now_utc，不打網路）。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from reference.run_gate import (WORKFLOWS, chip_fresh, decide, expected_chip_date,
                                expected_us_date, macro_fresh)

UTC = timezone.utc
T_WED_0517 = datetime(2026, 11, 17, 21, 17, tzinfo=UTC)    # 台北 11/18 週三 05:17
T_WED_1630 = datetime(2026, 11, 18, 8, 30, tzinfo=UTC)     # 台北週三 16:30
T_WED_1300 = datetime(2026, 11, 18, 5, 0, tzinfo=UTC)      # 台北週三 13:00
ALL = {f"S{i}" for i in range(18)} | {"^TNX"}              # 19 檔


def _meta(**kw):
    m = {"reference_date": "2026-11-17", "stale": [], "carried_forward": [], "estimated": []}
    m.update(kw)
    return m


def _tx(**kw):
    t = {"date": "2026-11-18", "missing_night": False}
    t.update(kw)
    return t


def test_expected_us_date_週三早上是週二():
    assert expected_us_date(T_WED_0517) == date(2026, 11, 17)


def test_expected_us_date_週一早上是上週五():
    assert expected_us_date(datetime(2026, 11, 15, 21, 17, tzinfo=UTC)) == date(2026, 11, 13)  # 台北 11/16 05:17


def test_expected_chip_date_15點後是今天():
    assert expected_chip_date(T_WED_1630) == date(2026, 11, 18)


def test_expected_chip_date_15點前是前一平日():
    assert expected_chip_date(T_WED_1300) == date(2026, 11, 17)


def test_macro_fresh_全齊():
    assert macro_fresh(_meta(), set(ALL), _tx(), ALL, T_WED_0517)[0] is True


def test_macro_fresh_少一檔不新鮮():
    ok, why = macro_fresh(_meta(), ALL - {"^TNX"}, _tx(), ALL, T_WED_0517)
    assert ok is False and "^TNX" in why


def test_macro_fresh_stale非空不新鮮():
    assert macro_fresh(_meta(stale=[{"symbol": "AAPL"}]), set(ALL), _tx(), ALL, T_WED_0517)[0] is False


def test_macro_fresh_有沿用不新鮮():
    assert macro_fresh(_meta(carried_forward=["^TNX"]), set(ALL), _tx(), ALL, T_WED_0517)[0] is False


def test_macro_fresh_日期舊不新鮮():
    assert macro_fresh(_meta(reference_date="2026-11-14"), set(ALL), _tx(), ALL, T_WED_0517)[0] is False


def test_macro_fresh_夜盤缺不新鮮():
    assert macro_fresh(_meta(), set(ALL), _tx(missing_night=True), ALL, T_WED_0517)[0] is False


def test_macro_fresh_meta不存在():
    assert macro_fresh(None, set(ALL), _tx(), ALL, T_WED_0517)[0] is False


def test_chip_fresh_兩檔都到():
    d = date(2026, 11, 18)
    assert chip_fresh({"foreign_futures": d, "inst_flow": d}, T_WED_1630)[0] is True


def test_chip_fresh_一檔落後():
    d = date(2026, 11, 18)
    assert chip_fresh({"foreign_futures": d, "inst_flow": date(2026, 11, 17)}, T_WED_1630)[0] is False


@pytest.mark.parametrize("src", ["manual", None])
def test_decide_手動一律跑(src):
    for w in WORKFLOWS:
        assert decide(w, "workflow_dispatch", src, T_WED_0517, fresh=(True, "新鮮"))[0] is True


def test_decide_alarm_總經新鮮跳過():
    assert decide("global_macro", "workflow_dispatch", "alarm", T_WED_0517, fresh=(True, "x"))[0] is False


def test_decide_alarm_總經不新鮮跑():
    assert decide("global_macro", "workflow_dispatch", "alarm", T_WED_0517, fresh=(False, "x"))[0] is True


def test_decide_alarm_openapi月營收heartbeat照跑():
    for w in ("openapi_daily", "revenue_watch", "heartbeat"):
        assert decide(w, "workflow_dispatch", "alarm", T_WED_0517)[0] is True


def test_decide_備援_總經新鮮跳過():
    assert decide("global_macro", "schedule", None, T_WED_0517, fresh=(True, "x"))[0] is False


def test_decide_備援_openapi近8小時有成功跳過():
    assert decide("openapi_daily", "schedule", None, T_WED_0517,
                  last_dispatch_success_utc=T_WED_0517 - timedelta(hours=3))[0] is False


def test_decide_備援_openapi超過8小時跑():
    assert decide("openapi_daily", "schedule", None, T_WED_0517,
                  last_dispatch_success_utc=T_WED_0517 - timedelta(hours=9))[0] is True


def test_decide_備援_沒有成功紀錄跑():
    assert decide("openapi_daily", "schedule", None, T_WED_0517)[0] is True


def test_decide_備援_heartbeat九點後跳過():
    now = datetime(2026, 11, 18, 8, 16, tzinfo=UTC)          # 台北 16:16
    assert decide("heartbeat", "schedule", None, now)[0] is False


def test_decide_備援_heartbeat開盤前看2小時():
    now = datetime(2026, 11, 18, 0, 40, tzinfo=UTC)          # 台北 08:40
    assert decide("heartbeat", "schedule", None, now,
                  last_dispatch_success_utc=datetime(2026, 11, 18, 0, 23, tzinfo=UTC))[0] is False
    assert decide("heartbeat", "schedule", None, now,
                  last_dispatch_success_utc=datetime(2026, 11, 17, 0, 23, tzinfo=UTC))[0] is True


def test_decide_未知workflow報錯():
    with pytest.raises(ValueError):
        decide("nope", "schedule", None, T_WED_0517)


def test_cli_出錯一律跑(monkeypatch, tmp_path, capsys):
    import scripts.run_gate as cli

    def boom(*a, **k):
        raise RuntimeError("讀檔失敗")
    monkeypatch.setattr(cli, "load_fresh", boom)
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert cli.main(["--workflow", "global_macro"]) == 0
    assert "run=true" in out.read_text(encoding="utf-8")
    assert "gate 出錯，照跑" in capsys.readouterr().out


def test_五條workflow都有gate與source輸入():
    wf = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    for name in WORKFLOWS:
        d = yaml.safe_load((wf / f"{name}.yml").read_text(encoding="utf-8"))
        on = d.get("on", d.get(True))                         # PyYAML 把 on 讀成 True
        assert "source" in on["workflow_dispatch"]["inputs"], name
        assert "gate" in d["jobs"], name
        mains = [j for k, j in d["jobs"].items() if k not in ("gate", "notify-failure")]
        assert mains, name
        for j in mains:
            needs = j["needs"] if isinstance(j["needs"], list) else [j["needs"]]
            assert "gate" in needs and "needs.gate.outputs.run == 'true'" in j["if"], name
