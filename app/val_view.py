"""估值卡畫面資料層（估值 2.0 P4，規格 docs/val2/P4_spec.md §3；版面 docs/val2/card_demo.html）。

【框架由 Opus 定（2026-11-02），實作者不得改介面、dataclass、常數名與值】函式本體由 P4a 實作。
輸入只有 val_card.build_card 的回傳 dict（與 stock_class.json 頂層 meta）；輸出字串與表格，streamlit 端只負責畫。

鐵則（test_畫面不自己算 會掃）：
- 不 import streamlit／pandas／numpy；不做四則運算（+ 只准接字串）；不呼叫 sum／min／max／abs／round。
  百分比、千分位一律用 format spec（例 f"{v:+.1%}"）。
- 估值畫面所有數字只准經下面的 fmt_* 產生（§9-3 同值同字）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

PIN = "📌"
PIN_LEGEND = "📌＝主卡片上的數字"
COVERAGE_MIN_K = 100
MSG_NO_MULTIPLES = "估值倍數資料還沒產生（缺 multiples_hist／eps_revision／industry_pe），暫不顯示估值"
MORE_DETAIL = "詳見 📊 估值定位細節"
NOT_FORECAST = "試算不是預測、不是目標價"
POS = {"cheap": ("便宜區", "good"), "fair": ("合理區", "mid"), "dear": ("昂貴區", "bad")}
BUY_STATE = {"normal": "一般", "fwd_up": "前瞻上調"}
KIND_ZH = {"actual": "實際", "est": "試算"}
REV_ROLL = "窗口更換，本月不比較"
REV_REPORT = "改用財報，本月不比較"
REV_FLAT = "比上月持平"
# 展開區標題（§15 名稱；streamlit 端 expander 用這三個）
EXP_DETAIL = "📊 估值定位細節"
EXP_EXPLAIN = "📐 怎麼算"
EXP_TRIAL = "🔍 試算細節"


# ── 格式化（唯一來源）────────────────────────────────────────

def fmt_px(v) -> str:
    """價位：None／非有限 → "—"；|v| ≥ 100 → 千分位整數（"2,034"）；否則一位小數（"36.9"）。"""
    if v is None or v != v or v in (float("inf"), float("-inf")):
        return "—"
    return f"{v:,.0f}" if v >= 100 or v <= -100 else f"{v:,.1f}"


def fmt_eps(v) -> str:
    """EPS／每股淨值：兩位小數（"98.73"、"-1.20"）；None → "—"。不帶「元」。"""
    if v is None or v != v:
        return "—"
    return f"{v:,.2f}"


def fmt_mult(v, metric: str) -> str:
    """倍數：pe／pe_fwd 一位小數、pb 兩位小數，後接「 倍」（"20.6 倍"、"1.23 倍"）；None → "—"。"""
    if v is None or v != v:
        return "—"
    return f"{v:.2f} 倍" if metric == "pb" else f"{v:.1f} 倍"


def fmt_pct(v, signed: bool = True) -> str:
    """比例 → 百分比一位小數（signed："+3.1%"；否則 "16.5%"）；None → "—"。"""
    if v is None or v != v:
        return "—"
    return f"{v:+.1%}" if signed else f"{v:.1%}"


def fmt_yi(v) -> str:
    """金額（元）→ 億，千分位整數＋「 億」（"4,676 億"）；|值| < 10 億留一位小數（"6.4 億"）；None → "—"。
    本函式（與 fmt_shares）是唯一准許除以 1e8 的地方（test_畫面不自己算 白名單）。"""
    raise NotImplementedError


def fmt_shares(v) -> str:
    """股數（股）→ "259.3 億股"（一位小數）；None → "—"。"""
    raise NotImplementedError


def fmt_range(lo, hi) -> str:
    """購買區間 "2,034～2,592"（兩端都用 fmt_px）。"""
    return f"{fmt_px(lo)}～{fmt_px(hi)}"


# ── 資料型別 ───────────────────────────────────────────────

@dataclass(frozen=True)
class VTable:
    title: str | None
    kind: str                                  # "derive"（步驟｜數值｜來源／假設）| "kv"（項目｜內容）| "grid"
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]          # 每格 str，多行用 "\n"
    hl: tuple[int, ...] = ()                   # 整列底色的列號（📌 列、「＝ 試算 EPS」）


@dataclass(frozen=True)
class PriceCard:
    head: str                                  # "股價"
    head_sub: str                              # "2330 台積電｜高成長"
    price: str                                 # fmt_px
    price_sub: str                             # "現價（10/30）"
    tri_label: str | None                      # "三價（相對自身歷史）"
    tri_hint: str | None                       # "推導見 🔍 ③"
    tri: tuple[tuple[str, str], ...] | None    # (("便宜價","2,034"),("合理價","2,592"),("昂貴價","2,856"))
    tri_note: str | None                       # 沒有三價時一定有字
    pos: tuple[str, str] | None                # ("合理區","mid")
    base_text: str | None                      # "基準：近 4 季 EPS 98.73 元"
    extra: tuple[str, ...]                     # ROE／B 層／C 層的行
    buy: tuple[str, str] | None                # ("2,034～2,592", "一般｜現價在區間內")
    buy_label: str = "購買區間"
    buy_hint: str = "推導見 🔍 ④"
    fwd_label: str | None = None               # "前瞻三價（相對自身前瞻倍數）"；tier≠A → None
    fwd_tri: tuple[tuple[str, str], ...] | None = None
    fwd_note: str | None = None


@dataclass(frozen=True)
class EpsCard:
    kv: tuple[tuple[str, str, str], ...]       # (標題, 小字副標, 數值)
    growth_label: str                          # "年增率（對去年同期）"
    growth_table: VTable                       # grid：期間｜營收｜EPS


@dataclass(frozen=True)
class CardView:
    full: bool                                 # False＝不在估值範圍：只畫 price 卡
    coverage: str
    asof_line: str
    price: PriceCard
    eps: EpsCard | None
    pins: dict[str, str] = field(default_factory=dict)   # 卡片標籤 → 卡片上的字（不含單位）


# ── 卡片 ──────────────────────────────────────────────────

def coverage_line(meta: dict | None) -> str:
    """meta＝stock_class.json 頂層（count、coverage_mktcap_k）。規則見 P4_spec §3-1。"""
    raise NotImplementedError


def asof_line(card: dict) -> str:
    """"財報 2026Q2｜月營收至 2026-09｜股價 2026/10/30　｜　試算不是預測、不是目標價"（缺的段落省略）。
    財報＝eps.reported 最後一季；月營收＝growth key=="month" 的 period。"""
    raise NotImplementedError


def revision_text(rev: dict | None) -> str:
    """上修文字，規則見 P4_spec §3-1 EPS 卡第 3 點。"""
    raise NotImplementedError


def card_view(card: dict, label: str, meta: dict | None) -> CardView:
    """label＝"2330 台積電"；meta＝stock_class.json 頂層。規則見 P4_spec §3-1。"""
    raise NotImplementedError


# ── 展開區 ────────────────────────────────────────────────

def legend_row() -> str:
    return PIN_LEGEND


def detail_tables(card: dict) -> list[VTable]:
    """📊 估值定位細節（kv）。P4_spec §3-2。不放推導與三價。"""
    raise NotImplementedError


def explain_tables(card: dict) -> list[VTable]:
    """📐 怎麼算（kv「項目｜規則」）。P4_spec §3-2。不放這檔的任何數字。"""
    raise NotImplementedError


def trial_tables(card: dict) -> list[VTable]:
    """🔍 試算細節 ①～⑥。P4_spec §3-2（照 card_demo.html）。📌 列：數值欄 f"{PIN} {字}"、來源欄以 f"＝卡片『{標籤}』" 開頭。"""
    raise NotImplementedError
