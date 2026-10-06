"""自建上游：月初檢查——前一個月發生了什麼、我們有沒有漏。產出一份可直接貼給 AI 查證的 Markdown。

## 分工（為什麼不是「整份丟給 AI」）
1. **程式能查的先查完**（便宜、確定）：
   - 完整性：該月每個交易日的檔數有沒有掉、融資券／法人有沒有缺日。
   - **事件對帳**：重新向官方抓該月的除權息／減資／面額變更清單，逐筆對照 corp_actions，列出「官方有、我們沒有」與「我們有、官方沒有」。
2. **剩下程式歸不到解釋的才給 AI**：事件簿（selfhost_ledger.py）裡的 `flag`（價格跳動無事件可解釋、還原後仍跳、缺日未歸因）。
   AI 只負責「上網查這檔這天發生了什麼」並附出處，**不負責判斷我們的資料對不對**——那一步要拿資料驗（外部 AI 已多次說錯）。

## 用法
    python scripts/selfhost_monthly_review.py                  # 前一個月
    python scripts/selfhost_monthly_review.py --month 2026-09
    python scripts/selfhost_monthly_review.py --month 2026-09 --offline   # 不連官方（只做完整性＋事件簿）

輸出：`data/derived/selfhost_monthly_review_<YYYY-MM>.md`
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "data" / "selfhost"
OUTDIR = ROOT / "data" / "derived"
CLASS = {"ex_div": "div", "ex_rights": "div", "ex_both": "div", "cap_reduction": "red", "par_change": "par", "split": "par"}


def month_range(month: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    a = pd.Timestamp(month + "-01")
    return a, a + pd.offsets.MonthEnd(0)


def prev_month(today: date | None = None) -> str:
    t = pd.Timestamp(today or date.today())
    return (t.replace(day=1) - pd.Timedelta(days=1)).strftime("%Y-%m")


def diff_events(official: pd.DataFrame, ours: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """以 (ticker, 事件日, 類別) 對帳。回傳 (官方有我們沒有, 我們有官方沒有)。
    類別用 div／red／par（不比 ex_div vs ex_rights 的細分：TWSE 與 TPEx 的詞彙不同）。官方事件日不一定是交易日，故只比日期字串。"""
    def key(d: pd.DataFrame) -> pd.DataFrame:
        k = d.copy()
        k["cls"] = k["type"].map(CLASS)
        k["date"] = pd.to_datetime(k["date"])
        k["ticker"] = k["ticker"].astype(str)
        return k[k["cls"].notna()].drop_duplicates(["ticker", "date", "cls"])
    o, u = key(official), key(ours)
    m = o.merge(u[["ticker", "date", "cls"]], on=["ticker", "date", "cls"], how="outer", indicator=True)
    return m[m["_merge"] == "left_only"].drop(columns="_merge"), m[m["_merge"] == "right_only"].drop(columns="_merge")


def completeness(raw: pd.DataFrame, a: pd.Timestamp, b: pd.Timestamp) -> list[str]:
    r = raw[(raw["date"] >= a) & (raw["date"] <= b)]
    base = raw[(raw["date"] >= a - pd.Timedelta(days=120)) & (raw["date"] < a)]
    out = []
    for m in ("TW", "TWO"):
        med = base[base["market"] == m].groupby("date").size().median()
        cnt = r[r["market"] == m].groupby("date").size()
        low = cnt[cnt < med * 0.9] if pd.notna(med) else cnt.iloc[0:0]
        out.append(f"- {m}：{len(cnt)} 個交易日，每日檔數中位 {int(cnt.median()) if len(cnt) else 0}（前 4 個月中位 {int(med) if pd.notna(med) else '—'}）"
                   + (f"；⚠ 檔數低於 90% 的日子：{', '.join(f'{d:%m-%d}({n})' for d, n in low.items())}" if len(low) else ""))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)
    month = a.month or prev_month()
    d0, d1 = month_range(month)

    raw = pd.read_parquet(SH / "raw_prices.parquet", columns=["ticker", "market", "date"])
    raw["date"] = pd.to_datetime(raw["date"])
    ca = pd.read_parquet(SH / "corp_actions.parquet")
    ca["date"] = pd.to_datetime(ca["date"])
    L = [f"# 自建上游月檢查：{month}", "", f"> 產生：{pd.Timestamp.now():%Y-%m-%d %H:%M}；資料最後一個實價日 {raw['date'].max().date()}。",
         "> 分工：程式先對帳（下面 1、2）；**只有 3 的 flag 才需要 AI 上網查**。AI 只查「發生了什麼事」並附出處，不判斷我們資料對不對。", ""]
    L += ["## 1. 完整性", *completeness(raw, d0, d1), ""]

    L += ["## 2. 事件對帳（官方清單 vs corp_actions）", ""]
    if a.offline:
        L += ["（--offline：略過）", ""]
    else:
        import selfhost_events as se
        try:
            off = pd.concat([se.fetch_official(d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d")),
                             se.fetch_official_actions(d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d"))], ignore_index=True)
            off = off[(pd.to_datetime(off["date"]) >= d0) & (pd.to_datetime(off["date"]) <= d1)]
            miss, extra = diff_events(off, ca[(ca["date"] >= d0) & (ca["date"] <= d1)])
            L += [f"官方該月事件 {len(off)} 筆（含多來源重複）；**官方有、我們沒有 {len(miss)} 筆**；我們有、官方沒有 {len(extra)} 筆。", ""]
            if len(miss):
                L += ["### 官方有、我們沒有（要補）", *[f"- {r.ticker} {r.date:%Y-%m-%d} {r.cls}（官方來源 {r.source}）" for r in miss.itertuples()], ""]
            if len(extra):
                L += ["### 我們有、官方沒有（FinMind 等第二來源；通常是官方表沒涵蓋的轉板／ETF，要抽查）",
                      *[f"- {r.ticker} {r.date:%Y-%m-%d} {r.cls}（來源 {r.source}）" for r in extra.itertuples()], ""]
        except Exception as e:  # noqa: BLE001
            L += [f"⚠ 官方抓取失敗：{e}（請稍後重跑）", ""]

    L += ["## 3. 事件簿裡歸不到解釋的項目（給 AI 查證）", ""]
    led_p = SH / "ledger.parquet"
    if not led_p.exists():
        L += ["（還沒有事件簿：先跑 `python scripts/selfhost_ledger.py`）", ""]
    else:
        led = pd.read_parquet(led_p)
        m = led[(led["date"] >= d0) & (led["date"] <= d1) & ((led["level"] == "flag") | ((led["kind"] == "gap") & (led["level"] == "warn")))]
        L += [f"本月共 {len(m)} 筆。", ""]
        for r in m.itertuples():
            L.append(f"- {r.ticker}｜{r.date:%Y-%m-%d}｜{r.kind}｜{r.title}")
        L += ["", "### 貼給 AI 的提示詞（上面第 3 節那份清單附在後面）", "",
              "```", "以下是台股個股在指定日期出現的異常價格跳動或缺資料。請**逐檔**上網查（證交所／櫃買中心／公開資訊觀測站公告為主），回答：",
              "1. 該日前後有沒有：除權息、現金增資、減資、變更股票面額、股票分割、合併／換股、轉板（上櫃↔上市）、暫停／恢復交易、全額交割、處置、終止上市？",
              "2. 有的話給：事件類型、事件日、**官方參考價或換股比率**、公告連結與日期。",
              "3. 查不到就明說查不到，**不要推測**；不要用新聞標題當依據。",
              "只要事實與出處，不需要建議。", "```", ""]
    out = OUTDIR / f"selfhost_monthly_review_{month}.md"
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"→ {out}（flag {0 if not led_p.exists() else len(m)} 筆）")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
