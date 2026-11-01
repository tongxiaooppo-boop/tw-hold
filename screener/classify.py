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
  必要②：op_drawdown(...)["max_dd"] ≥ CYCLE_DRAWDOWN 且 ["contraction"] 為 True。
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
  ③近 GROWTH_NO_NEG_YOY_Q 季的季頻 TTM 營收年增都 ≥ 0（任一 NaN 或 < 0 → 不成立）
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
  高成長③  "近 12 季 TTM 營收年增皆 ≥ 0"
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

import pandas as pd

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

HISTORY_COLS = ("ticker", "decided_at", "candidate_type", "final_type", "switched",
                "candidate_states", "final_states")
STATE_SEP = "|"


@dataclass
class ClassInputs:
    """classify() 的輸入（欄位與型別固定，不准改）。

    quarters：單一檔，index＝period_end（季末 Timestamp，嚴格遞增），欄位 QUARTER_COLS 全部**單季**
      （capex 已用 quarterly_prep.to_single_quarter_cashflow 差分；capex 正負號不拘，取絕對值用）。
      缺季的列可以不存在；缺值 NaN。
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


# ── 單檔計算（build 用來算橫斷面，classify 內部也用）─────────────────

def oroa_series(quarters: pd.DataFrame) -> pd.Series:
    """OROA(t)＝TTM op_income(t) ÷ mean(total_assets 在 t−4..t 共 5 個曆季)。

    TTM 用 quarterly_prep.ttm（連續 4 曆季）；總資產 5 個曆季都要在 index 且非 NaN、平均 > 0，否則 NaN。
    輸出與 quarters 同 index、name="oroa" 的 float Series。缺欄 → KeyError。
    """
    raise NotImplementedError


def oroa_amplitude(oroa: pd.Series, window: int = CYCLE_WINDOW_Q,
                   min_obs: int = CYCLE_MIN_OROA_OBS) -> float:
    """近 window 列（最後 window 列，含 NaN 列）中非 NaN 的 OROA 的 P90 − P10
    （pandas Series.quantile 預設線性插值）。非 NaN 個數 < min_obs → NaN。不丟例外。"""
    raise NotImplementedError


def op_drawdown(quarters: pd.DataFrame, window: int = CYCLE_WINDOW_Q) -> dict:
    """TTM op_income 的最大回撤與同期營收收縮。

    TTM op、TTM 營收與其年增先用全部列算好，再只看最後 window 列。對每個 t：peak(t)＝窗內 t 以前（含）TTM op 最大值所在季（同值取**最晚**那季）；
      peak 值 > 0 時 dd(t)＝1 − TTM_op(t) ÷ peak 值（可 > 1，代表跌到負）；否則不算。
    max_dd＝max dd(t)；取 max_dd 的 t 為 trough（同值取最早），對應 peak 為 dd_peak。
    rev_yoy_min＝[dd_peak, trough] 期間（含兩端）季頻 TTM 營收年增（TTM(t)/TTM(t−4)−1）的最小值。
    contraction＝rev_yoy_min < CYCLE_REV_CONTRACTION。
    **注意**：「同期營收收縮」只看 max_dd 那一段；若要求「任一段 dd ≥ 50% 且同期收縮」，見待決。
    recovered_half＝trough 之後（不含）任一 TTM op ≥ peak 值 × CYCLE_RECOVER_HALF；trough 是最後一季 → None。

    回傳 {"max_dd": float, "dd_peak": Timestamp|None, "dd_trough": Timestamp|None,
          "rev_yoy_min": float, "contraction": bool, "recovered_half": bool|None}
    無可算點 → max_dd NaN、contraction False、其餘 None／NaN。
    """
    raise NotImplementedError


def cycle_coverage(oroa: pd.Series, amp: float, window: int = CYCLE_WINDOW_Q) -> bool:
    """循環涵蓋檢查：最後 window 列的非 NaN OROA 中，存在 i < j < k 使
      高→低→高：x_i − x_j ≥ thr 且 x_k − x_j ≥ thr，或
      低→高→低：x_j − x_i ≥ thr 且 x_j − x_k ≥ thr，
    其中 thr＝amp × CYCLE_COVERAGE_LEG。amp 為 NaN 或 ≤ 0 → False。"""
    raise NotImplementedError


def asset_intensity(quarters: pd.DataFrame) -> dict:
    """資產強度（橫斷面分位前的原始值）。

    ta_rev＝最新一列 total_assets ÷ 最新 TTM 營收（TTM ≤ 0 或 NaN → NaN）。
    capex_rev＝Σ|capex| ÷ Σrevenue，取最後 ASSET_CAPEX_Q 列中 capex 與 revenue 都非 NaN 的列；
      這樣的列 < ASSET_CAPEX_MIN_Q 或 Σrevenue ≤ 0 → NaN。
    回傳 {"ta_rev": float, "capex_rev": float}。
    """
    raise NotImplementedError


def cross_section_pct(values: pd.Series) -> pd.Series:
    """橫斷面分位：values.rank(pct=True, method="average")；NaN 保持 NaN、不計入分母。
    index 原樣（通常是 ticker）。"""
    raise NotImplementedError


def ttm_cagr(ttm_series: pd.Series, years: int) -> float:
    """CAGR＝(最後一列值 ÷ 4×years 個曆季前那一季的值)^(1/years) − 1。
    ttm_series 的 index 為季末 Timestamp；那一季不在 index、任一端 NaN 或 ≤ 0 → NaN。"""
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


def apply_hysteresis(new: Classification, history: pd.DataFrame) -> Classification:
    """套遲滯（§1.5），回傳**新物件**（不改 new）。

    history（同一 ticker、每季一列、依 decided_at 遞增），欄位 HISTORY_COLS：
      ticker(str)、decided_at(Timestamp：該次判定所用的最新季末)、
      candidate_type(str：該季「有效候選」，即已套留任門檻後的類型)、final_type(str：套遲滯後)、
      switched(bool：final_type 在該季改變)、
      candidate_states(str：該季 classify 的 state 以 "|" 串接，空＝"")、final_states(str：同格式)。
    缺欄 → ValueError。history 為空（0 列）＝首次判定。

    規則（current＝history 最後一列 final_type；prev＝history 最後一列）：
      1. 首次判定：final＝new.type，switched False，last_switch None。
      2. new.type 或 current 屬 TYPES_NO_HYSTERESIS → final＝new.type 立即生效（改變時 switched True）。
      3. 有效候選 cand＝new.type；若 new.type ≠ current 且 new.metrics["stay_ok"].get(current) 為 True
         → cand＝current（未跌破留任門檻，不算門檻外）。
      4. cand == current → 維持。
      5. 鎖定：最近一次 switched 為 True 的季 T，若 new 的季 < T + HYST_LOCK_Q 季 → 維持（鎖定中）。
      6. 連續：prev.decided_at 恰為 new 的前一個曆季 且 prev.candidate_type == cand → 切換為 cand；
         否則維持。（鎖定期間的候選仍計入「連續」）
      new 的季＝new.metrics["asof"]；與 prev.decided_at 相同 → ValueError（同季重判應由呼叫端取代該列）。
    狀態：final_states＝new.state 中屬 STATES_IMMEDIATE 者 ＋ 其餘「也出現在 prev.candidate_states 且 prev 為前一曆季」者
      （保持 new.state 的順序）。首次判定 → 只有 STATES_IMMEDIATE。
    輸出：type＝final、state＝final_states；metrics 另加
      "candidate_type"(cand), "raw_type"(new.type), "switched"(bool), "last_switch"(Timestamp|None：本季切換＝本季),
      "locked_until"(Timestamp|None：鎖定期最後一季的季末)。
    why 追加（維持時才加，一條）：
      "本季判定為{cand 中文}，未連續 2 季，維持{current 中文}"
      "切換後鎖定中（至 {YYYYQn}），維持{current 中文}"
      留任時："高成長留任：3 年營收 CAGR 仍 ≥ 12%"（只在 cand 因 stay_ok 改回 current 且 current 為 growth）
    """
    raise NotImplementedError


def display_type(c: Classification) -> str:
    """卡片顯示用類型名（§1.4 覆蓋規則）。

    c.type 為 TYPE_NORMAL 或 TYPE_GROWTH，且 state 含 "虧損" 或 "轉機" → "轉機"。
    其餘 → TYPE_ZH[c.type]（循環、金融不被覆蓋；特殊、資料不足照原名）。
    """
    raise NotImplementedError

