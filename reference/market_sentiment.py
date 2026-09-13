"""總經羅盤頁首的「市場情緒摘要」——固定句型代入數字，不是 AI 生成。

## 為什麼不用 AI

2026-09-13 討論過：這裡只是把 `market_status.py` / `us_macro.py` 已經算好的數字
（多空狀態、VIX 分位、殖利率曲線形狀……）串成一段話，本質是**模板代入**，不是
生成——句型設計得誠實、不裝懂，品質就不會差。真的要做「有脈絡感的敘事」（例如
連結到新聞事件）才是 AI 解說層的事（見 `docs/AI_LAYER.md`，v2 未實作，AI 只解說
不選股），這裡刻意不越界。

## 每個句子只做「條列現況」，不做「評論」

例如「VIX 處於近一年低檔」是事實（分位算出來的），但不會說「顯示市場過度樂觀」
這種需要脈絡判斷的話——後者才是模板容易講出怪句子的地方，所以不做。
"""

from __future__ import annotations

_TW_BOTH_LABEL = {
    ("bull", "bull"): "偏多（站上季線與年線）",
    ("bear", "bear"): "偏空（跌破季線與年線）",
    ("chop", "chop"): "盤整（貼著季線與年線）",
}
_STATE_ZH = {"bull": "偏多", "bear": "偏空", "chop": "盤整"}


def tw_market_sentence(name: str, card: dict) -> str:
    """0050/006201 這種台股卡——MA60 跟 MA200 都列，一致就講一句，分歧就兩條都講。"""
    ma60, ma200 = card.get("ma60"), card.get("ma200")
    if ma60 is None and ma200 is None:
        return f"{name}資料不足"
    if ma60 is None or ma200 is None:
        v = ma60 or ma200
        which = "季線" if ma60 else "年線"
        return f"{name}{which}判定{_STATE_ZH[v['state']]}（另一條均線暖機中）"
    pair = (ma60["state"], ma200["state"])
    if pair in _TW_BOTH_LABEL:
        return f"{name}{_TW_BOTH_LABEL[pair]}"
    return f"{name}季線{_STATE_ZH[ma60['state']]}、年線{_STATE_ZH[ma200['state']]}（短長分歧）"


def us_index_sentence(name: str, card: dict) -> str:
    """道瓊/那斯達克/費半——國際機構慣例只看年線（MA200）。"""
    v = card.get("ma200")
    if v is None:
        return f"{name}資料不足"
    text = {"bull": "站穩年線", "bear": "跌破年線", "chop": "貼著年線整理"}[v["state"]]
    return f"{name}{text}"


def vix_sentence(pct: float | None) -> str:
    """VIX 近一年分位——只講分位事實，不猜「市場情緒為什麼這樣」。"""
    if pct is None:
        return "VIX 資料不足"
    if pct < 0.3:
        return "VIX 處於近一年低檔，波動度偏低"
    if pct > 0.7:
        return "VIX 處於近一年高檔，波動度偏高"
    return "VIX 處於近一年中段"


def yield_curve_sentence(short: float | None, ten: float | None) -> str:
    """短天期(13週) vs 10年期——這是最常引用的衰退領先指標(3m10y)。
    只講「倒掛與否」這個形狀事實，不猜衰退機率（那需要模型，不是這頁的事）。"""
    if short is None or ten is None:
        return "殖利率資料不足，無法判斷曲線形狀"
    if ten < short:
        return "殖利率曲線倒掛（短天期高於10年期）"
    return "殖利率曲線正常（10年期高於短天期）"


def compose(tw_sentences: list[str], us_sentences: list[str],
            vix_text: str, curve_text: str) -> str:
    """兜成一段話。台股/美股指數用頓號連，VIX/殖利率單獨成句——三段各自獨立，
    不做任何跨段推論（不會因為「台股偏多」加「VIX偏低」就講「風險偏好回升」
    這種需要因果判斷的合成句）。"""
    parts = []
    if tw_sentences:
        parts.append("、".join(tw_sentences) + "。")
    if us_sentences:
        parts.append("、".join(us_sentences) + "。")
    parts.append(f"{vix_text}，{curve_text}。")
    return "".join(parts)
