"""個股查詢的 plotly 圖（M4，PRD §4.2）。

八類：K 線 / 月營收 / 季 EPS / 三率 / 現金流 / 股利 / 本益比河流圖 / F-Score 9 分項。
⚠️ 月營收：bundle `revenue.parquet` 只有單月快照，歷史圖待 revenue 歷史進 bundle。
⚠️ F-Score 9 分項：**打勾表，不加總、不給 verdict**（PRD §4.1）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

_MA = {"季線": 60, "年線": 240}


def kline(px: pd.DataFrame, name: str) -> go.Figure:
    d = px.copy()
    x = pd.to_datetime(d["date"]).tolist()
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=x, open=d["open"].astype(float).tolist(), high=d["high"].astype(float).tolist(),
        low=d["low"].astype(float).tolist(), close=d["close"].astype(float).tolist(),
        name="還原K線",
        increasing=dict(line=dict(color="#d62728")),
        decreasing=dict(line=dict(color="#2ca02c"))))
    for label, w in _MA.items():
        if len(d) >= w:
            fig.add_trace(go.Scatter(
                x=x, y=d["close"].astype(float).rolling(w).mean().tolist(),
                name=label, line=dict(width=1)))
    fig.update_layout(title=f"{name} 還原日K + 均線", xaxis_rangeslider_visible=False,
                      height=420, margin=dict(t=40, b=20))
    return fig


def quarterly_eps(qf: pd.DataFrame, name: str) -> go.Figure:
    d = qf.tail(20)
    fig = go.Figure([
        go.Bar(x=d["period_end"], y=d["eps"], name="單季 EPS"),
        go.Scatter(x=d["period_end"], y=d["ttm_eps"], name="TTM EPS", yaxis="y2",
                   line=dict(width=2)),
    ])
    fig.update_layout(title=f"{name} 季 EPS", height=340, margin=dict(t=40, b=20),
                      yaxis2=dict(overlaying="y", side="right", showgrid=False))
    return fig


def margins(qf: pd.DataFrame, name: str) -> go.Figure:
    d = qf.tail(24).copy()
    d["op_margin"] = d["op_income"] / d["revenue"]
    d["net_margin"] = d["net_income"] / d["revenue"]
    fig = go.Figure()
    for col, label in [("gross_margin", "毛利率"), ("op_margin", "營益率"),
                       ("net_margin", "稅後淨利率")]:
        fig.add_trace(go.Scatter(x=d["period_end"], y=d[col] * 100, name=label))
    fig.update_layout(title=f"{name} 三率（%）", height=340, margin=dict(t=40, b=20))
    return fig


def cashflow(qf: pd.DataFrame, name: str) -> go.Figure:
    d = qf.tail(24).copy()
    d["fcf"] = d["ocf_net"].fillna(d["ocf"]) - d["capex"].abs()
    fig = go.Figure([
        go.Bar(x=d["period_end"], y=d["ocf_net"].fillna(d["ocf"]) / 1e8, name="營運現金流"),
        go.Bar(x=d["period_end"], y=-d["capex"].abs() / 1e8, name="資本支出"),
        go.Scatter(x=d["period_end"], y=d["fcf"] / 1e8, name="自由現金流", line=dict(width=2)),
    ])
    fig.update_layout(title=f"{name} 現金流（億元）", barmode="relative", height=340,
                      margin=dict(t=40, b=20))
    return fig


def dividends_chart(div: pd.DataFrame, name: str) -> go.Figure:
    d = div[div["year"] >= div["year"].max() - 12] if not div.empty else div
    fig = go.Figure([
        go.Bar(x=d["year"], y=d["CashEarningsDistribution"], name="現金股利"),
        go.Bar(x=d["year"], y=d["StockEarningsDistribution"], name="股票股利"),
    ])
    fig.update_layout(title=f"{name} 逐年股利（元/股）", barmode="stack", height=320,
                      margin=dict(t=40, b=20))
    return fig


def pe_river(px: pd.DataFrame, per: pd.DataFrame, name: str) -> go.Figure:
    """本益比河流圖：股價 + 「TTM EPS(t) × 自身 PE 分位」的河道。
    TTM EPS(t) ≈ 收盤 ÷ per（TWSE 報的 per 本來就是 trailing）。"""
    if per.empty:
        return go.Figure().update_layout(title=f"{name} 本益比河流圖（無 per 資料）", height=380)
    m = px[["date", "close"]].merge(per[["date", "per"]], on="date", how="inner")
    m = m[m["per"] > 0]
    if m.empty:
        return go.Figure().update_layout(title=f"{name} 本益比河流圖（per 全為 0/負）", height=380)
    m["ttm_eps"] = m["close"] / m["per"]
    qs = m["per"].quantile([0.1, 0.3, 0.5, 0.7, 0.9])
    fig = go.Figure()
    colors = ["#eef", "#dde", "#ccd", "#dde", "#eef"]
    for (q, mult), col in zip(qs.items(), colors):
        fig.add_trace(go.Scatter(x=m["date"], y=m["ttm_eps"] * mult,
                                 name=f"PE {mult:.0f}x（P{int(q*100)}）",
                                 line=dict(width=0.5), fill="tonexty" if q > 0.1 else None,
                                 fillcolor=col))
    fig.add_trace(go.Scatter(x=m["date"], y=m["close"], name="收盤",
                             line=dict(color="#111", width=1.5)))
    fig.update_layout(title=f"{name} 本益比河流圖", height=420, margin=dict(t=40, b=20))
    return fig


F_LABELS = {
    "f_roa": "ROA 為正", "f_ocf": "營運現金流為正", "f_droa": "ROA 較去年提升",
    "f_accrual": "營運現金流 > 淨利", "f_leverage": "長期負債比未升高",
    "f_liquidity": "流動比未惡化", "f_noissue": "去年未增資",
    "f_margin": "毛利率較去年提升", "f_turnover": "資產週轉率較去年提升",
}


def fscore_table(qf: pd.DataFrame) -> pd.DataFrame:
    """Piotroski F-Score 9 分項——**打勾，不加總、不給 verdict**（PRD §4.1）。"""
    last = qf.iloc[-1]
    rows = [{"項目": lab, "狀態": "✓" if last.get(k) else "✗"} for k, lab in F_LABELS.items()]
    return pd.DataFrame(rows)
