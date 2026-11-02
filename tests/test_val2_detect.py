"""估值 2.0 可信度四組（upgrade_guide §8；P3）。預期值由 Opus 定，實作者不得改。"""
import dataclasses

import numpy as np
import pandas as pd
import pytest

from reference import corporate_actions as ca
from screener import detect as dt
from screener import eps_windows as ew
from test_val2_eps_windows import make_monthly, make_q

T = pd.Timestamp
ASOF = T("2026-11-02")


@pytest.fixture(autouse=True)
def _events(monkeypatch):
    monkeypatch.setattr(ca, "SPLITS", {})
    monkeypatch.setattr(ca, "EVENTS_OK", True)


def Q(**over):
    q = make_q("2026Q2", n=30, **over)
    q["capital_stock"] = 1000.0
    return q


def C(group, name, level, why="x"):
    return dt.Check(group, name, level, None, why)


# ── summarize ───────────────────────────────────────────

def test_彙總_沒檢查的組是未檢查():
    s = dt.summarize([])
    assert set(s) == set(dt.GROUPS)
    assert all(v == {"level": "unchecked", "items": []} for v in s.values())


def test_彙總_取最嚴重_只列非ok():
    s = dt.summarize([C("data", "a", "ok", ""), C("data", "b", "warn"), C("data", "c", "stop", "停"),
                      C("share_basis", "d", "unchecked"), C("share_basis", "e", "ok", "")])
    assert s["data"]["level"] == "stop"
    assert [i["name"] for i in s["data"]["items"]] == ["c", "b"]
    assert s["share_basis"]["level"] == "unchecked" and [i["name"] for i in s["share_basis"]["items"]] == ["d"]
    assert dt.stopped(s, "data") == "停" and dt.stopped(s, "share_basis") is None


def test_彙總_沒有試算季要列出():
    s = dt.summarize([dt.Check("estimate", "試算季", "ok", None, "沒有試算季")])
    assert s["estimate"]["level"] == "ok"
    assert s["estimate"]["items"] == [{"name": "試算季", "level": "ok", "value": None, "why": "沒有試算季"}]


# ── data ────────────────────────────────────────────────

def _windows(q, monthly, asof=ASOF, financial=False):
    return ew.windows(q, monthly, asof, live=True, financial=financial)


def test_資料_月營收應公布未取得():
    q, m = Q(), make_monthly("2026-08")
    out = {c.name: c for c in dt.data_checks(q, m, _windows(q, m), None, ASOF)}
    assert out["月營收缺"].level == "warn" and "2026-09" in out["月營收缺"].why
    assert out["財報缺季"].level == "ok"


def test_資料_金融不查月營收():
    q, m = Q(), make_monthly("2026-08")
    names = [c.name for c in dt.data_checks(q, m, _windows(q, m, financial=True), None, ASOF, financial=True)]
    assert "月營收缺" not in names and "財報矛盾" not in names


def test_資料_斷季停用():
    q, m = Q(drop=("2026Q1",)), make_monthly("2026-09")
    out = {c.name: c for c in dt.data_checks(q, m, _windows(q, m), None, ASOF)}
    assert out["財報缺季"].level == "stop" and out["財報缺季"].group == "data"


def test_資料_分類過期():
    q, m = Q(), make_monthly("2026-09")
    cls = {"decided_at": "2026-03-31"}
    out = {c.name: c for c in dt.data_checks(q, m, _windows(q, m), cls, ASOF)}
    assert out["分類過期"].level == "warn" and "2026-03-31" in out["分類過期"].why


# ── share_basis ─────────────────────────────────────────

def test_股數_事件表讀不到只回一條停用(monkeypatch):
    monkeypatch.setattr(ca, "EVENTS_OK", False)
    out = dt.share_checks("9999", Q(), ASOF)
    assert len(out) == 1 and (out[0].name, out[0].level) == ("股數事件表", "stop")


def test_股數_對得上與面額未收集():
    out = {c.name: c for c in dt.share_checks("9999", Q(), ASOF)}
    assert out["股數對不上"].level == "ok" and out["股數對不上"].value == pytest.approx(0.0)
    assert out["面額與特別股"].level == "unchecked" and out["現金減資區間"].level == "ok"
    assert {c.name: c for c in dt.share_checks("9999", Q(), ASOF, today_par=10.0)}["面額與特別股"].level == "ok"


def test_股數_對不上提示():
    q = Q()
    q["capital_stock"] = 1500.0
    c = {c.name: c for c in dt.share_checks("9999", q, ASOF)}["股數對不上"]
    assert c.level == "warn" and c.value == pytest.approx(1 / 3)


def test_股數_現金減資區間停用(monkeypatch):
    monkeypatch.setattr(ca, "SPLITS", {"9999": [{"date": "2026-09-15", "type": "cap_reduction", "m": None}]})
    c = {c.name: c for c in dt.share_checks("9999", Q(), ASOF)}["現金減資區間"]
    assert c.level == "stop"
    q3 = make_q("2026Q3", n=30)
    q3["capital_stock"] = 1000.0
    after = {c.name: c for c in dt.share_checks("9999", q3, ASOF)}["現金減資區間"]
    assert after.level == "ok"                               # 事件那一季（Q3）財報進來就解除


# ── comparability ───────────────────────────────────────

def test_可比性_分布寬與截斷只提示():
    stats = {"raw_mults": (8.0, 10.0, 24.0), "mults": (8.0, 10.0, 24.0), "capped": True}
    out = {c.name: c for c in dt.comparability_checks({"subtags": ["疑似循環"], "metrics": {"switched": True}}, stats)}
    assert out["倍數分布"].level == "warn" and out["倍數分布"].value == pytest.approx(3.0)
    assert out["倍數截斷"].level == "warn" and out["疑似循環"].level == "warn" and out["剛換類"].level == "warn"
    assert all(c.level in ("ok", "warn") for c in out.values())


# ── estimate ────────────────────────────────────────────

def test_試算_沒有試算季():
    q, m = Q(), make_monthly("2026-06")
    out = dt.estimate_checks(q, m, _windows(q, m))
    assert out == [dt.Check("estimate", "試算季", "ok", None, "沒有試算季")]


def test_試算_合成資料全部正常():
    q, m = Q(), make_monthly("2026-09")
    out = {c.name: c for c in dt.estimate_checks(q, m, _windows(q, m))}
    assert out["橋接殘差"].level == "ok" and out["橋接殘差"].value == pytest.approx(0.0)
    assert all(c.level == "ok" for c in out.values())


def test_橋接殘差_公式誤差大停用():
    q, m = Q(), make_monthly("2026-09")
    d = _windows(q, m)["ttm"].details[0]
    c = dt.bridge_residual(q, dataclasses.replace(d, shares=60.0))      # eps_hat 1.6 vs 0.96
    assert c.level == "stop" and c.value == pytest.approx(2 / 3)


def test_高變動_排除淡旺季():
    seasonal = Q(**{"2025Q1": {"revenue": 700.0}, "2026Q1": {"revenue": 700.0}})   # 兩年都 Q1 淡 → d=0
    assert dt.variability(seasonal).level == "ok"
    jump = Q(**{"2026Q1": {"revenue": 700.0}})                            # 只有今年跳 → d=+43%
    c = dt.variability(jump)
    assert c.level == "warn" and c.value == pytest.approx(1000 / 700 - 1)


def test_高變動_資料不足不判():
    assert dt.variability(make_q("2026Q2", n=4)).level == "ok"
