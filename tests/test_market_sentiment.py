"""reference.market_sentiment——固定句型代入，不是 AI 生成，逐分支測完。"""
from __future__ import annotations

from reference.market_sentiment import (
    compose,
    tw_market_sentence,
    us_index_sentence,
    vix_sentence,
    yield_curve_sentence,
)


def _v(state: str) -> dict:
    return {"state": state, "gap_pct": 0.0, "ma": 100.0, "close": 100.0}


def test_tw_兩條均線一致_多頭():
    assert tw_market_sentence("上市", {"ma60": _v("bull"), "ma200": _v("bull")}) == "上市偏多（站上季線與年線）"


def test_tw_兩條均線一致_空頭():
    assert tw_market_sentence("上市", {"ma60": _v("bear"), "ma200": _v("bear")}) == "上市偏空（跌破季線與年線）"


def test_tw_兩條均線一致_盤整():
    assert tw_market_sentence("上市", {"ma60": _v("chop"), "ma200": _v("chop")}) == "上市盤整（貼著季線與年線）"


def test_tw_短長分歧():
    out = tw_market_sentence("上櫃", {"ma60": _v("bull"), "ma200": _v("bear")})
    assert out == "上櫃季線偏多、年線偏空（短長分歧）"


def test_tw_其中一條暖機中():
    out = tw_market_sentence("上市", {"ma60": _v("bull"), "ma200": None})
    assert out == "上市季線判定偏多（另一條均線暖機中）"


def test_tw_都沒資料():
    assert tw_market_sentence("上市", {"ma60": None, "ma200": None}) == "上市資料不足"


def test_us_index_只看ma200_站穩():
    assert us_index_sentence("那斯達克", {"ma200": _v("bull")}) == "那斯達克站穩年線"


def test_us_index_只看ma200_跌破():
    assert us_index_sentence("道瓊", {"ma200": _v("bear")}) == "道瓊跌破年線"


def test_us_index_資料不足():
    assert us_index_sentence("費半", {"ma200": None}) == "費半資料不足"


def test_vix_低檔():
    assert vix_sentence(0.1) == "VIX 處於近一年低檔，波動度偏低"


def test_vix_高檔():
    assert vix_sentence(0.9) == "VIX 處於近一年高檔，波動度偏高"


def test_vix_中段():
    assert vix_sentence(0.5) == "VIX 處於近一年中段"


def test_vix_無資料():
    assert vix_sentence(None) == "VIX 資料不足"


def test_殖利率曲線_正常():
    assert yield_curve_sentence(short=3.9, ten=4.9) == "殖利率曲線正常（10年期高於短天期）"


def test_殖利率曲線_倒掛():
    assert yield_curve_sentence(short=5.0, ten=4.0) == "殖利率曲線倒掛（短天期高於10年期）"


def test_殖利率曲線_缺資料():
    assert yield_curve_sentence(None, 4.0) == "殖利率資料不足，無法判斷曲線形狀"


def test_compose串接三段():
    out = compose(["上市偏多"], ["那斯達克站穩年線"], "VIX 處於近一年低檔", "殖利率曲線正常")
    assert out == "上市偏多。那斯達克站穩年線。VIX 處於近一年低檔，殖利率曲線正常。"


def test_compose沒有台股或美股句子時不留空句():
    out = compose([], [], "VIX 資料不足", "殖利率資料不足，無法判斷曲線形狀")
    assert out == "VIX 資料不足，殖利率資料不足，無法判斷曲線形狀。"
