"""估值分類：類型＋狀態（估值分類框架，2026-11-01 Opus 定介面；本體待填）。

依據：`D:\\g\\claude\\估值定義定案草案.md` §1（分類）、§8.1（模組邊界）。
概念上取代 `app/valuation.py::stock_label`（本階段不動它）。

**純函式：不讀檔、不連網。** 全市場橫斷面（OROA 振幅分位、資產強度分位）與營收指數由呼叫端
（之後的 build_classification.py）先算好放進 ClassInputs；本模組提供算這些量的單檔函式
（oroa_series／oroa_amplitude／asset_intensity）與分位函式 cross_section_pct。

## 判斷順序（classify，取第一個成立的類型）
0 資料閘門：quarters 中 revenue 非 NaN 的列數 < MIN_QUARTERS → TYPE_INSUFFICIENT（不判狀態）
1 金融：industry_group == "financial" → TYPE_FINANCIAL（不看數字；狀態照判）
2 特殊退出 TYPE_SPECIAL（任一）：
    ① biotech 且近 SPECIAL_BIOTECH_WINDOW_Q 季中 eps < 0 的季數 ≥ SPECIAL_BIOTECH_LOSS_Q
    ② construction（一律）
    ③ 最新股本 ÷ 4 季前股本 − 1 的絕對值 > SPECIAL_CAP_CHANGE；
       或 最新 TTM 營收年增 > SPECIAL_REV_JUMP 且 股本 4 季變動 > SPECIAL_CAP_JUMP_WITH_REV
    命中的條件記在 metrics["special_triggers"]（list[str]：「biotech_loss」「construction」
    「cap_change」「rev_jump_cap」）。
3／4 景氣循環、高成長（見下），兩者都成立時用穿越循環檢定裁決：
    通過 → TYPE_GROWTH＋副標「具循環性」；不通過 → TYPE_CYCLICAL＋副標「成長型循環」。
5 其餘 TYPE_NORMAL；副標：TTM 營收 3 年 CAGR < NORMAL_SHRINK_CAGR3 →「營運收縮」；
    近 NORMAL_LOSS_YEARS 個完整曆年（4 季 eps 都有）中有年 EPS 合計 < 0 →「獲利不穩」。

## 景氣循環（§1.2）
  OROA(t)＝TTM op_income(t) ÷ 近 5 個季末 total_assets 平均（t−4..t，5 季都要有值且平均 > 0）。
  振幅＝近 CYCLE_WINDOW_Q 季 OROA 的 P90 − P10（線性插值＝pandas quantile 預設）。
  必要①：inp.oroa_amp_pct ≥ 1 − CYCLE_AMP_TOP_PCT（＝0.70）。
  必要②：op_drawdown(...)["contraction"] 為 True（任何一段 TTM 營業利益回撤 ≥ CYCLE_DRAWDOWN 且該段期間
         TTM 營收年增曾 < CYCLE_REV_CONTRACTION；max_dd 等為記錄那一段，見 op_drawdown）。
  輔助：inp.rev_beta ≥ CYCLE_BETA_MIN 或 inp.ind_sync ≥ CYCLE_SYNC_MIN（NaN 視為不成立）。
  必要兩條＋輔助 → 循環；只有必要兩條 → 循環＋副標「疑似循環」＋降級原因。
  循環涵蓋：cycle_coverage(OROA, 振幅) 為 False → 副標「循環未觀察完整」＋降級原因。
  資產重／輕：inp.asset_ta_rev_pct 或 inp.asset_capex_rev_pct ≥ 1 − ASSET_HEAVY_TOP_PCT（＝0.60）
    → 副標「資產重」，否則「資產輕」（只對循環類加；metrics["asset_heavy"] 一律給 bool）。
  結構衰退：op_drawdown(...)["recovered_half"] 為 False → 降級原因
    「回撤後未回到前高 50%（可能為結構衰退）」（暫定只降級不改類型，見待決）。

## 高成長（§1.3，全部成立）
  ①TTM 營收 3 年 CAGR ≥ GROWTH_REV_CAGR3 且 5 年 CAGR ≥ GROWTH_REV_CAGR5
    （5 年 CAGR 因歷史不足為 NaN → 跳過 5 年部分，加降級原因「營收歷史不足 5 年，5 年 CAGR 未檢查」）
  ②TTM op_income 3 年 CAGR ≥ GROWTH_OP_CAGR3（兩端都 > 0，否則不成立）
  ③近 GROWTH_NO_NEG_YOY_Q 季的季頻 TTM 營收年增最低 ≥ GROWTH_MIN_YOY（−10%；任一 NaN 或有 < −10% → 不成立）
  ④穿越循環檢定 crossing_test(...)：只在「同時判循環」時用來裁決（見判斷順序 3／4）。
  上市季數（inp.listed_quarters，None 時用 quarters 列數）< GROWTH_MIN_LISTED_Q → 降級原因「上市未滿 20 季」。
  CAGR(n 年)＝(TTM(t) ÷ TTM(t − 4n 季))^(1/n) − 1；任一端 ≤ 0 或 NaN → NaN。

## 狀態（§1.4；TYPE_INSUFFICIENT 不判，其餘類型都判；可同時多個，依下列順序放進 state）
  "虧損"         最新連續 4 季 eps 合計 ≤ 0
  "預估轉虧"     inp.eps_nc 非 None 且 ≤ 0，且不是"虧損"
  "獲利不穩"     最新 4 季任一 eps < 0；或 eps_nc 非 None 且 < 近 5 年（20 季）TTM EPS 中位數 × 0.2
                 （中位數 ≤ 0 或可用 TTM < 4 個 → 後半條不判）
  "轉機"/"谷底回升"  最新 4 季任一 eps < 0，且最新季 op_income > 0，且 TTM op(t) > TTM op(t−1) > TTM op(t−2)，
                 且 inp.g3 > 0（NaN 不成立）。非循環類叫"轉機"，TYPE_CYCLICAL 叫"谷底回升"。
  "歷史高獲利區"/"歷史低獲利區"  最新 OROA 在自身近 40 季 OROA（含最新，非 NaN 至少 CYCLE_MIN_OROA_OBS 個）的
                 rank(pct=True, method="average") ≥ PROFIT_ZONE_HIGH／≤ PROFIT_ZONE_LOW。
  "疑似景氣高檔"/"疑似景氣低檔"  只在 TYPE_CYCLICAL＋循環涵蓋完整＋歷史高（低）獲利區，且
                 inp.industry_rev_ttm_yoy 最後一個非 NaN 值 > 0（< 0）時另加（暫定，見待決）。
  "前瞻擴張"     eps_nc、eps_f4、TTM EPS 皆 > 0，eps_nc ÷ TTM EPS − 1 ≥ FWD_EXPAND_MIN，且 eps_f4 ≥ eps_nc。

## why（list[str]，依判斷順序；數字格式固定）
  資料閘門  "單季財報僅 {n} 季（< 12 季），不分類"
  金融      "產業為金融保險，走 PB"
  特殊①    "生技醫療近 12 季有 {k} 季虧損（≥ 8）"
  特殊②    "建材營造：營收認列不連續，只給 PB 位置"
  特殊③a   "股本 4 季變動 {chg:+.0%}（> 30%）"                 例 "股本 4 季變動 +50%（> 30%）"
  特殊③b   "TTM 營收年增 {yoy:+.0%} 且股本同步增 {chg:+.0%}，疑似併購/重組"
  循環①    "OROA 振幅 {amp:.1%}，位於全體前 {1−pct:.0%}"     例 "OROA 振幅 20.0%，位於全體前 10%"
  循環②    "TTM 營業利益自 {peak} 高點最多跌 {dd:.0%}，期間 TTM 營收年增最低 {yoy:+.0%}"
            （peak 用 "2017Q4" 格式）例 "TTM 營業利益自 2017Q4 高點最多跌 100%，期間 TTM 營收年增最低 -30%"
  循環輔助  "營收 beta {beta:.2f}（≥ 1.5）" 或 "產業同步度 {sync:.2f}（≥ 0.6）"（兩者都成立就兩條）
  疑似循環  "缺輔助條件（營收 beta {beta:.2f}、產業同步度 {sync:.2f}），列疑似循環"（NaN 印 "nan"）
  高成長①  "TTM 營收 3 年 CAGR {c3:.0%}、5 年 {c5:.0%}"（5 年 NaN 印 "—"）
  高成長②  "TTM 營業利益 3 年 CAGR {o3:.0%}"
  高成長③  "近 12 季 TTM 營收年增最低 {m:+.0%}（≥ -10%）"
  穿越      "市場營收收縮的 {n} 個月，個股營收年增皆 > 0" ／ "市場營收收縮的 {n} 個月，個股有 {k} 個月 ≤ 0"
  一般      "未符合景氣循環或高成長條件"
  狀態另起，每個狀態一條，例 "近四季 EPS 合計 -0.40 ≤ 0"、"最新 OROA 位於自身近 40 季第 100 百分位"。

## metrics（dict，鍵固定；算不出 → NaN／None）
  "asof"(Timestamp 最新季末), "n_quarters"(int), "oroa"(float 最新), "oroa_amp"(float),
  "oroa_pct_self"(float), "max_dd"(float), "dd_peak"(Timestamp|None), "dd_trough"(Timestamp|None),
  "dd_rev_yoy_min"(float), "contraction"(bool), "recovered_half"(bool|None), "coverage"(bool|None),
  "cyclical_necessary"(bool), "cyclical_aux"(bool), "asset_heavy"(bool),
  "rev_cagr3", "rev_cagr5", "op_cagr3"(float), "growth_core"(bool；①②③皆成立),
  "crossing"(dict：crossing_test 回傳), "ttm_eps"(float),
  "special_triggers"(list[str]),
  "stay_ok"(dict[str, bool])：遲滯「留任門檻」——鍵為類型，值＝若目前就是這類，本季是否仍可留任：
      TYPE_GROWTH：①改用 GROWTH_EXIT_CAGR3（3 年 ≥ 12%，不看 5 年）＋②③＋（同時循環時）穿越通過；
      TYPE_CYCLICAL：與進入門檻相同（草案未給退出門檻，見待決）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import copy
import dataclasses

import numpy as np
import pandas as pd

from screener import quarterly_prep as qp

RULE_VERSION = "class-v1-2026-11-01"

# ── 類型 ─────────────────────────────────────────────────────
TYPE_INSUFFICIENT = "insufficient"
TYPE_FINANCIAL = "financial"
TYPE_SPECIAL = "special"
TYPE_CYCLICAL = "cyclical"
TYPE_GROWTH = "growth"
TYPE_NORMAL = "normal"
TYPE_ZH = {TYPE_INSUFFICIENT: "資料不足", TYPE_FINANCIAL: "金融", TYPE_SPECIAL: "特殊",
           TYPE_CYCLICAL: "景氣循環", TYPE_GROWTH: "高成長", TYPE_NORMAL: "一般"}
# 不受遲滯（立即生效）的類型（暫定，見待決）
TYPES_NO_HYSTERESIS = (TYPE_INSUFFICIENT, TYPE_FINANCIAL, TYPE_SPECIAL)

# ── 狀態 ─────────────────────────────────────────────────────
STATE_LOSS = "虧損"
STATE_FWD_LOSS = "預估轉虧"
STATE_UNSTABLE = "獲利不穩"
STATE_TURNAROUND = "轉機"
STATE_TROUGH_RECOVERY = "谷底回升"
STATE_PROFIT_HIGH = "歷史高獲利區"
STATE_PROFIT_LOW = "歷史低獲利區"
STATE_CYCLE_HIGH = "疑似景氣高檔"
STATE_CYCLE_LOW = "疑似景氣低檔"
STATE_FWD_EXPAND = "前瞻擴張"
STATES_IMMEDIATE = (STATE_LOSS,)    # 遲滯：只有「虧損」立即生效，其餘連 2 次一致

# ── 副標 ─────────────────────────────────────────────────────
SUB_SUSPECT_CYCLE = "疑似循環"
SUB_CYCLE_INCOMPLETE = "循環未觀察完整"
SUB_GROWTH_CYCLE = "成長型循環"        # 循環＋高成長，穿越不通過 → 判循環
SUB_CYCLICAL_GROWTH = "具循環性"       # 循環＋高成長，穿越通過 → 判高成長
SUB_ASSET_HEAVY = "資產重"
SUB_ASSET_LIGHT = "資產輕"
SUB_SHRINKING = "營運收縮"
SUB_UNSTABLE = "獲利不穩"

# ── 門檻（名稱照草案；【經驗】＝初值，上線後校準）────────────────
MIN_QUARTERS = 12                  # §1.1 第 0 步
CYCLE_WINDOW_Q = 40                # 近 40 季
OROA_ASSET_AVG_Q = 5               # 近 5 季末總資產平均
CYCLE_MIN_OROA_OBS = 12            # 【待決】振幅／自身分位最少要幾個 OROA 值，草案未定
CYCLE_AMP_TOP_PCT = 0.30           # 振幅位於全體前 30%【經驗】
CYCLE_DRAWDOWN = 0.50              # 營運回撤 ≥ 50%【經驗】
CYCLE_REV_CONTRACTION = -0.10      # 同期 TTM 營收年增曾 < −10%【經驗】
CYCLE_BETA_MIN = 1.5               # 輔助：市場營收 beta ≥ 1.5【經驗】
CYCLE_SYNC_MIN = 0.6               # 輔助：產業同步度 ≥ 0.6【經驗】
CYCLE_COVERAGE_LEG = 0.50          # 循環涵蓋：每段幅度 ≥ 振幅 × 50%
CYCLE_RECOVER_HALF = 0.50          # 回撤後回到前高 50% 才算回升
ASSET_HEAVY_TOP_PCT = 0.40         # 資產強度任一在全體前 40% ＝ 資產重【經驗】
ASSET_CAPEX_Q = 20                 # 近 5 年 capex
ASSET_CAPEX_MIN_Q = 8              # 【待決】capex 強度最少季數
GROWTH_REV_CAGR3 = 0.20            # 【經驗】
GROWTH_REV_CAGR5 = 0.12            # 【經驗】
GROWTH_OP_CAGR3 = 0.20             # 【經驗】
GROWTH_NO_NEG_YOY_Q = 12
GROWTH_MIN_YOY = -0.10             # ③ 近 12 季 TTM 營收年增最低須 ≥ −10%（原「從未 < 0」放寬）【經驗】
GROWTH_EXIT_CAGR3 = 0.12           # 退出門檻（遲滯）
GROWTH_MIN_LISTED_Q = 20           # 上市 < 20 季降一級
SPECIAL_BIOTECH_WINDOW_Q = 12
SPECIAL_BIOTECH_LOSS_Q = 8
SPECIAL_CAP_CHANGE = 0.30
SPECIAL_REV_JUMP = 1.00
SPECIAL_CAP_JUMP_WITH_REV = 0.10   # 【待決】「股本同步大增」草案未給數字，暫定 10%
NORMAL_SHRINK_CAGR3 = -0.05
NORMAL_LOSS_YEARS = 5
UNSTABLE_EPSNC_REL = 0.2
UNSTABLE_MEDIAN_Q = 20             # 近 5 年 TTM EPS
FWD_EXPAND_MIN = 0.10              # 【經驗】
PROFIT_ZONE_HIGH = 0.80
PROFIT_ZONE_LOW = 0.20
HYST_CONFIRM_Q = 2                 # 連續 2 季一致才切換
HYST_LOCK_Q = 4                    # 切換後鎖 4 季（含切換當季，最早第 T+4 季才可再切）

QUARTER_COLS = ("revenue", "op_income", "eps", "total_assets", "capital_stock", "capex")
QUARTER_COLS_OPTIONAL = ("equity_parent",)   # 選用：資產負債表歸母權益；有此欄才啟用特殊③的權益條件
SPECIAL_EQUITY_RATIO = 0.50                  # 權益變動須 ≥ 股本變動 × 此比例才算真增資/併購（權益只因獲利累積增加、股本卻大增＝分割/配股）【經驗】
SPECIAL_EQUITY_JUMP = 0.30                   # 股本大增時，同 4 季窗權益變動（絕對值）也須 > 30%【經驗】

HISTORY_COLS = ("ticker", "decided_at", "candidate_type", "final_type", "switched",
                "candidate_states", "final_states")
STATE_SEP = "|"


@dataclass
class ClassInputs:
    """classify() 的輸入（欄位與型別固定，不准改）。

    quarters：單一檔，index＝period_end（季末 Timestamp，嚴格遞增），欄位 QUARTER_COLS 全部**單季**
      （capex 已用 quarterly_prep.to_single_quarter_cashflow 差分；capex 正負號不拘，取絕對值用）。
      缺季的列可以不存在；缺值 NaN。
      另可有選用欄 QUARTER_COLS_OPTIONAL（equity_parent＝資產負債表歸母權益，非損益表的 ni_parent）：
      有此欄時，特殊③a 的「股本大增」還須同 4 季窗權益變動絕對值 > SPECIAL_EQUITY_JUMP
      （任一端 NaN 或 ≤ 0 → 不成立；避免分割／配股被誤判成併購）；沒有此欄則只看股本。
    oroa_amp_pct／asset_ta_rev_pct／asset_capex_rev_pct：全市場橫斷面分位（cross_section_pct 的輸出，
      0～1，越大越前面）；算不出 NaN（NaN 視為不成立）。
    rev_beta、ind_sync：rev_index.revenue_beta／industry_sync；NaN 視為不成立。
    stock_rev_ttm_yoy、market_rev_ttm_yoy、industry_rev_ttm_yoy：月頻（index 月初 Timestamp）
      TTM 營收年增；industry 為「排除自己」版本。可為空 Series。
    g3：rev_momentum 最新月的 g3；NaN 視為不成立。
    eps_nc、eps_f4：前瞻 EPS（eps_nowcast 尚未實作，None＝不判相關狀態）。
    listed_quarters：上市季數；None 時以 quarters 列數代替。
    """
    ticker: str
    industry_group: str
    quarters: pd.DataFrame
    oroa_amp_pct: float = float("nan")
    asset_ta_rev_pct: float = float("nan")
    asset_capex_rev_pct: float = float("nan")
    rev_beta: float = float("nan")
    ind_sync: float = float("nan")
    stock_rev_ttm_yoy: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    market_rev_ttm_yoy: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    industry_rev_ttm_yoy: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    g3: float = float("nan")
    eps_nc: float | None = None
    eps_f4: float | None = None
    listed_quarters: int | None = None


@dataclass
class Classification:
    """classify() 的輸出（欄位固定）。type 為 TYPE_*；state 依檔頭順序；subtags 依判斷順序、不重複；
    why 格式見檔頭；metrics 鍵見檔頭；reasons_degrade 為降級原因中文字串（不重複）。"""
    type: str
    state: list[str] = field(default_factory=list)
    subtags: list[str] = field(default_factory=list)
    why: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    reasons_degrade: list[str] = field(default_factory=list)
    rule_version: str = RULE_VERSION


# ── 內部小工具 ────────────────────────────────────────────────

def _on_calendar(s: pd.Series) -> pd.Series:
    """展開成連續曆季（缺季補 NaN）；季末 index 才有意義。"""
    if s.empty:
        return s
    return s.reindex(pd.date_range(s.index[0], s.index[-1], freq="QE"))


def _lag(s: pd.Series, k: int) -> pd.Series:
    """往前 k 個**曆季**的值（缺季為 NaN），index 與 s 相同。"""
    if s.empty:
        return s
    return _on_calendar(s).shift(k).reindex(s.index)


def _ttm_yoy(ttm_s: pd.Series) -> pd.Series:
    """季頻 TTM 年增＝TTM(t) ÷ TTM(t−4 曆季) − 1；分母 ≤ 0 或 NaN → NaN。"""
    prev = _lag(ttm_s, 4)
    return (ttm_s / prev.where(prev > 0) - 1.0).astype(float)


def _qlabel(ts: pd.Timestamp) -> str:
    """季末 Timestamp → "2017Q4"。"""
    return f"{ts.year}Q{ts.quarter}"


def _qord(ts: pd.Timestamp) -> int:
    """季末 Timestamp → 曆季序號（相鄰季差 1）。"""
    return pd.Timestamp(ts).year * 4 + pd.Timestamp(ts).quarter


def _full_years_eps(eps: pd.Series) -> dict[int, float]:
    """曆年 → 該年 4 季 EPS 合計（只收 4 季都有值的完整年）。"""
    out: dict[int, float] = {}
    s = eps.dropna()
    for y, g in s.groupby(s.index.year):
        if len(g) == 4:
            out[int(y)] = float(g.sum())
    return out


def _last_nonnan(s: pd.Series) -> float:
    s = s.dropna()
    return float(s.iloc[-1]) if len(s) else float("nan")


# ── 單檔計算（build 用來算橫斷面，classify 內部也用）─────────────────

def oroa_series(quarters: pd.DataFrame) -> pd.Series:
    """OROA(t)＝TTM op_income(t) ÷ mean(total_assets 在 t−4..t 共 5 個曆季)。

    TTM 用 quarterly_prep.ttm（連續 4 曆季）；總資產 5 個曆季都要在 index 且非 NaN、平均 > 0，否則 NaN。
    輸出與 quarters 同 index、name="oroa" 的 float Series。缺欄 → KeyError。
    """
    op_ttm = qp.ttm(quarters["op_income"].astype(float))
    ta = quarters["total_assets"].astype(float)
    if ta.empty:
        return pd.Series(dtype=float, name="oroa")
    avg = _on_calendar(ta).rolling(OROA_ASSET_AVG_Q, min_periods=OROA_ASSET_AVG_Q).mean()
    avg = avg.reindex(quarters.index)
    avg = avg.where(avg > 0)                      # ≤ 0 或 NaN → NaN
    out = (op_ttm / avg).astype(float)
    out.name = "oroa"
    return out


def oroa_amplitude(oroa: pd.Series, window: int = CYCLE_WINDOW_Q,
                   min_obs: int = CYCLE_MIN_OROA_OBS) -> float:
    """近 window 列（最後 window 列，含 NaN 列）中非 NaN 的 OROA 的 P90 − P10
    （pandas Series.quantile 預設線性插值）。非 NaN 個數 < min_obs → NaN。不丟例外。"""
    vals = oroa.tail(window).dropna()
    if len(vals) < min_obs or len(vals) == 0:
        return float("nan")
    return float(vals.quantile(0.9) - vals.quantile(0.1))


def op_drawdown(quarters: pd.DataFrame, window: int = CYCLE_WINDOW_Q) -> dict:
    """TTM op_income 的營運回撤與同期營收收縮（「任何一段」語意）。

    TTM op、TTM 營收與其年增先用全部列算好，再只看最後 window 列。對每個 t：peak(t)＝窗內 t 以前（含）TTM op 最大值所在季（同值取**最晚**那季，即滾動最高點）；
      peak 值 > 0 時 dd(t)＝1 − TTM_op(t) ÷ peak 值（可 > 1，代表跌到負）；否則不算。
    每個 t 的 rev_yoy_min(t)＝[peak(t), t] 期間（含兩端）季頻 TTM 營收年增（TTM(t)/TTM(t−4)−1）的最小值。
    **條件②（contraction）成立＝存在某個 t，dd(t) ≥ CYCLE_DRAWDOWN 且 rev_yoy_min(t) < CYCLE_REV_CONTRACTION**
      （2026-11-01 改：原本只看 max_dd 那一段；航運型早期有一次不縮營收的深回撤、後期才有營收大減的深回撤，舊語意會漏判）。
    記錄的那一段：有滿足條件的 t → 其中 dd 最大者（同值取最早 t）；沒有 → 整體最大回撤那一段（舊行為），contraction False。
    max_dd／dd_peak／dd_trough／rev_yoy_min 都是記錄那一段的值。
    recovered_half＝記錄那段 trough 之後（不含）任一 TTM op ≥ 該段 peak 值 × CYCLE_RECOVER_HALF；trough 是最後一季 → None。

    回傳 {"max_dd": float, "dd_peak": Timestamp|None, "dd_trough": Timestamp|None,
          "rev_yoy_min": float, "contraction": bool, "recovered_half": bool|None}
    無可算點 → max_dd NaN、contraction False、其餘 None／NaN。
    """
    nan = float("nan")
    empty = {"max_dd": nan, "dd_peak": None, "dd_trough": None, "rev_yoy_min": nan,
             "contraction": False, "recovered_half": None}
    if len(quarters) == 0:
        return empty
    op_ttm = qp.ttm(quarters["op_income"].astype(float))
    rev_ttm = qp.ttm(quarters["revenue"].astype(float))
    yoy = _ttm_yoy(rev_ttm)
    win = op_ttm.tail(window)

    peak_val, peak_t = None, None
    best_all = None          # (dd, peak, trough)：整體最大回撤
    best_ok = None           # (dd, peak, trough)：滿足「dd ≥ 門檻 且 期間營收收縮」者中 dd 最大
    for t, v in win.items():
        if pd.isna(v):
            continue
        if peak_val is None or v >= peak_val:        # 同值取最晚
            peak_val, peak_t = float(v), t
        if peak_val > 0:
            dd = 1.0 - float(v) / peak_val
            if best_all is None or dd > best_all[0]:       # 同值取最早
                best_all = (dd, peak_t, t)
            if dd >= CYCLE_DRAWDOWN - 1e-12 and (best_ok is None or dd > best_ok[0]):
                seg_t = yoy.loc[peak_t:t].dropna()
                if len(seg_t) and float(seg_t.min()) < CYCLE_REV_CONTRACTION:
                    best_ok = (dd, peak_t, t)
    if best_all is None:
        return empty

    contraction = best_ok is not None
    best_dd, best_peak, best_trough = best_ok if contraction else best_all
    seg = yoy.loc[best_peak:best_trough].dropna()
    rev_min = float(seg.min()) if len(seg) else nan
    peak_value = float(win.loc[best_peak])
    if best_trough == win.index[-1]:
        recovered = None
    else:
        after = win.loc[win.index > best_trough].dropna()
        recovered = bool((after >= peak_value * CYCLE_RECOVER_HALF).any())
    return {"max_dd": float(best_dd), "dd_peak": best_peak, "dd_trough": best_trough,
            "rev_yoy_min": rev_min, "contraction": contraction,
            "recovered_half": recovered}


def cycle_coverage(oroa: pd.Series, amp: float, window: int = CYCLE_WINDOW_Q) -> bool:
    """循環涵蓋檢查：最後 window 列的非 NaN OROA 中，存在 i < j < k 使
      高→低→高：x_i − x_j ≥ thr 且 x_k − x_j ≥ thr，或
      低→高→低：x_j − x_i ≥ thr 且 x_j − x_k ≥ thr，
    其中 thr＝amp × CYCLE_COVERAGE_LEG。amp 為 NaN 或 ≤ 0 → False。"""
    if amp is None or pd.isna(amp) or amp <= 0:
        return False
    x = oroa.tail(window).dropna().to_numpy(dtype=float)
    if len(x) < 3:
        return False
    thr = amp * CYCLE_COVERAGE_LEG - 1e-12           # 容許浮點誤差（剛好等於門檻算成立）
    pre_max = np.maximum.accumulate(x)
    pre_min = np.minimum.accumulate(x)
    suf_max = np.maximum.accumulate(x[::-1])[::-1]
    suf_min = np.minimum.accumulate(x[::-1])[::-1]
    for j in range(1, len(x) - 1):
        if pre_max[j - 1] - x[j] >= thr and suf_max[j + 1] - x[j] >= thr:
            return True
        if x[j] - pre_min[j - 1] >= thr and x[j] - suf_min[j + 1] >= thr:
            return True
    return False


def asset_intensity(quarters: pd.DataFrame) -> dict:
    """資產強度（橫斷面分位前的原始值）。

    ta_rev＝最新一列 total_assets ÷ 最新 TTM 營收（TTM ≤ 0 或 NaN → NaN）。
    capex_rev＝Σ|capex| ÷ Σrevenue，取最後 ASSET_CAPEX_Q 列中 capex 與 revenue 都非 NaN 的列；
      這樣的列 < ASSET_CAPEX_MIN_Q 或 Σrevenue ≤ 0 → NaN。
    回傳 {"ta_rev": float, "capex_rev": float}。
    """
    nan = float("nan")
    ta_rev = nan
    if len(quarters):
        rev_ttm = qp.ttm(quarters["revenue"].astype(float))
        last_rev, last_ta = rev_ttm.iloc[-1], quarters["total_assets"].iloc[-1]
        if pd.notna(last_rev) and last_rev > 0 and pd.notna(last_ta):
            ta_rev = float(last_ta) / float(last_rev)
    tail = quarters[["capex", "revenue"]].tail(ASSET_CAPEX_Q).dropna()
    capex_rev = nan
    if len(tail) >= ASSET_CAPEX_MIN_Q and tail["revenue"].sum() > 0:
        capex_rev = float(tail["capex"].abs().sum() / tail["revenue"].sum())
    return {"ta_rev": ta_rev, "capex_rev": capex_rev}


def cross_section_pct(values: pd.Series) -> pd.Series:
    """橫斷面分位：values.rank(pct=True, method="average")；NaN 保持 NaN、不計入分母。
    index 原樣（通常是 ticker）。"""
    return values.rank(pct=True, method="average")


def ttm_cagr(ttm_series: pd.Series, years: int) -> float:
    """CAGR＝(最後一列值 ÷ 4×years 個曆季前那一季的值)^(1/years) − 1。
    ttm_series 的 index 為季末 Timestamp；那一季不在 index、任一端 NaN 或 ≤ 0 → NaN。"""
    nan = float("nan")
    if len(ttm_series) == 0:
        return nan
    t_last = ttm_series.index[-1]
    t_base = t_last - pd.offsets.QuarterEnd(4 * years)
    if t_base not in ttm_series.index:
        return nan
    end, start = ttm_series.iloc[-1], ttm_series.loc[t_base]
    if pd.isna(end) or pd.isna(start) or end <= 0 or start <= 0:
        return nan
    return float((end / start) ** (1.0 / years) - 1.0)


def crossing_test(stock_rev_ttm_yoy: pd.Series, market_rev_ttm_yoy: pd.Series,
                  asof: pd.Timestamp | None = None, window_months: int = CYCLE_WINDOW_Q * 3) -> dict:
    """穿越循環檢定（§1.3 ④）。

    看 (asof − window_months 個月, asof] 內（asof 預設＝market 最後一個月），
    market < 0 且 stock 非 NaN 的月份集合 M。
      n＝|M|，k＝M 中 stock ≤ 0 的月數。
      n == 0 → {"n": 0, "k": 0, "passed": True, "executed": False}（暫定：無市場收縮月視為通過但標未執行）
      否則 passed＝(k == 0)，executed＝True。
    回傳 {"n": int, "k": int, "passed": bool, "executed": bool}。
    """
    none = {"n": 0, "k": 0, "passed": True, "executed": False}
    market = market_rev_ttm_yoy.dropna()
    if asof is None:
        if len(market) == 0:
            return none
        asof = market.index[-1]
    lo = asof - pd.DateOffset(months=window_months)
    shrink = market[(market.index > lo) & (market.index <= asof) & (market < 0)]
    stk = stock_rev_ttm_yoy.reindex(shrink.index).dropna()
    n = int(len(stk))
    if n == 0:
        return none
    k = int((stk <= 0).sum())
    return {"n": n, "k": k, "passed": k == 0, "executed": True}


# ── 主函式 ────────────────────────────────────────────────────

def classify(inp: ClassInputs) -> Classification:
    """依檔頭「判斷順序」「景氣循環」「高成長」「狀態」產生本季**候選**分類（未套遲滯）。

    - TYPE_SPECIAL 仍判狀態；TYPE_INSUFFICIENT 的 state＝[]、subtags＝[]。
    - 穿越檢定未執行（crossing["executed"] False）且需要它裁決時 → 視為通過，
      加降級原因「期間無市場營收收縮月，穿越檢定未執行」。
    - 疑似循環 → 降級原因「疑似循環（缺輔助條件）」；循環未觀察完整 → 降級原因「循環未觀察完整」。
    - metrics["asof"]＝quarters 最後一列的 period_end（遲滯會用到）。
    錯誤：quarters 缺 QUARTER_COLS 任一欄 → KeyError；index 不遞增 → ValueError。
    """
    q = inp.quarters
    missing = [c for c in QUARTER_COLS if c not in q.columns]
    if missing:
        raise KeyError(f"quarters 缺欄位：{missing}")
    if not (q.index.is_monotonic_increasing and q.index.is_unique):
        raise ValueError("quarters index 必須嚴格遞增")

    nan = float("nan")
    n_rev = int(q["revenue"].notna().sum())
    metrics: dict = {
        "asof": q.index[-1] if len(q) else None, "n_quarters": n_rev,
        "oroa": nan, "oroa_amp": nan, "oroa_pct_self": nan, "max_dd": nan,
        "dd_peak": None, "dd_trough": None, "dd_rev_yoy_min": nan, "contraction": False,
        "recovered_half": None, "coverage": None, "cyclical_necessary": False,
        "cyclical_aux": False, "asset_heavy": False, "rev_cagr3": nan, "rev_cagr5": nan,
        "op_cagr3": nan, "growth_core": False, "crossing": {}, "ttm_eps": nan,
        "special_triggers": [], "stay_ok": {},
    }
    # 0 資料閘門
    if n_rev < MIN_QUARTERS:
        return Classification(type=TYPE_INSUFFICIENT, metrics=metrics,
                              why=[f"單季財報僅 {n_rev} 季（< {MIN_QUARTERS} 季），不分類"])

    rev = q["revenue"].astype(float)
    op = q["op_income"].astype(float)
    eps = q["eps"].astype(float)
    why: list[str] = []
    degrade: list[str] = []
    subtags: list[str] = []

    rev_ttm = qp.ttm(rev)
    op_ttm = qp.ttm(op)
    eps_ttm = qp.ttm(eps)
    yoy_q = _ttm_yoy(rev_ttm)

    # ── 指標（不論最後判成什麼類型都算，狀態與 metrics 要用）──
    oroa = oroa_series(q)
    amp = oroa_amplitude(oroa)
    dd = op_drawdown(q)
    cover = cycle_coverage(oroa, amp)
    crossing = crossing_test(inp.stock_rev_ttm_yoy, inp.market_rev_ttm_yoy)
    c3, c5 = ttm_cagr(rev_ttm, 3), ttm_cagr(rev_ttm, 5)
    o3 = ttm_cagr(op_ttm, 3)
    ttm_eps_now = _last_nonnan(eps_ttm.tail(1))

    amp_pct = inp.oroa_amp_pct
    nec1 = bool(pd.notna(amp_pct) and amp_pct >= (1 - CYCLE_AMP_TOP_PCT) - 1e-12)
    nec2 = bool(pd.notna(dd["max_dd"]) and dd["max_dd"] >= CYCLE_DRAWDOWN - 1e-12
                and dd["contraction"])
    cyc_ok = nec1 and nec2
    beta_ok = bool(pd.notna(inp.rev_beta) and inp.rev_beta >= CYCLE_BETA_MIN)
    sync_ok = bool(pd.notna(inp.ind_sync) and inp.ind_sync >= CYCLE_SYNC_MIN)
    aux_ok = beta_ok or sync_ok
    heavy_thr = (1 - ASSET_HEAVY_TOP_PCT) - 1e-12
    asset_heavy = bool((pd.notna(inp.asset_ta_rev_pct) and inp.asset_ta_rev_pct >= heavy_thr)
                       or (pd.notna(inp.asset_capex_rev_pct)
                           and inp.asset_capex_rev_pct >= heavy_thr))

    # 高成長 ①②③
    yoy_tail = yoy_q.tail(GROWTH_NO_NEG_YOY_Q)
    no_neg = bool(len(yoy_tail) >= GROWTH_NO_NEG_YOY_Q and yoy_tail.notna().all()
                  and (yoy_tail >= GROWTH_MIN_YOY - 1e-12).all())
    cond1 = bool(pd.notna(c3) and c3 >= GROWTH_REV_CAGR3 and (pd.isna(c5) or c5 >= GROWTH_REV_CAGR5))
    cond2 = bool(pd.notna(o3) and o3 >= GROWTH_OP_CAGR3)
    growth_core = cond1 and cond2 and no_neg
    # 留任門檻：①②的 3 年 CAGR 改用退出門檻（草案未寫②是否放寬，依測試兩者都用 12%）
    growth_stay_core = bool(pd.notna(c3) and c3 >= GROWTH_EXIT_CAGR3
                            and pd.notna(o3) and o3 >= GROWTH_EXIT_CAGR3 and no_neg)

    metrics.update({
        "oroa": _last_nonnan(oroa.tail(1)), "oroa_amp": amp,
        "max_dd": dd["max_dd"], "dd_peak": dd["dd_peak"], "dd_trough": dd["dd_trough"],
        "dd_rev_yoy_min": dd["rev_yoy_min"], "contraction": dd["contraction"],
        "recovered_half": dd["recovered_half"],
        "coverage": (None if pd.isna(amp) else bool(cover)),
        "cyclical_necessary": cyc_ok, "cyclical_aux": aux_ok, "asset_heavy": asset_heavy,
        "rev_cagr3": c3, "rev_cagr5": c5, "op_cagr3": o3, "growth_core": growth_core,
        "crossing": crossing, "ttm_eps": ttm_eps_now,
    })
    # stay_ok：遲滯的留任門檻
    crossing_pass = bool(crossing["passed"])
    metrics["stay_ok"] = {
        TYPE_GROWTH: bool(growth_stay_core and (crossing_pass if cyc_ok else True)),
        TYPE_CYCLICAL: cyc_ok,
    }

    # ── 類型 ──
    ctype: str | None = None
    group = inp.industry_group
    if group == "financial":
        ctype = TYPE_FINANCIAL
        why.append("產業為金融保險，走 PB")
    else:
        triggers: list[str] = []
        k_loss = int((eps.tail(SPECIAL_BIOTECH_WINDOW_Q) < 0).sum())
        if group == "biotech" and k_loss >= SPECIAL_BIOTECH_LOSS_Q:
            triggers.append("biotech_loss")
            why.append(f"生技醫療近 {SPECIAL_BIOTECH_WINDOW_Q} 季有 {k_loss} 季虧損"
                       f"（≥ {SPECIAL_BIOTECH_LOSS_Q}）")
        if group == "construction":
            triggers.append("construction")
            why.append("建材營造：營收認列不連續，只給 PB 位置")
        cap = q["capital_stock"].astype(float)
        cap_prev = _lag(cap, 4).iloc[-1]
        cap_now = cap.iloc[-1]
        chg = (float(cap_now) / float(cap_prev) - 1.0
               if pd.notna(cap_now) and pd.notna(cap_prev) and cap_prev > 0 else nan)
        if pd.notna(chg) and abs(chg) > SPECIAL_CAP_CHANGE:
            if "equity_parent" in q.columns:
                eq = q["equity_parent"].astype(float)
                eq_prev = _lag(eq, 4).iloc[-1]
                eq_now = eq.iloc[-1]
                eq_chg = (float(eq_now) / float(eq_prev) - 1.0
                          if pd.notna(eq_now) and pd.notna(eq_prev) and eq_prev > 0 and eq_now > 0
                          else nan)
                if (pd.notna(eq_chg) and abs(eq_chg) > SPECIAL_EQUITY_JUMP
                        and abs(eq_chg) >= SPECIAL_EQUITY_RATIO * abs(chg)):
                    triggers.append("cap_change")
                    why.append(f"股本 4 季變動 {chg:+.0%}（> {SPECIAL_CAP_CHANGE:.0%}）"
                               f"且權益 {eq_chg:+.0%}（> {SPECIAL_EQUITY_JUMP:.0%}，且 ≥ 股本變動的 {SPECIAL_EQUITY_RATIO:.0%}）")
                else:
                    metrics["cap_jump_equity_flat"] = True
            else:
                triggers.append("cap_change")
                why.append(f"股本 4 季變動 {chg:+.0%}（> {SPECIAL_CAP_CHANGE:.0%}）")
        yoy_now = yoy_q.iloc[-1]
        if (pd.notna(yoy_now) and yoy_now > SPECIAL_REV_JUMP
                and pd.notna(chg) and chg > SPECIAL_CAP_JUMP_WITH_REV):
            triggers.append("rev_jump_cap")
            why.append(f"TTM 營收年增 {yoy_now:+.0%} 且股本同步增 {chg:+.0%}，疑似併購/重組")
        metrics["special_triggers"] = triggers
        if triggers:
            ctype = TYPE_SPECIAL

    if ctype is None:
        # 景氣循環／高成長的 why（成立才寫）
        if cyc_ok:
            why.append(f"OROA 振幅 {amp:.1%}，位於全體前 {1 - amp_pct:.0%}")
            why.append(f"TTM 營業利益自 {_qlabel(dd['dd_peak'])} 高點最多跌 {dd['max_dd']:.0%}，"
                       f"期間 TTM 營收年增最低 {dd['rev_yoy_min']:+.0%}")
            if aux_ok:
                if beta_ok:
                    why.append(f"營收 beta {inp.rev_beta:.2f}（≥ {CYCLE_BETA_MIN:g}）")
                if sync_ok:
                    why.append(f"產業同步度 {inp.ind_sync:.2f}（≥ {CYCLE_SYNC_MIN:g}）")
            else:
                why.append(f"缺輔助條件（營收 beta {inp.rev_beta:.2f}、"
                           f"產業同步度 {inp.ind_sync:.2f}），列疑似循環")
        if growth_core:
            c5_txt = "—" if pd.isna(c5) else f"{c5:.0%}"
            why.append(f"TTM 營收 3 年 CAGR {c3:.0%}、5 年 {c5_txt}")
            why.append(f"TTM 營業利益 3 年 CAGR {o3:.0%}")
            why.append(f"近 {GROWTH_NO_NEG_YOY_Q} 季 TTM 營收年增最低 {float(yoy_tail.min()):+.0%}"
                       f"（≥ {GROWTH_MIN_YOY:.0%}）")

        if cyc_ok and growth_core:
            if crossing["executed"]:
                if crossing["passed"]:
                    why.append(f"市場營收收縮的 {crossing['n']} 個月，個股營收年增皆 > 0")
                else:
                    why.append(f"市場營收收縮的 {crossing['n']} 個月，"
                               f"個股有 {crossing['k']} 個月 ≤ 0")
            else:
                degrade.append("期間無市場營收收縮月，穿越檢定未執行")
            if crossing_pass:
                ctype = TYPE_GROWTH
                subtags.append(SUB_CYCLICAL_GROWTH)
            else:
                ctype = TYPE_CYCLICAL
                subtags.append(SUB_GROWTH_CYCLE)
        elif cyc_ok:
            ctype = TYPE_CYCLICAL
        elif growth_core:
            ctype = TYPE_GROWTH
        else:
            ctype = TYPE_NORMAL
            why.append("未符合景氣循環或高成長條件")

        if ctype == TYPE_CYCLICAL:
            if not aux_ok:
                subtags.append(SUB_SUSPECT_CYCLE)
                degrade.append("疑似循環（缺輔助條件）")
            if not cover:
                subtags.append(SUB_CYCLE_INCOMPLETE)
                degrade.append("循環未觀察完整")
            subtags.append(SUB_ASSET_HEAVY if asset_heavy else SUB_ASSET_LIGHT)
            if dd["recovered_half"] is False:
                degrade.append("回撤後未回到前高 50%（可能為結構衰退）")
        if ctype == TYPE_GROWTH:
            if pd.isna(c5):
                degrade.append("營收歷史不足 5 年，5 年 CAGR 未檢查")
            listed = inp.listed_quarters if inp.listed_quarters is not None else len(q)
            if listed < GROWTH_MIN_LISTED_Q:
                degrade.append(f"上市未滿 {GROWTH_MIN_LISTED_Q} 季")
        if ctype == TYPE_NORMAL:
            if pd.notna(c3) and c3 < NORMAL_SHRINK_CAGR3:
                subtags.append(SUB_SHRINKING)
            years = _full_years_eps(eps)
            if years:
                last_y = max(years)
                if any(v < 0 for y, v in years.items() if y > last_y - NORMAL_LOSS_YEARS):
                    subtags.append(SUB_UNSTABLE)

    # ── 狀態 ──
    state: list[str] = []
    last4 = eps.tail(4)
    any_neg4 = bool((last4 < 0).any())
    is_loss = bool(pd.notna(ttm_eps_now) and ttm_eps_now <= 0)
    if is_loss:
        state.append(STATE_LOSS)
        why.append(f"近四季 EPS 合計 {ttm_eps_now:.2f} ≤ 0")
    nc, f4 = inp.eps_nc, inp.eps_f4
    if nc is not None and nc <= 0 and not is_loss:
        state.append(STATE_FWD_LOSS)
        why.append(f"EPS_NC {nc:.2f} ≤ 0，預估轉虧")
    unstable_reason: str | None = None
    if any_neg4:
        unstable_reason = f"近四季有 {int((last4 < 0).sum())} 季 EPS < 0"
    elif nc is not None:
        hist = eps_ttm.tail(UNSTABLE_MEDIAN_Q).dropna()
        if len(hist) >= 4:
            med = float(hist.median())
            if med > 0 and nc < med * UNSTABLE_EPSNC_REL:
                unstable_reason = (f"EPS_NC {nc:.2f} < 近 5 年 TTM EPS 中位數 {med:.2f} 的 "
                                   f"{UNSTABLE_EPSNC_REL:.0%}")
    if unstable_reason:
        state.append(STATE_UNSTABLE)
        why.append(unstable_reason)
    if (any_neg4 and len(q) and pd.notna(op.iloc[-1]) and op.iloc[-1] > 0
            and pd.notna(inp.g3) and inp.g3 > 0):
        t3 = op_ttm.tail(3).to_numpy(dtype=float)
        if len(t3) == 3 and not np.isnan(t3).any() and t3[2] > t3[1] > t3[0]:
            name = STATE_TROUGH_RECOVERY if ctype == TYPE_CYCLICAL else STATE_TURNAROUND
            state.append(name)
            why.append(f"{name}：近四季曾虧損，最新季營業利益轉正且 TTM 營業利益連 2 季上升")
    zone_win = oroa.tail(CYCLE_WINDOW_Q)
    zone_vals = zone_win.dropna()
    zone: str | None = None
    if len(zone_vals) >= CYCLE_MIN_OROA_OBS and pd.notna(zone_win.iloc[-1]):
        pct_self = float(zone_vals.rank(pct=True, method="average").iloc[-1])
        metrics["oroa_pct_self"] = pct_self
        if pct_self >= PROFIT_ZONE_HIGH:
            zone = STATE_PROFIT_HIGH
        elif pct_self <= PROFIT_ZONE_LOW:
            zone = STATE_PROFIT_LOW
        if zone:
            state.append(zone)
            why.append(f"最新 OROA 位於自身近 {CYCLE_WINDOW_Q} 季第 {pct_self * 100:.0f} 百分位")
    if zone and ctype == TYPE_CYCLICAL and cover:
        ind_last = _last_nonnan(inp.industry_rev_ttm_yoy)
        if pd.notna(ind_last):
            if zone == STATE_PROFIT_HIGH and ind_last > 0:
                state.append(STATE_CYCLE_HIGH)
                why.append(f"產業營收 TTM 年增 {ind_last:+.1%}，與歷史高獲利區同向")
            elif zone == STATE_PROFIT_LOW and ind_last < 0:
                state.append(STATE_CYCLE_LOW)
                why.append(f"產業營收 TTM 年增 {ind_last:+.1%}，與歷史低獲利區同向")
    if (nc is not None and f4 is not None and pd.notna(ttm_eps_now) and ttm_eps_now > 0
            and nc > 0 and f4 > 0 and nc / ttm_eps_now - 1.0 >= FWD_EXPAND_MIN - 1e-12
            and f4 >= nc):
        state.append(STATE_FWD_EXPAND)
        why.append(f"EPS_NC {nc:.2f} 較近四季 EPS {ttm_eps_now:.2f} 成長 "
                   f"{nc / ttm_eps_now - 1.0:.0%}，EPS_F4 {f4:.2f} ≥ EPS_NC")

    return Classification(type=ctype, state=state, subtags=subtags, why=why,
                          metrics=metrics, reasons_degrade=degrade)


def apply_hysteresis(new: Classification, history: pd.DataFrame) -> Classification:
    """套遲滯（§1.5），回傳**新物件**（不改 new）。

    history（同一 ticker、每季一列、依 decided_at 遞增），欄位 HISTORY_COLS：
      ticker(str)、decided_at(Timestamp：該次判定所用的最新季末)、
      candidate_type(str：該季「有效候選」，即已套留任門檻後的類型)、final_type(str：套遲滯後)、
      switched(bool：final_type 在該季改變)、
      candidate_states(str：該季 classify 的 state 以 "|" 串接，空＝"")、final_states(str：同格式)。
    缺欄 → ValueError。history 為空（0 列）＝首次判定。

    規則（current＝history 最後一列 final_type；prev＝history 最後一列）：
      1. 首次判定（history 0 列）：類型與狀態都直接採用 new（不做連 2 季、不限立即狀態），
         switched False，last_switch None，locked_until None。
      2. new.type 或 current 屬 TYPES_NO_HYSTERESIS → final＝new.type 立即生效（改變時 switched True）。
      3. 有效候選 cand＝new.type；若 new.type ≠ current 且 new.metrics["stay_ok"].get(current) 為 True
         → cand＝current（未跌破留任門檻，不算門檻外）。
      4. cand == current → 維持。
      5. 鎖定：最近一次 switched 為 True 的季 T，若 new 的季 < T + HYST_LOCK_Q 季 → 維持（鎖定中）。
      6. 連續：prev.decided_at 恰為 new 的前一個曆季 且 prev.candidate_type == cand → 切換為 cand；
         否則維持。（鎖定期間的候選仍計入「連續」）
      new 的季＝new.metrics["asof"]；與 prev.decided_at 相同 → ValueError（同季重判應由呼叫端取代該列）。
    狀態：final_states＝new.state 中屬 STATES_IMMEDIATE 者 ＋ 其餘「也出現在 prev.candidate_states 且 prev 為前一曆季」者
      （保持 new.state 的順序）。首次判定 → 直接採用 new.state 全部（2026-11-01 改）。
    輸出：type＝final、state＝final_states；metrics 另加
      "candidate_type"(cand), "raw_type"(new.type), "switched"(bool), "last_switch"(Timestamp|None：本季切換＝本季),
      "locked_until"(Timestamp|None：鎖定期最後一季的季末)。
    why 追加（維持時才加，一條）：
      "本季判定為{cand 中文}，未連續 2 季，維持{current 中文}"
      "切換後鎖定中（至 {YYYYQn}），維持{current 中文}"
      留任時："高成長留任：3 年營收 CAGR 仍 ≥ 12%"（只在 cand 因 stay_ok 改回 current 且 current 為 growth）
    """
    missing = [c for c in HISTORY_COLS if c not in history.columns]
    if missing:
        raise ValueError(f"history 缺欄位：{missing}")
    new_q = pd.Timestamp(new.metrics["asof"])
    out = dataclasses.replace(
        new, state=list(new.state), subtags=list(new.subtags), why=list(new.why),
        metrics=copy.deepcopy(new.metrics), reasons_degrade=list(new.reasons_degrade))

    def finish(final: str, cand: str, switched: bool, last_switch, final_states: list[str]):
        out.type = final
        out.state = final_states
        locked = None
        if last_switch is not None:
            end = _qord(last_switch) + HYST_LOCK_Q - 1
            if _qord(new_q) <= end:
                locked = pd.Timestamp(last_switch) + pd.offsets.QuarterEnd(HYST_LOCK_Q - 1)
        out.metrics.update({"candidate_type": cand, "raw_type": new.type, "switched": switched,
                            "last_switch": last_switch, "locked_until": locked})
        return out

    if len(history) == 0:                                   # 1 首次判定
        return finish(new.type, new.type, False, None, list(new.state))

    prev = history.iloc[-1]
    prev_dt = pd.Timestamp(prev["decided_at"])
    if new_q == prev_dt:
        raise ValueError("同一季重複判定：應由呼叫端取代該列")
    consecutive = _qord(prev_dt) == _qord(new_q) - 1
    current = str(prev["final_type"])

    # 狀態：立即狀態＋前一曆季候選也有的狀態
    prev_states = prev["candidate_states"]
    prev_set = set(str(prev_states).split(STATE_SEP)) if isinstance(prev_states, str) and prev_states else set()
    final_states = [s for s in new.state
                    if s in STATES_IMMEDIATE or (consecutive and s in prev_set)]

    sw = history[history["switched"].astype(bool)]
    last_sw = pd.Timestamp(sw.iloc[-1]["decided_at"]) if len(sw) else None

    def result(final: str, cand: str):
        switched = final != current
        return finish(final, cand, switched, new_q if switched else last_sw, final_states)

    if new.type in TYPES_NO_HYSTERESIS or current in TYPES_NO_HYSTERESIS:   # 2
        return result(new.type, new.type)

    cand = new.type                                                          # 3
    stayed = False
    if new.type != current and new.metrics.get("stay_ok", {}).get(current) is True:
        cand, stayed = current, True

    if cand == current:                                                      # 4
        if stayed and current == TYPE_GROWTH:
            out.why.append(f"高成長留任：3 年營收 CAGR 仍 ≥ {GROWTH_EXIT_CAGR3:.0%}")
        return result(current, cand)

    if last_sw is not None and _qord(new_q) < _qord(last_sw) + HYST_LOCK_Q:  # 5
        end = last_sw + pd.offsets.QuarterEnd(HYST_LOCK_Q - 1)
        out.why.append(f"切換後鎖定中（至 {_qlabel(end)}），維持{TYPE_ZH.get(current, current)}")
        return result(current, cand)

    if consecutive and prev["candidate_type"] == cand:                       # 6
        return result(cand, cand)
    out.why.append(f"本季判定為{TYPE_ZH.get(cand, cand)}，未連續 {HYST_CONFIRM_Q} 季，"
                   f"維持{TYPE_ZH.get(current, current)}")
    return result(current, cand)


def display_type(c: Classification) -> str:
    """卡片顯示用類型名（§1.4 覆蓋規則）。

    c.type 為 TYPE_NORMAL 或 TYPE_GROWTH，且 state 含 "虧損" 或 "轉機" → "轉機"。
    其餘 → TYPE_ZH[c.type]（循環、金融不被覆蓋；特殊、資料不足照原名）。
    """
    if c.type in (TYPE_NORMAL, TYPE_GROWTH) and (STATE_LOSS in c.state or STATE_TURNAROUND in c.state):
        return "轉機"
    return TYPE_ZH[c.type]

