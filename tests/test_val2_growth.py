"""估值 2.0 年增率模組（upgrade_guide §6、§10）。預期值由 Opus 定，實作者不得改。"""
import math

from screener import growth as g


def test_yoy_虧損擴大():
    r = g.yoy_eps(-4, -2)
    assert r.label == "loss_wider" and r.value is None and r.text == "虧損擴大"


def test_yoy_虧損縮小():
    assert g.yoy_eps(-1, -2).label == "loss_narrower"


def test_yoy_虧轉盈():
    r = g.yoy_eps(1, -1)
    assert r.label == "turn_profit" and r.value is None


def test_yoy_轉虧():
    assert g.yoy_eps(-1, 2).label == "turn_loss"


def test_yoy_基期低():
    r = g.yoy_eps(3, 0.5)
    assert r.label == "pct" and r.low_base and math.isclose(r.value, 5.0)
    assert r.text == "+500%（基期低）"


def test_yoy_基期低_相對():
    assert g.yoy_eps(30, 5).low_base          # 去年不到今年 1/5
    assert not g.yoy_eps(30, 10).low_base


def test_yoy_一般():
    r = g.yoy_eps(13.5, 10)
    assert r.label == "pct" and not r.low_base and r.text == "+35%"


def test_yoy_零與缺值():
    assert g.yoy_eps(1, 0).label == "base_zero"
    assert g.yoy_eps(0, 1).label == "flat"
    assert g.yoy_eps(None, 1).label == "na"
    assert g.yoy_eps(float("nan"), 1).label == "na"
    assert g.yoy_eps(float("inf"), 1).label == "na"


def test_營收_非正值不可用():
    assert g.yoy_revenue(100, 0).label == "na"
    assert g.yoy_revenue(-5, 100).label == "na"
    r = g.yoy_revenue(120, 100)
    assert r.label == "pct" and math.isclose(r.value, 0.2) and not r.low_base


def test_門檻_例外詞不過():
    assert not g.yoy_eps(-4, -2).passes(0.25)
    assert not g.yoy_eps(1, -1).passes(0.25)
    assert g.yoy_eps(1.3, 1.0).passes(0.25)
    assert not g.yoy_eps(1.25, 1.0).passes(0.25)


def test_加速():
    assert g.accel(g.yoy_revenue(130, 100), g.yoy_revenue(120, 100)) is True
    assert g.accel(g.yoy_revenue(110, 100), g.yoy_revenue(120, 100)) is False
    assert g.accel(g.yoy_revenue(110, 100), g.yoy_revenue(120, 0)) is None
