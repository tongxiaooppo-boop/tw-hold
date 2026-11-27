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

LEV_NOTE = "代號 L 結尾是正 2：追蹤單日兩倍，長期不等於兩倍。"

# 2026-11-27 使用者：正 2 跟市值型放同一張表（etf.json 的 group 不變，只有頁面合併）
SHOW_GROUPS: dict[str, tuple[str, ...]] = {"cap": ("cap", "lev"), "div": ("div",)}

EXPLAIN = """\
- **季線／半年線／年線**：收盤比過去 60／120／240 個交易日平均高（＋）或低（－）幾 %。用還原價（配息、分割都還原），所以跟看盤軟體不一定一樣。資料不夠天數顯示「—」。
- **近一年報酬**：含配息再投入，跟一年前比。
- **近一年配息率**：過去一年（到今天為止 365 天）除息的現金加總 ÷ 今天收盤；「次數」是這段期間除息幾次。上市未滿一年顯示「—」。
- 配息率高可能是價格下跌造成；配息不等於獲利，回測才看得到價格漲跌。
- 這頁只列數字，不是推薦。"""

YEARLY_NOTE = "每年除息的現金合計 ÷ 當年第一個交易日收盤。標 * 的是不完整年（上市當年或今年）。"

DCA_NOTE = """\
每月第一個交易日開盤買 {amount:,} 元（可買零股）；上市當月不買，從下個月開始。
「再投入」：配息在除息日按參考價買回同一檔（近似）。「領現金」：配息留現金，期末市值含累計現金。
「最慘帳面」：過程中市值比已投入金額最多少幾 %。「同期 0050」：同樣的扣款月份改買 0050（再投入）。
扣款不到 12 次的不列。"""

DCA_HEAD = ["代號", "期間", "次數", "已投入", "市值（再投入）", "年化（再投入）", "最慘帳面",
            "市值（領現金）", "年化（領現金）", "同期 0050 年化"]


def fmt_pos(v: float | None) -> str:
    """+3.1% / −2.0% / —（帶號、一位小數）。"""
    return "—" if v is None else f"{v * 100:+.1f}%"


def fmt_rate(v: float | None) -> str:
    """6.8% / —（不帶號、一位小數）。"""
    return "—" if v is None else f"{v * 100:.1f}%"


def _val(row: dict, key: str):
    return row["ma"]["240"] if key == "ma240" else row[key]


def sort_rows(rows: list[dict], key: str | None) -> list[dict]:
    """key=None → 依代號；'ma240' → 依 row['ma']['240']；其他 → row[key]。數值由大到小，None 排最後（維持代號順序）。"""
    by_code = sorted(rows, key=lambda r: r["code"])
    if key is None:
        return by_code
    have = [r for r in by_code if _val(r, key) is not None]
    none = [r for r in by_code if _val(r, key) is None]
    return sorted(have, key=lambda r: _val(r, key), reverse=True) + none


def page_slice(rows: list[dict], page: int, per: int = PER_PAGE) -> list[dict]:
    """page 從 1 起；超出範圍回空 list。"""
    if page < 1:
        return []
    return rows[(page - 1) * per: page * per]


def page_count(n: int, per: int = PER_PAGE) -> int:
    """至少 1。"""
    return max(1, -(-n // per))


def table_rows(rows: list[dict], group: str) -> list[list]:
    """etf.json 的 rows（已篩成該組、已排序）→ _vtable 的 body。
    第 0 欄＝(code, name) tuple（手機在代號下顯示名稱），第 1 欄 name，第 2 欄收盤（千分位、兩位小數），
    第 3～5 欄 ma 60/120/240 用 fmt_pos；cap/lev 第 6 欄 ret_1y 用 fmt_pos；
    div 第 6 欄 yield_1y 用 fmt_rate、第 7 欄 yield_1y_n（None → "—"，否則整數字串）。"""
    out = []
    for r in rows:
        line = [(r["code"], r["name"]), r["name"], f"{r['close']:,.2f}",
                fmt_pos(r["ma"]["60"]), fmt_pos(r["ma"]["120"]), fmt_pos(r["ma"]["240"])]
        if group == "div":
            n = r["yield_1y_n"]
            line += [fmt_rate(r["yield_1y"]), "—" if n is None else str(int(n))]
        else:
            line += [fmt_pos(r["ret_1y"])]
        out.append(line)
    return out


def yearly_table(yearly: dict, codes: list[str], names: dict[str, str]) -> tuple[list[str], list[list]]:
    """head＝["代號", 由舊到新的年份…]（取所有 codes 出現過的年份聯集）；
    cell＝fmt_rate(rate) + ("*" if partial)；該年沒值 → "—"。第 0 欄＝(code, name) tuple。"""
    years = sorted({y for c in codes for y in yearly.get(c, {})})
    body = []
    for c in codes:
        cells = []
        for y in years:
            cell = yearly.get(c, {}).get(y)
            cells.append("—" if cell is None else fmt_rate(cell["rate"]) + ("*" if cell["partial"] else ""))
        body.append([(c, names.get(c, c))] + cells)
    return ["代號"] + years, body


def dca_table(dca: dict, codes: list[str], names: dict[str, str]) -> list[list]:
    """依 DCA_HEAD 組列；reinvest 為 None 的代號整列略過。
    期間＝f"{start[:7]}～{end[:7]}"；已投入／市值用 f"{v/1e4:,.1f} 萬"；年化用 fmt_pos；最慘帳面＝reinvest 的 worst 用 fmt_pos；
    同期 0050＝bench_reinvest 的 irr（None → "—"，0050 自己也是 "—"）。第 0 欄＝(code, name) tuple。"""
    wan = lambda v: f"{v / 1e4:,.1f} 萬"  # noqa: E731
    out = []
    for c in codes:
        d = dca.get(c)
        if not d or d.get("reinvest") is None:
            continue
        re, ca, bn = d["reinvest"], d.get("cash"), d.get("bench_reinvest")
        out.append([(c, names.get(c, c)), f"{re['start'][:7]}～{re['end'][:7]}", str(re["buys"]),
                    wan(re["invested"]), wan(re["value"]), fmt_pos(re["irr"]), fmt_pos(re["worst"]),
                    wan(ca["value"]) if ca else "—", fmt_pos(ca["irr"]) if ca else "—",
                    fmt_pos(bn["irr"]) if bn else "—"])
    return out


# ── 每年年初買一筆（2026-11-27 框架，Opus 定）──────────────────────────────
ANNUAL_NOTE = """每年第一個交易日開盤買 {amount:,} 元（配息再投入），看到年底賺賠；上市當年不算，從隔年開始。
總表的「投入／損益」＝每年那筆都抱到今天的合計；「同期 0050」＝同樣年份改買 0050 的報酬。
今年還沒過完，標 *。"""

ANNUAL_HEAD = ["代號", "開始", "投入", "損益", "報酬", "同期 0050"]
ANNUAL_NUM: set[int] = {1, 2, 3, 4, 5}
ANNUAL_SRC: set[int] = {2}            # 投入：手機收掉（只剩 5 欄，不用往右拉）

ANNUAL_YEAR_HEAD = ["年", "年底市值", "損益", "報酬"]


def annual_table(annual: dict, codes: list[str], names: dict[str, str]) -> list[list]:
    """總表：依 codes 順序，annual[c] 為 None／不存在的略過。
    列＝[(c, 名稱), start, f"{invested/1e4:,.1f} 萬", f"{(value-invested)/1e4:+,.1f} 萬",
        fmt_pos(value/invested-1), fmt_pos(bench_value/invested-1) 或 "—"（bench_value 為 None）]。"""
    out = []
    for c in codes:
        d = annual.get(c)
        if not d:
            continue
        inv, val, bv = d["invested"], d["value"], d.get("bench_value")
        out.append([(c, names.get(c, c)), d["start"], f"{inv / 1e4:,.1f} 萬", f"{(val - inv) / 1e4:+,.1f} 萬",
                    fmt_pos(val / inv - 1), fmt_pos(bv / inv - 1) if bv is not None else "—"])
    return out


def annual_years(d: dict, amount: int) -> list[list]:
    """單檔逐年直表（新的在上）：[year + ("*" if partial), f"{amount*(1+ret):,.0f}", f"{pnl:+,.0f}", fmt_pos(ret)]。"""
    return [[y["year"] + ("*" if y["partial"] else ""), f"{amount * (1 + y['ret']):,.0f}", f"{y['pnl']:+,.0f}",
             fmt_pos(y["ret"])] for y in reversed(d["years"])]


# ── 高股息近 5 年配息（元）＋平均（2026-11-27 框架，Opus 定；版型照估值頁 EPS 年份列）──
DIV_CASH_TITLE = "近 5 年配息（元）"
DIV_CASH_NOTE = "每年除息現金合計（每單位；分割已換成現在單位）。上市當年不完整不算；標 * 的平均不到 5 年。"


def div_cash_table(div_cash: dict, codes: list[str], names: dict[str, str]) -> tuple[list[str], list[list]]:
    """head＝["代號", 年份後兩碼…(由舊到新，取第一個有資料代號的 years key), "平均"]；沒有任何代號有資料 → (["代號"], [])。
    依 codes 順序，div_cash 沒有的代號略過。列＝[(c, 名稱), 每年 f"{v:.2f}" 或 "—",
    平均 f"{avg:.2f}" + ("*" if n < 年數 else "")，avg 為 None → "—"]。"""
    have = [c for c in codes if c in div_cash]
    if not have:
        return ["代號"], []
    ys = list(div_cash[have[0]]["years"])
    head = ["代號"] + [y[-2:] for y in ys] + ["平均"]
    body = []
    for c in have:
        d = div_cash[c]
        avg = d.get("avg")
        avg_s = "—" if avg is None else f"{avg:.2f}" + ("*" if d["n"] < len(ys) else "")
        body.append([(c, names.get(c, c))] + [("—" if d["years"].get(y) is None else f"{d['years'][y]:.2f}") for y in ys] + [avg_s])
    return head, body


# ── 定期定額：可選起點（發行起／某年 1 月起）＋配息切換（2026-11-27 框架，Opus 定）──
DCA_FIRST = "發行起"
DCA_MODES: dict[str, str] = {"再投入": "reinvest", "領現金": "cash"}

DCA2_NOTE = """每月第一個交易日開盤買 {amount:,} 元（可買零股）。「發行起」：每檔從上市隔月開始，附同樣月份改買 0050 的年化；
選年份：從那年 1 月開始，只列那年以前已上市的。
「再投入」：配息在除息日買回同一檔（近似）；「領現金」：配息留現金，市值含累計現金。
「最慘帳面」：過程中市值比已投入最多少幾 %。扣款不到 12 次的不列。"""

DCA2_HEAD_FIRST = ["代號", "開始", "投入", "報酬", "年化", "最慘帳面", "同期 0050"]
DCA2_SRC_FIRST: set[int] = {2, 5}     # 手機收掉投入、最慘 → 5 欄
DCA2_HEAD_YEAR = ["代號", "投入", "市值", "報酬", "年化", "最慘帳面"]
DCA2_SRC_YEAR: set[int] = {1, 2}      # 手機收掉投入、市值 → 4 欄


def dca_start_options(dca_from: dict) -> list[str]:
    """[DCA_FIRST] + dca_from 的年份由舊到新。"""
    raise NotImplementedError


def dca2_rows(entries: dict, codes: list[str], names: dict[str, str], mode: str, first: bool) -> list[list]:
    """mode＝"reinvest"|"cash"。依 codes 順序；entries[c] 不存在或 entries[c][mode] 為 None → 略過。
    d＝entries[c][mode]；ret＝d["value"]/d["invested"]−1；wan＝f"{v/1e4:,.1f} 萬"。
    first=True（發行起，entries＝etf.json 的 dca）：[(c,名稱), d["start"][:7], wan(invested), fmt_pos(ret), fmt_pos(irr),
        fmt_pos(worst), fmt_pos(entries[c]["bench_"+mode]["irr"]) 或 "—"（bench 為 None）]
    first=False（某年，entries＝dca_from[年]）：[(c,名稱), wan(invested), wan(value), fmt_pos(ret), fmt_pos(irr), fmt_pos(worst)]"""
    raise NotImplementedError
