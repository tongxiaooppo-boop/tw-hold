"""估值卡引擎（估值 2.0，upgrade_guide §5；取代 card-v2）。

【框架由 Opus 定（P3，2026-11-02），實作者不得改介面、常數名與值、回傳欄位、字串常數】函式本體由 P3 實作。
純函式，不讀檔（share_basis 事件表例外）。app 只讀 build_card 的回傳排版，不重算。

輸入（build_card）
- qf：單季財報（reference.loader.load_quarterly(live=True) 的該檔，已 corporate_actions.adjust_eps）。
  需要欄位 Q_COLS；缺欄補 NaN。
- rev：月營收（month "YYYY-MM"、revenue）。
- px：日線（date、close；原始收盤）。price＝最後一列 close。
- cls：stock_class.json 該檔 dict（ticker、industry、industry_group、type、display_type、state、subtags、
  why、decided_at、metrics）。None → tier D。
- mh：multiples_self.build_history 的該檔列（HIST_COLUMNS）；None／空 → 視為 0 個有效月。
- rev_hist：eps_revision.parquet 的該檔列；None／空 → revision＝{last_pct: None, streak: 0, direction: None}。
- industry_pe：industry_pe.json 的 "industries"（{產業: {median_pe, n, values}}）；None → B 層只給 pe_now。
- asof：評價日（app 傳今天台北日期）。所有窗口用 live=True。

決策順序（§5-1）
  1. cls None → D「這檔不在分類母體（上市櫃且財報 ≥12 季），不做估值」；q 少於 4 季 → D「財報不足 4 季」
  2. 算 windows＝eps_windows.windows(q, monthly, asof, live=True, financial=FIN)，
     FIN＝cls["industry_group"]=="financial" 或 type=="financial"
     checks＝detect.data_checks + share_checks + comparability_checks(cls, 採用的 stats) + estimate_checks；
     status＝detect.summarize(checks)。estimate stop → 近 4 季改用 windows["reported"]、前瞻＝None，
     eps["est_disabled"]＝stop 的 why。
  3. share_basis stop → D，reason＝stopped 的 why（PE、PB 都不給）
  4. route_pb(cls)（金融、循環・資產重、特殊且 metrics.special_triggers 含 "construction"）→
     PB 窗（kind "pb"、metric "pb"、cap None、全歷史）tier_a 過且 bvps_live 有值 → A-PB；否則 D
     （reason：PB_NO_HIST 或 BVPS_NA）。PB 路線不看近 4 季 EPS 正負。
  5. 近 4 季窗口不可用（data stop 或 ttm.ok False）→ D，reason＝f"近 4 季 EPS 不可用（{原因}）"
  6. 近 4 季 EPS ≤ 0 → C
  7. type ∈ {"special", "insufficient"} 或不在 PE_KIND → D（reason 用 D_REASONS）
  8. PE 窗 tier_a 過 → A-PE；否則 B
  route：第 4 步起 route_pb → "PB"，第 5、6、8 步 → "PE"；第 1、3、7 步 → None。
  comparability_checks 在決定採用哪組 stats 之後才加（D 層傳 None），status 最後才 summarize；
  estimate stop 要在第 5 步之前套用。notes 不重複（同句只加一次）。

A-PE
- kind＝PE_KIND[type]；cap＝pe_cap(type, mh, q, asof)
- 基準 EPS：cyclical 或 peak_block(cls) → min(近 4 季, eps_avg(q, 12)) 名稱 BASE_LOW（eps_avg 為 None 或 ≤0
  → 近 4 季、名稱 BASE_TTM，notes 加 NOTE_AVG_NA）；其餘 → 近 4 季，BASE_TTM。cyclical 另給 eps_5y_avg＝eps_avg(q, 20)。
- prices＝three_prices(基準, stats)；raw P20 ≥ cap → cheap／fair／dear 皆 None、position="na"、notes 加 NOTE_CAP_FLAT、
  buy_range None。
- fwd_prices（只在：非 cyclical、非 peak、前瞻可用、前瞻季≠近 4 季季別、前瞻 EPS ≥ EPS_MIN、
  PE_FWD 窗 n_valid ≥ multiples_self.VALID_MIN[kind 的 key]（不套緩衝）時給）＝three_prices(前瞻 EPS, 前瞻 stats)，
  base_name＝BASE_FWD；否則 None，前瞻季＝近 4 季季別時 notes 加 NOTE_FWD_SAME。
- buy_range＝buy_range(prices, fwd_prices, revision, price)
A-PB：prices＝three_prices(bvps_live, pb stats)，base_name＝BASE_BVPS；fwd_prices None；buy_range 只 normal；
  金融另給 roe＝roe_ttm(q)。
B：b_tier＝b_tier(price, 近 4 季 EPS, industry_pe.get(cls["industry"]))
C：c_tier＝c_tier(price, bvps_live(q), mh, asof)
所有層：growth＝growth_rows(...)、revision、quality（cfo_ni、accrual）、status、notes。
position：A 層 multiples.classify_position 同規則（price < cheap → cheap；≤ dear → fair…；任一 None → "na"）。

回傳欄位（§5-5，app 只讀這些；缺的一律給 None，不省略 key）
  ok(bool：cls 不是 None 就 True), tier, route("PE"|"PB"|None), reason(str|None), price, px_date("YYYY/MM/DD"),
  ticker, type, display_type, state(list), subtags(list), why(list), class_asof,
  eps{reported, ttm, fwd: EpsWindow.to_dict() | None, est_disabled: str|None},
  growth(list，見 growth_rows), prices(dict|None), position(str), fwd_prices(dict|None),
  buy_range(dict|None), revision(dict), b_tier(dict|None), c_tier(dict|None), roe(float|None),
  eps_5y_avg(float|None), quality{cfo_ni, accrual}, status(summarize 結果), notes(list[str]), version
prices／fwd_prices dict：{cheap, fair, dear, base, base_name, metric("pe"|"pe_fwd"|"pb"), mults(tuple 截斷後),
  raw_mults(tuple), capped(bool), cap(float|None), n_valid, n_loss, window("YYYY-MM～YYYY-MM")}
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from reference import share_basis as sb
from screener import detect as dt
from screener import eps_windows as ew
from screener import growth as gr
from screener import multiples_self as ms

CARD_VERSION = "card-v3-val2"
Q_COLS = ["revenue", "gross_profit", "op_income", "pretax_income", "net_income", "ni_parent", "eps",
          "capital_stock", "equity_parent", "total_assets", "ocf"]
TIERS = ("A", "B", "C", "D")
PE_KIND = {"normal": "normal", "growth": "growth", "cyclical": "cyclical"}
EPS_MIN = 0.05
HYST_MONTHS = 24            # tier_a 緩衝：往回模擬幾個完整月份
INDUSTRY_MIN_N = 8          # 【起始值】§12
C_PB_MIN = 12               # C 層 PB 位置至少要幾個有效月
HIGH_PE_YEARS = 5
HIGH_PE_LEVEL = 30.0

BASE_TTM = "近 4 季 EPS"
BASE_FWD = "前瞻 4 季 EPS"
BASE_LOW = "較低獲利情境"
BASE_BVPS = "每股淨值"
D_REASONS = {"special": "特殊類型（生技／併購重組等），歷史倍數不可比，不做估值",
             "insufficient": "財報不足 12 季，資料不足，不做估值"}
PB_NO_HIST = "股價淨值比自身歷史不足（有效月數未達門檻）"
BVPS_NA = "每股淨值推不出（缺歸母權益或股數）"
C_TEXT = "虧損中，不用獲利估價"
NOTE_CAP_FLAT = "歷史倍數高於上限，三價不給（只列原始倍數）"
NOTE_FWD_SAME = "新季營收未出，前瞻 4 季與近 4 季相同"
NOTE_AVG_NA = "3 年平均 EPS 不可用，較低獲利情境改用近 4 季"
BUY_NOTE_ABOVE = "現價高於購買區間上緣"
BUY_NOTE_FWD = "前瞻 EPS 連續上修，上緣改用前瞻合理價"


def build_card(qf: pd.DataFrame | None, rev: pd.DataFrame | None, px: pd.DataFrame | None,
               cls: dict | None, mh: pd.DataFrame | None, rev_hist: pd.DataFrame | None,
               industry_pe: dict | None, asof: pd.Timestamp) -> dict:
    """見模組說明。不得丟例外給呼叫端以外的情況：share_basis.EventsUnavailable 由 share_checks 轉成 stop。"""
    raise NotImplementedError


# ── 路由與分層 ────────────────────────────────────────────────────

def route_pb(cls: dict) -> bool:
    """type=="financial"；或 type=="cyclical" 且 "資產重" ∈ subtags；
    或 type=="special" 且 "construction" ∈ metrics.special_triggers。"""
    raise NotImplementedError


def peak_block(cls: dict) -> bool:
    """沿用 card-v2 `_peak_block` 判斷（"歷史高獲利區" ∈ state 且（疑似循環／僅單一景氣事件 ∈ subtags 或 max_dd ≥ 0.5））。"""
    raise NotImplementedError


def tier_a(mh: pd.DataFrame | None, kind: str, metric: str, asof: pd.Timestamp,
           cap: float | None) -> tuple[bool, dict]:
    """A 層門檻含緩衝（§4-3、§12 VALID_MIN／VALID_EXIT）。
    M0＝multiples_self.last_complete_month(asof)；對 m＝M0−(HYST_MONTHS−1) … M0 逐月：
      n_m＝window_stats(mh, kind, metric, asof=m 的月底, cap)["n_valid"]；
      state＝multiples_self.is_valid_tier_a(n_m, k, was_a=state)，起始 state=False；
      k＝kind（metric=="pb" 時 k="pb"）。
    回傳 (最後 state, window_stats(mh, kind, metric, asof, cap))。mh None／空 → (False, 該 stats 以空表算)。"""
    raise NotImplementedError


def pe_cap(typ: str, mh: pd.DataFrame | None, q: pd.DataFrame, asof: pd.Timestamp) -> float:
    """growth → MULT_CAP["growth"]；normal 且 high_pe_exception → MULT_CAP["normal_exc"]；其餘 MULT_CAP["normal"]。"""
    raise NotImplementedError


def high_pe_exception(mh: pd.DataFrame | None, q: pd.DataFrame, asof: pd.Timestamp) -> bool:
    """近 HIGH_PE_YEARS 個完整曆年（asof 年之前的 5 年）每一年：該年 4 季 EPS 都有限且合計 >0，
    且 mh 該年 valid_pe 的 pe 平均 > HIGH_PE_LEVEL（該年沒有有效月 → False）。全部成立才 True。"""
    raise NotImplementedError


# ── 價格 ──────────────────────────────────────────────────────────

def three_prices(base: float, stats: dict, metric: str, base_name: str, cap: float | None) -> dict:
    """{cheap, fair, dear}＝base × stats["mults"]（P20/P50/P80，截斷後）；任一倍數 None → 三價皆 None。
    其餘欄位照模組說明的 prices dict 填（window＝f"{start}～{end}"）。"""
    raise NotImplementedError


def position(price: float | None, prices: dict | None) -> str:
    """"cheap"／"fair"／"dear"／"na"：price < cheap → cheap；cheap ≤ price ≤ dear → fair；> dear → dear；
    任一 None → na（與 screener.multiples.classify_position 同規則）。"""
    raise NotImplementedError


def buy_range(prices: dict | None, fwd_prices: dict | None, revision: dict, price: float | None) -> dict | None:
    """§5-3。prices 或其 cheap／fair 為 None → None。
    low＝prices.cheap；state="fwd_up" 當且僅當 revision.direction=="up" 且 streak ≥ multiples_self.REV_STREAK
    且 fwd_prices 的 fair 不是 None 且 > prices.fair → high＝fwd_prices.fair、note＝BUY_NOTE_FWD；
    否則 state="normal"、high＝prices.fair、note＝None。high < low → None。
    price 不是 None 且 > high → note 改為 BUY_NOTE_ABOVE（fwd_up 時兩句用「；」接：BUY_NOTE_FWD；BUY_NOTE_ABOVE）。
    回傳 {low, high, state, note}。"""
    raise NotImplementedError


# ── B／C 層 ───────────────────────────────────────────────────────

def b_tier(price: float | None, eps_ttm: float, peers: dict | None) -> dict:
    """pe_now＝price ÷ eps_ttm（price None → None）。peers＝{median_pe, n, values}。
    peers None 或 n < INDUSTRY_MIN_N → {pe_now, industry_pct: None, eps_needed: None, n_peers: n 或 0, median_pe: None}；
    否則 industry_pct＝values 中 < pe_now 的比例（0～1）、eps_needed＝price ÷ median_pe、median_pe。"""
    raise NotImplementedError


def c_tier(price: float | None, bvps: float | None, mh: pd.DataFrame | None, asof: pd.Timestamp) -> dict:
    """pb_now＝price ÷ bvps（任一 None／≤0 → None）。歷史＝mh 中 month ≤ last_complete_month(asof) 且 valid_pb 的 pb。
    有效月 ≥ C_PB_MIN 且 pb_now 有值 → pb_pct＝歷史 pb < pb_now 的比例；否則 None。
    回傳 {pb_now, pb_pct, n_valid, text: C_TEXT}。"""
    raise NotImplementedError


# ── 基準數字 ──────────────────────────────────────────────────────

def bvps_live(q: pd.DataFrame) -> float | None:
    """與 multiples_self.build_history 的 bvps 同算法，但所有財報季都視為可見（live）：
    最近一季 equity_parent 有限 >0 的季 Q；股數＝Q 起往前共 5 季中最近一個 |eps| ≥ EPS_MIN 且 ni_parent÷eps 有限 >0 者；
    都推不出 → None。回傳 Q.equity_parent ÷ 股數。"""
    raise NotImplementedError


def eps_avg(q: pd.DataFrame, n: int) -> float | None:
    """最近 n 個曆季相鄰、EPS 都有限的實際季合計 ÷ (n/4)（年化平均）；用 screener.quarterly_prep.last_n_quarters；
    不足或斷季 → None。n=12 → 3 年平均；n=20 → 5 年平均。"""
    raise NotImplementedError


def roe_ttm(q: pd.DataFrame) -> float | None:
    """近 4 季（曆季相鄰）ni_parent 合計 ÷ 平均 equity_parent（第 −4 季與最新季兩期平均；任一缺 → 用有值的那期）。
    分母 ≤0 或 ni_parent 不全 → None。"""
    raise NotImplementedError


def quality(q: pd.DataFrame) -> dict:
    """近 4 季（曆季相鄰）：cfo_ni＝Σocf ÷ Σni_parent（Σni_parent ≤0 → None）；
    accrual＝(Σnet_income − Σocf) ÷ 平均 total_assets（第 −4 季與最新季；≤0 → None）。缺值 → None。"""
    raise NotImplementedError


# ── 年增率（§6、§9 EPS 卡表格「期間｜營收｜EPS」）──────────────────

def growth_rows(q: pd.DataFrame, monthly: pd.Series, ttm: ew.EpsWindow, fwd: ew.EpsWindow | None,
                asof: pd.Timestamp) -> list[dict]:
    """回傳列（順序固定，不適用的列不放）：每列 {key, period, kind, months_known, rev, eps}，
    rev／eps＝growth.Growth 的 dict（dataclasses.asdict）或 None（畫面印「—」）。
    1. key="month"：最新可見月 m（live：monthly 最後一個有限 >0 的月）；period＝"YYYY-MM"；
       rev＝yoy_revenue(m, 去年同月)；eps=None；kind=None、months_known=None。monthly 空 → 不放。
    2. key="last_q"：近 4 季末季 L（ttm.quarters[-1]）；period＝L.q；kind＝L.kind；
       months_known＝該季已有營收的月數（actual＝3）；
       rev＝yoy_revenue(L 季已有月份營收合計, 去年同月份合計)（任一月缺 → 該月不計入兩邊）；
       eps＝yoy_eps(L.eps, 去年同季實際 EPS)。ttm 不 ok → 不放。
    3. key="ttm"：period＝f"{第一季}～{最後一季}"；rev＝yoy_revenue(Σ近 4 季 rev, Σ一年前 4 季實際 revenue)；
       eps＝yoy_eps(ttm.eps, Σ一年前 4 季實際 EPS)；一年前任一季缺 → 該欄 yoy(…, None)（label "na"）。
    4. key="fwd"：只在 fwd 不是 None、ok、且季別 ≠ 近 4 季時放；rev=None；
       eps＝yoy_eps(fwd.eps, Σ一年前同 4 季實際 EPS)。"""
    raise NotImplementedError
