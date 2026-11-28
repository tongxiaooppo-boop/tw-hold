"""回測報告分頁（2026-11-28 使用者要求）：上面放研究報告，下面放 app 其他分頁的回測報告。

- 研究報告：`app/reports/*.md` 靜態檔，`REPORTS` 決定順序。
- 其他回測報告：直接讀 `streamlit_app.BACKTEST_NOTES` 的 "backtest" 欄（原頁面照舊顯示，這裡不複製文字）。
- 每份報告都放展開區，點開才看得到全部（之後還會加報告）。
"""
from __future__ import annotations

from pathlib import Path

REPORT_DIR = Path(__file__).resolve().parent / "reports"

#: (標題, 檔名, 一行說明)；順序即顯示順序
REPORTS: list[tuple[str, str, str]] = [
    ("市值型 ETF 加碼①：找策略（每段大跌一份預算）", "etf_addon_1_search.md",
     "0050，59 個方案比「什麼時候加碼比較不傷」，挑出三個候選；含逐段明細、指標與均線統計。2026-11-28"),
    ("市值型 ETF 加碼②：每年年初一筆錢的帳戶回測", "etf_addon_2_account.md",
     "0050，三個候選＋年初全買，投入 10/20/30/40%；另計 -20%＋國安基金；含每一筆買進。2026-11-28"),
    ("市值型 ETF 加碼③：投入比例怎麼分", "etf_addon_3_weights.md",
     "0050，8 組比例 × 三策略與 59 方案重測；每級觸發幾年；隨機日期測試分批時機有沒有加分。2026-11-28"),
]

#: BACKTEST_NOTES 的 key → 顯示名稱（順序即顯示順序）；沒有 "backtest" 欄的自動略過
APP_BACKTESTS: list[tuple[str, str]] = [
    ("short", "短線"),
    ("swing", "長波段"),
    ("value", "價值"),
    ("deposit", "定存"),
]


def read_report(fname: str) -> str:
    p = REPORT_DIR / fname
    return p.read_text(encoding="utf-8") if p.exists() else f"（找不到報告檔 `{fname}`）"


def app_backtests(notes: dict) -> list[tuple[str, str]]:
    """回傳 [(顯示名稱, markdown)]，只收有回測內容的分頁。"""
    return [(label, notes[k]["backtest"]) for k, label in APP_BACKTESTS
            if k in notes and notes[k].get("backtest")]


def render(st, notes: dict) -> None:
    with st.container(key="report_page"):
        st.subheader("回測報告")
        st.caption("每份報告點開看全部。數字是研究當時的結果，不會每天重算。")
        st.markdown("#### 研究報告")
        for title, fname, desc in REPORTS:
            with st.expander(f"📊 {title}"):
                st.caption(desc)
                st.markdown(read_report(fname))
        bts = app_backtests(notes)
        if bts:
            st.markdown("#### 各分頁的回測報告")
            st.caption("跟各分頁頁尾「回測報告」展開區是同一份內容。")
            for label, md in bts:
                with st.expander(f"📊 {label}"):
                    st.markdown(md)
