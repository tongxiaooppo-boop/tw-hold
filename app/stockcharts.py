"""個股查詢的 plotly 圖（M4，PRD §4.2）。

八類：K 線 / 月營收 / 季 EPS / 三率 / 現金流 / 股利 / 本益比河流圖 / F-Score 9 分項。
月營收：bundle `revenue.parquet` 是長表（2015~），柱＝月營收、線＝YoY%。舊單月快照
schema 也吃（只有一列 → 不畫）。
⚠️ F-Score 9 分項：**打勾表，不加總、不給 verdict**（PRD §4.1）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

#: 均線集合——依顯示區間切換（短區間看短均線，長區間看長均線）。
_MA_SHORT = [("MA5", 5), ("MA20", 20), ("季線", 60)]
_MA_LONG = [("MA20", 20), ("季線", 60), ("年線", 240)]

#: 固定深色（app 主題也是深色）。圖例橫排放在**圖下方**——放上方會跟標題重疊、
#: 手機放右邊會吃掉半個繪圖區。
_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#d7dbd4"),
    legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="left", x=0),
    margin=dict(t=48, b=76, l=10, r=10),
    # 手機上單指拖曳會被 plotly 吃掉當平移／縮放，害頁面滑不動——關掉拖曳，
    # 保留 hover 點值；雙指縮放要兩指、不會誤觸。
    dragmode=False,
)


def _style(fig: go.Figure, title: str, height: int) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", font=dict(size=14)),
        height=height, **_LAYOUT)
    return fig


def kline(px: pd.DataFrame, name: str, start=None, ma: list | None = None) -> go.Figure:
    """`start`：只顯示這天以後（均線仍用完整歷史算，左緣才不缺）。
    `ma`：均線集合 [(label, window)]；None → 依有沒有給 start 猜短/長。"""
    d = px.copy().sort_values("date")
    d["date"] = pd.to_datetime(d["date"])
    x = d["date"].tolist()
    close = d["close"].astype(float)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=x, open=d["open"].astype(float).tolist(), high=d["high"].astype(float).tolist(),
        low=d["low"].astype(float).tolist(), close=close.tolist(),
        name="還原K線",
        increasing=dict(line=dict(color="#d62728")),      # 台股慣例：紅漲綠跌
        decreasing=dict(line=dict(color="#2ca02c"))))
    ma = ma or (_MA_SHORT if start is not None else _MA_LONG)
    for i, (label, w) in enumerate(ma):
        if len(d) >= w:
            fig.add_trace(go.Scatter(
                x=x, y=close.rolling(w).mean().tolist(), name=label,
                line=dict(width=1 if i == 0 else 1.4)))
    fig.update_layout(xaxis_rangeslider_visible=False)
    if start is not None:
        fig.update_xaxes(range=[pd.Timestamp(start), d["date"].max()])
        vis = close[d["date"] >= pd.Timestamp(start)]
        if len(vis):
            pad = (vis.max() - vis.min()) * 0.06 or 1
            fig.update_yaxes(range=[vis.min() - pad, vis.max() + pad])
    return _style(fig, f"{name} 還原日K + 均線", 440)


def monthly_revenue(rev: pd.DataFrame, name: str, start=None) -> go.Figure:
    """月營收：柱＝月營收（億元），線＝YoY%（右軸）。`start` 只裁 x 軸，YoY 用完整歷史算。"""
    d = rev.copy().sort_values("month")
    d["month"] = pd.to_datetime(d["month"])
    d["yoy"] = d["revenue"] / d["revenue"].shift(12) - 1.0
    fig = go.Figure([
        go.Bar(x=d["month"], y=d["revenue"] / 1e8, name="月營收（億）",
               marker_line_width=0),
        go.Scatter(x=d["month"], y=d["yoy"] * 100, name="YoY %", yaxis="y2",
                   line=dict(width=2, color="#d69f57")),
    ])
    fig.update_layout(
        yaxis2=dict(overlaying="y", side="right", showgrid=False, ticksuffix="%",
                    zeroline=True, zerolinecolor="rgba(214,159,87,.35)"))
    if start is not None:
        fig.update_xaxes(range=[pd.Timestamp(start), d["month"].max()])
    return _style(fig, f"{name} 月營收 + YoY", 360)


def institutional_net(chips: pd.DataFrame, name: str, start=None) -> go.Figure:
    """法人買賣超：外資／投信／自營柱狀（張，堆疊）+ 三大合計 20 日累計線（右軸）。
    `start` 只裁 x 軸，累計線用完整歷史算。"""
    d = chips.copy().sort_values("date")
    d["date"] = pd.to_datetime(d["date"])
    d["cum20"] = (d["foreign"] + d["trust"] + d["dealer"]).rolling(20).sum()
    fig = go.Figure([
        go.Bar(x=d["date"], y=d["foreign"], name="外資", marker_line_width=0),
        go.Bar(x=d["date"], y=d["trust"], name="投信", marker_line_width=0),
        go.Bar(x=d["date"], y=d["dealer"], name="自營", marker_line_width=0),
        go.Scatter(x=d["date"], y=d["cum20"], name="三大合計20日累計", yaxis="y2",
                   line=dict(width=2, color="#e9ece6")),
    ])
    fig.update_layout(barmode="relative",
                      yaxis2=dict(overlaying="y", side="right", showgrid=False,
                                  zeroline=True, zerolinecolor="rgba(233,236,230,.25)"))
    if start is not None:
        fig.update_xaxes(range=[pd.Timestamp(start), d["date"].max()])
    return _style(fig, f"{name} 法人買賣超（張）", 360)


def quarterly_eps(qf: pd.DataFrame, name: str) -> go.Figure:
    d = qf.tail(20)
    fig = go.Figure([
        go.Bar(x=d["period_end"], y=d["eps"], name="單季 EPS"),
        go.Scatter(x=d["period_end"], y=d["ttm_eps"], name="TTM EPS", yaxis="y2",
                   line=dict(width=2)),
    ])
    fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False))
    return _style(fig, f"{name} 季 EPS", 360)


def margins(qf: pd.DataFrame, name: str) -> go.Figure:
    d = qf.tail(24).copy()
    d["op_margin"] = d["op_income"] / d["revenue"]
    d["net_margin"] = d["net_income"] / d["revenue"]
    fig = go.Figure()
    for col, label in [("gross_margin", "毛利率"), ("op_margin", "營益率"),
                       ("net_margin", "稅後淨利率")]:
        fig.add_trace(go.Scatter(x=d["period_end"], y=d[col] * 100, name=label))
    return _style(fig, f"{name} 三率（%）", 360)


def cashflow(qf: pd.DataFrame, name: str) -> go.Figure:
    d = qf.tail(24).copy()
    d["fcf"] = d["ocf_net"].fillna(d["ocf"]) - d["capex"].abs()
    fig = go.Figure([
        go.Bar(x=d["period_end"], y=d["ocf_net"].fillna(d["ocf"]) / 1e8, name="營運現金流"),
        go.Bar(x=d["period_end"], y=-d["capex"].abs() / 1e8, name="資本支出"),
        go.Scatter(x=d["period_end"], y=d["fcf"] / 1e8, name="自由現金流", line=dict(width=2)),
    ])
    fig.update_layout(barmode="relative")
    return _style(fig, f"{name} 現金流（億元）", 360)


def dividends_chart(div: pd.DataFrame, name: str) -> go.Figure:
    d = div[div["year"] >= div["year"].max() - 12] if not div.empty else div
    # 一年多次配息（季配／半年配）→ 每筆各自一段疊在同一年的柱子上。給每段描邊，
    # 段跟段之間才看得出「今年配了幾次、各配多少」。按實際配息日排序讓疊放依時序。
    if "pay_date" in d.columns:
        d = d.sort_values(["year", "pay_date"])
    edge = dict(marker_line_color="rgba(233,236,230,.55)", marker_line_width=1)
    fig = go.Figure([
        go.Bar(x=d["year"], y=d["CashEarningsDistribution"], name="現金股利", **edge),
        go.Bar(x=d["year"], y=d["StockEarningsDistribution"], name="股票股利", **edge),
    ])
    fig.update_layout(barmode="stack")
    return _style(fig, f"{name} 逐年股利（元/股，同年多段＝分次配息）", 340)


def pe_river(px: pd.DataFrame, per: pd.DataFrame, name: str, start=None) -> go.Figure:
    """本益比河流圖：股價 + 「TTM EPS(t) × 自身 PE 分位」的河道。
    TTM EPS(t) ≈ 收盤 ÷ per（TWSE 報的 per 本來就是 trailing）。"""
    if per.empty:
        return _style(go.Figure(), f"{name} 本益比河流圖（無 per 資料）", 380)
    m = px[["date", "close"]].merge(per[["date", "per"]], on="date", how="inner")
    m = m[m["per"] > 0]
    if m.empty:
        return _style(go.Figure(), f"{name} 本益比河流圖（per 全為 0/負）", 380)
    m = m.assign(date=pd.to_datetime(m["date"]))
    m["ttm_eps"] = m["close"] / m["per"]
    qs = m["per"].quantile([0.1, 0.3, 0.5, 0.7, 0.9])
    fig = go.Figure()
    # 三段有意義的顏色：便宜區（P10–P30）綠、中性（P30–P70）灰、偏貴（P70–P90）琥珀
    fills = [None, "rgba(104,183,132,.30)", "rgba(150,158,148,.16)",
             "rgba(150,158,148,.16)", "rgba(214,159,87,.28)"]
    for (q, mult), col in zip(qs.items(), fills):
        fig.add_trace(go.Scatter(x=m["date"], y=m["ttm_eps"] * mult,
                                 name=f"PE {mult:.0f}x（P{int(q*100)}）",
                                 line=dict(width=0.6, color="rgba(160,168,158,.35)"),
                                 fill="tonexty" if col else None, fillcolor=col))
    fig.add_trace(go.Scatter(x=m["date"], y=m["close"], name="收盤",
                             line=dict(color="#e9ece6", width=1.6)))
    if start is not None:
        fig.update_xaxes(range=[pd.Timestamp(start), m["date"].max()])
        vis = m.loc[m["date"] >= pd.Timestamp(start)]
        if not vis.empty:
            lo = min(vis["close"].min(), (vis["ttm_eps"] * qs.iloc[0]).min())
            hi = max(vis["close"].max(), (vis["ttm_eps"] * qs.iloc[-1]).max())
            pad = (hi - lo) * 0.06 or 1
            fig.update_yaxes(range=[lo - pad, hi + pad])
    return _style(fig, f"{name} 本益比河流圖", 440)


def roe_trend(qf: pd.DataFrame, name: str) -> go.Figure:
    """ROE / ROA（TTM，%）逐季——價值軌「獲利品質」的走勢版（三率圖沒有 ROE）。"""
    d = qf.tail(24)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d["period_end"], y=d["roe"] * 100, name="ROE(TTM)",
                             line=dict(width=2)))
    if "roa" in d.columns:
        fig.add_trace(go.Scatter(x=d["period_end"], y=d["roa"] * 100, name="ROA(TTM)",
                                 line=dict(width=1.4)))
    return _style(fig, f"{name} ROE / ROA（%，TTM）", 340)


def balance_health(qf: pd.DataFrame, name: str) -> go.Figure:
    """負債比（左軸 %）+ 流動比（右軸，倍）逐季——價值/定存軌「財務安全」的走勢版。"""
    d = qf.tail(24)
    fig = go.Figure([
        go.Scatter(x=d["period_end"], y=d["debt_ratio"] * 100, name="負債比 %",
                   line=dict(width=2, color="#d69f57")),
        go.Scatter(x=d["period_end"], y=d["current_ratio"], name="流動比（倍）", yaxis="y2",
                   line=dict(width=1.6, color="#68b784")),
    ])
    fig.update_layout(yaxis=dict(ticksuffix="%"),
                      yaxis2=dict(overlaying="y", side="right", showgrid=False))
    return _style(fig, f"{name} 負債比 / 流動比", 340)


def yield_trend(per: pd.DataFrame, name: str, start=None) -> go.Figure:
    """現金殖利率走勢（%）——定存軌用；per.parquet 的 dividend_yield 已是百分比單位。"""
    d = per.copy().sort_values("date")
    d = d[pd.to_numeric(d["dividend_yield"], errors="coerce") > 0]
    if d.empty:
        return _style(go.Figure(), f"{name} 現金殖利率走勢（無資料）", 320)
    fig = go.Figure([go.Scatter(x=d["date"], y=d["dividend_yield"], name="現金殖利率",
                                line=dict(width=2, color="#68b784"))])
    fig.update_layout(yaxis=dict(ticksuffix="%"))
    if start is not None:
        fig.update_xaxes(range=[pd.Timestamp(start), pd.to_datetime(d["date"]).max()])
    return _style(fig, f"{name} 現金殖利率走勢（%）", 320)


F_LABELS = {
    "f_roa": "ROA 為正", "f_ocf": "營運現金流為正", "f_droa": "ROA 較去年提升",
    "f_accrual": "營運現金流 > 淨利", "f_leverage": "長期負債比未升高",
    "f_liquidity": "流動比未惡化", "f_noissue": "去年未增資",
    "f_margin": "毛利率較去年提升", "f_turnover": "資產週轉率較去年提升",
}


def fscore_table(qf: pd.DataFrame) -> pd.DataFrame:
    """Piotroski F-Score 9 分項——**打勾，不加總、不給 verdict**（PRD §4.1）。"""
    last = qf.iloc[-1]
    rows = [{"項目": lab, "狀態": "✅ 成立" if last.get(k) else "⬜ 未達"}
            for k, lab in F_LABELS.items()]
    return pd.DataFrame(rows)
