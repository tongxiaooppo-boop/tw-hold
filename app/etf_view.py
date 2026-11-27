"""ETF 分頁的純函式（不 import streamlit，好測）。streamlit_app._etf_page() 呼叫這裡組表格列，再交給 _vtable 畫。

框架 2026-11-27（Opus 定，實作者不得改簽名、欄名、文字常數；有問題停下回報）。
格式：位置／報酬用帶正負號百分比（+3.1%）；配息率不帶正負號（6.8%）；缺值一律 "—"。不上漲跌色。
"""
from __future__ import annotations

PER_PAGE = 8

HEAD: dict[str, list[str]] = {
    "cap": ["代號", "名稱", "收盤", "季線", "半年線", "年線", "近一年報酬"],
    "div": ["代號", "名稱", "收盤", "季線", "半年線", "年線", "近一年配息率", "次數"],
    "lev": ["代號", "名稱", "收盤", "季線", "半年線", "年線", "近一年報酬"],
}
NUM_COLS: set[int] = {2, 3, 4, 5, 6, 7}
SRC_COLS: set[int] = {1, 2}          # 名稱、收盤：桌機才顯示；手機把名稱放代號下方小字

# 排序選項：顯示名 → rows 裡的 key（None＝按代號）
SORTS: dict[str, dict[str, str | None]] = {
    "cap": {"代號": None, "年線位置": "ma240", "近一年報酬": "ret_1y"},
    "div": {"代號": None, "年線位置": "ma240", "近一年配息率": "yield_1y"},
    "lev": {"代號": None, "年線位置": "ma240", "近一年報酬": "ret_1y"},
}

LEV_NOTE = "追蹤單日兩倍，長期不等於兩倍。"

EXPLAIN = """\
- **季線／半年線／年線**：收盤比過去 60／120／240 個交易日平均高（＋）或低（－）幾 %。用還原價（配息、分割都還原），所以跟看盤軟體不一定一樣。資料不夠天數顯示「—」。
- **近一年報酬**：含配息再投入，跟一年前比。
- **近一年配息率**：過去一年（到今天為止 365 天）除息的現金加總 ÷ 今天收盤；「次數」是這段期間除息幾次。上市未滿一年顯示「—」。
- 配息率高可能是價格下跌造成；配息不等於獲利，回測才看得到價格漲跌。
- 這頁只列數字，不是推薦。"""

YEARLY_NOTE = "每年除息的現金合計 ÷ 當年第一個交易日收盤。標 * 的是不完整年（上市當年或今年）。"

DCA_NOTE = """\
每月第一個交易日扣款 {amount:,} 元，隔一個交易日開盤買（可買零股）；上市當月不買，從下個月開始。
「再投入」：配息在除息日按參考價買回同一檔（近似）。「領現金」：配息留現金，期末市值含累計現金。
「最慘帳面」：過程中市值比已投入金額最多少幾 %。「同期 0050」：同樣的扣款月份改買 0050（再投入）。
扣款不到 12 次的不列。"""

DCA_HEAD = ["代號", "期間", "次數", "已投入", "市值（再投入）", "年化（再投入）", "最慘帳面",
            "市值（領現金）", "年化（領現金）", "同期 0050 年化"]


def fmt_pos(v: float | None) -> str:
    """+3.1% / −2.0% / —（帶號、一位小數）。"""
    raise NotImplementedError


def fmt_rate(v: float | None) -> str:
    """6.8% / —（不帶號、一位小數）。"""
    raise NotImplementedError


def sort_rows(rows: list[dict], key: str | None) -> list[dict]:
    """key=None → 依代號；'ma240' → 依 row['ma']['240']；其他 → row[key]。數值由大到小，None 排最後（維持代號順序）。"""
    raise NotImplementedError


def page_slice(rows: list[dict], page: int, per: int = PER_PAGE) -> list[dict]:
    """page 從 1 起；超出範圍回空 list。"""
    raise NotImplementedError


def page_count(n: int, per: int = PER_PAGE) -> int:
    """至少 1。"""
    raise NotImplementedError


def table_rows(rows: list[dict], group: str) -> list[list]:
    """etf.json 的 rows（已篩成該組、已排序）→ _vtable 的 body。
    第 0 欄＝(code, name) tuple（手機在代號下顯示名稱），第 1 欄 name，第 2 欄收盤（千分位、兩位小數），
    第 3～5 欄 ma 60/120/240 用 fmt_pos；cap/lev 第 6 欄 ret_1y 用 fmt_pos；
    div 第 6 欄 yield_1y 用 fmt_rate、第 7 欄 yield_1y_n（None → "—"，否則整數字串）。"""
    raise NotImplementedError


def yearly_table(yearly: dict, codes: list[str], names: dict[str, str]) -> tuple[list[str], list[list]]:
    """head＝["代號", 由舊到新的年份…]（取所有 codes 出現過的年份聯集）；
    cell＝fmt_rate(rate) + ("*" if partial)；該年沒值 → "—"。第 0 欄＝(code, name) tuple。"""
    raise NotImplementedError


def dca_table(dca: dict, codes: list[str], names: dict[str, str]) -> list[list]:
    """依 DCA_HEAD 組列；reinvest 為 None 的代號整列略過。
    期間＝f"{start[:7]}～{end[:7]}"；已投入／市值用 f"{v/1e4:,.1f} 萬"；年化用 fmt_pos；最慘帳面＝reinvest 的 worst 用 fmt_pos；
    同期 0050＝bench_reinvest 的 irr（None → "—"，0050 自己也是 "—"）。第 0 欄＝(code, name) tuple。"""
    raise NotImplementedError
