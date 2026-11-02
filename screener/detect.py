"""估值可信度四組（估值 2.0，upgrade_guide §8）。

【框架由 Opus 定（P3，2026-11-02），實作者不得改介面、常數名與值、Check 欄位、group／name 字串】函式本體由 P3 實作。

每個檢查回 `Check(group, name, level, value, why)`：
- group ∈ GROUPS：data／share_basis／comparability／estimate
- level ∈ LEVELS：ok／warn（只提示）／stop（停用受影響的窗口或方法）／unchecked（沒檢查到；≠ ok）
- why：畫面用中文短句；level=="ok" 時可為 ""（例外：estimate 沒有試算季時寫「沒有試算季」）
`summarize()` 彙總成每組一個狀態（嚴重度 stop > warn > unchecked > ok），val_card 依它停用：
- data stop → 該窗口不可用（val_card 判 D）
- share_basis stop → PE／PB 都不給價（val_card 判 D，原因寫 why）
- estimate stop → 停用所有試算季（近 4 季退回已公布 4 季、前瞻不給）
- comparability 只提示
純函式，不讀檔（share_checks 例外：透過 reference.share_basis 讀事件表）。

舊版（card-v2）的 degrade／severe／block 三級、confidence()、dist_check()、class_flags()、pb_events() 全部刪除；
P80÷P20、倍數截斷、分類旗標改進 comparability_checks。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

LEVELS = ("ok", "warn", "stop", "unchecked")
GROUPS = ("data", "share_basis", "comparability", "estimate")
SEVERITY = {"ok": 0, "unchecked": 1, "warn": 2, "stop": 3}

# ── 門檻（沿用舊值者註明）──
SHARES_WARN = 0.15           # 隱含股數 vs 股本÷面額 差距（舊 SHARES_BLOCK；EPS 已調股數，差距多為調整時點 → 只提示）
BRIDGE_WARN = 0.10           # 沿用
BRIDGE_STOP = 0.25           # 沿用
NONOP_SHARE = 0.20           # 沿用：近 8 季業外占稅前
NONOP_DISPERSION = 0.5       # 沿用：業外 P90−P10 ÷ |稅前中位數|
REV_CALIBER_TOL = 0.05       # 沿用
NEAR_ZERO_REL = 0.2          # 沿用
RATIO_WARN = 2.5             # 沿用（舊 RATIO_DEGRADE）；>4 也只提示（§5-2「只降級」）
FWD_JUMP_REL = 1.5           # 沿用
VAR_PP = 0.30                # 【起始值】高變動：最新季季增減 − 去年同季季增減，絕對值 ≥ 30 個百分點
PAR_DEFAULT = 10.0           # 沒有面額資料時假設 10 元（company_basic 要到 P5）


@dataclass(frozen=True)
class Check:
    group: str
    name: str
    level: str
    value: float | None
    why: str


def summarize(checks: list[Check]) -> dict[str, dict]:
    """{group: {"level": str, "items": [{"name", "level", "value", "why"}...]}}，GROUPS 四組都要有。
    level＝該組 items 中 SEVERITY 最高者；該組沒有任何 Check → level="unchecked"、items=[]。
    items 只列 level != "ok" 的 Check，**例外**：estimate 組的「試算季」ok 項（why＝沒有試算季）要列。
    items 依 SEVERITY 由高到低、同級照原順序。"""
    raise NotImplementedError


def stopped(status: dict[str, dict], group: str) -> str | None:
    """status＝summarize() 結果；該組 level=="stop" → 回傳第一個 stop 項的 why，否則 None。"""
    raise NotImplementedError


# ── data ──────────────────────────────────────────────────────────

def data_checks(q: pd.DataFrame, monthly: pd.Series, windows: dict, cls: dict | None,
                asof: pd.Timestamp, financial: bool = False, construction: bool = False) -> list[Check]:
    """windows＝eps_windows.windows(...) 結果（{"reported","ttm","fwd"}）。依序產生：
    1. 「財報缺季」：windows["reported"].ok 為 False → stop，why＝"近 4 季財報不連續或不足（{reason}）"；否則 ok。
    2. 「財報延遲」：windows["ttm"].status=="report_late" → warn，why＝"新季營收已出兩季、財報還沒出，近 4 季用已公布財報"。
       （ok 時不必產生）
    3. 「月營收缺」（financial=True 跳過，不產生）：M＝asof 時「應已公布」的最近月（asof ≥ 次月 10 日的最近一個月）；
       monthly 在 M 沒有有限 >0 的值 → warn，why＝f"{M:%Y-%m} 月營收應已公布但沒有資料，新季不試算"；否則 ok。
    4. 「分類過期」：cls 有 decided_at 且早於 q 最新 period_end → warn（why 沿用舊句：
       "分類基準 YYYY-MM-DD 落後最新財報 YYYY-MM-DD，類型與狀態可能過期"）；解析失敗略過。
    5. 「財報矛盾」：quarter_sanity(q, construction=construction)，financial=True 跳過。"""
    raise NotImplementedError


def quarter_sanity(q: pd.DataFrame, n: int = 8, construction: bool = False) -> Check:
    """沿用 card-v2 算法（近 n 季 EPS 與歸母淨利異號、非營建營收 ≤0、毛利 > 營收；缺欄位略過該條）。
    group="data"、name="財報矛盾"；有矛盾 → warn（舊 degrade），why 沿用舊句。"""
    raise NotImplementedError


# ── share_basis ───────────────────────────────────────────────────

def share_checks(ticker: str, q: pd.DataFrame, asof: pd.Timestamp, today_par: float | None = None) -> list[Check]:
    """1. 事件表：reference.share_basis.events(ticker) 丟 EventsUnavailable → 只回
          [Check("share_basis","股數事件表","stop",None,"股數事件表讀取失敗，股數基準無法確認，不給價")]（T-17）。
    2. 「現金減資區間」（卡片端即時版，與歷史序列的 excluded_months 不同）：share_basis.events(ticker) 中
       type=="cap_reduction" 且 m 為 None、date ≤ asof 的事件 e，Qe＝e.date 所在曆季季末；
       q 沒有任何 period_end ≥ Qe 且 eps 有限的列（事件後的財報還沒進來）→ stop，
       why＝"現金減資後、新財報出來前，EPS 與股價的股數基準不一致，不給價"；否則 ok。
    3. 「股數對不上」：最新一季（period_end 最大且 |eps| ≥ 0.05、ni_parent 有限）隱含股數 S＝ni_parent ÷ eps；
       股本股數 C＝capital_stock ÷ (today_par 或 PAR_DEFAULT)；dev＝|S ÷ C − 1|；
       dev > SHARES_WARN → warn（why：f"隱含股數與股本差 {dev:.0%}，可能是分割／配股調整時點"），否則 ok（value=dev）；
       推不出 S 或 C 非有限 >0 → unchecked，why＝"推不出隱含股數或缺股本"。
    4. 「面額與特別股」：today_par 為 None → unchecked，why＝"面額與特別股資料尚未收集，假設面額 10 元"；否則 ok。"""
    raise NotImplementedError


# ── comparability ─────────────────────────────────────────────────

def comparability_checks(cls: dict | None, stats: dict | None) -> list[Check]:
    """全部只提示（warn）。stats＝val_card 採用的那組 multiples_self.window_stats 結果（沒有就 None，不產生倍數項）。
    1. 「倍數分布」：raw_mults P20、P80 皆有限 >0 且 P80÷P20 > RATIO_WARN → warn，
       why＝f"歷史倍數 P80÷P20＝{r:.1f}，分布寬，三價參考性較低"，value=r；否則 ok。
    2. 「倍數截斷」：stats["capped"] → warn，why＝"歷史倍數高於上限，已截斷"。
    3. 分類旗標（cls subtags）：「疑似循環」「循環未觀察完整」「僅單一景氣事件」各一條 warn（why 沿用舊句）。
    4. cls metrics：comparability_pending → 「歷史可比性」warn；switched → 「剛換類」warn（why 沿用舊句）。"""
    raise NotImplementedError


# ── estimate ──────────────────────────────────────────────────────

def estimate_checks(q: pd.DataFrame, monthly: pd.Series, windows: dict) -> list[Check]:
    """試算季的可靠度。E＝windows["ttm"]、windows["fwd"] 兩窗口所有 EstDetail（依 q 去重）。
    E 為空 → 只回 [Check("estimate","試算季","ok",None,"沒有試算季")]。否則依序：
    1. bridge_residual(q, E[0])
    2. nonop_gate(q)
    3. revenue_caliber(q, monthly)
    4. variability(q)
    5. E 每個 EstDetail 的 flags（去重）→ 各一條 warn，name＝「稅率／少數股權」，why＝flag 原文
    6. near_zero_eps(windows["fwd"].eps 若 fwd.ok 且 n_est>0，否則 windows["ttm"].eps, q)
    7. forward_jump(windows["fwd"].eps, windows["reported"].eps)（fwd 或 reported 不 ok → 傳 None）"""
    raise NotImplementedError


def bridge_residual(q: pd.DataFrame, detail) -> Check:
    """驗「試算公式本身」（§8：零業外改業外中位數）：對 q 最近 8 個 eps、op_income 皆有限的實際季 i：
      pretax_i = op_income_i + detail.nonop；t_i = 0 if pretax_i ≤ 0 else tax8；
      eps_hat_i = pretax_i × (1 − t_i) × (1 − detail.minority) ÷ detail.shares
    tax8＝1 − Σnet_income ÷ Σpretax_income（同 8 季）；Σpretax ≤0 或 tax8 ∉ [0, 0.35] → 0.20。
    r＝Σ|eps_hat − eps| ÷ Σ|eps|；有效季 <4 或 Σ|eps|=0 → unchecked（why＝"實際季不足，無法驗證試算公式"）。
    r > BRIDGE_STOP → stop；> BRIDGE_WARN → warn；否則 ok。group="estimate"、name="橋接殘差"、value=r，
    why：f"用試算公式重算近 8 季 EPS，平均誤差 {r:.0%}"（stop 再加「，試算停用」）。"""
    raise NotImplementedError


def nonop_gate(q: pd.DataFrame) -> Check:
    """沿用 card-v2 算法；舊 block → stop（why 結尾改「，試算停用」）、degrade → warn。name="業外閘門"。"""
    raise NotImplementedError


def revenue_caliber(q: pd.DataFrame, monthly: pd.Series) -> Check:
    """沿用 card-v2 算法（近 4 季曆季相鄰，用 period_end 推 3 個月）；舊 block → stop。name="月營收口徑"。"""
    raise NotImplementedError


def variability(q: pd.DataFrame) -> Check:
    """高變動（§8 新門檻）：P＝最新一季；需要 P、P−1、P−4、P−5 曆季都有 revenue 有限 >0，否則 ok。
    g_now＝rev(P)÷rev(P−1)−1；g_ly＝rev(P−4)÷rev(P−5)−1；d＝g_now − g_ly。
    |d| ≥ VAR_PP → warn，value=d，why＝f"最新一季營收季增減比去年同期多 {d:+.0%}（排除淡旺季後仍偏離），試算延續該季水準"。
    name="高變動"。"""
    raise NotImplementedError


def near_zero_eps(eps_base: float | None, q: pd.DataFrame) -> Check:
    """沿用 card-v2 算法（近 20 個 TTM 中位數 × NEAR_ZERO_REL）；舊 block → stop，
    why＝f"試算後 4 季 EPS {eps_base:.2f} 遠低於近 5 年中位 {med:.2f}，試算停用"。name="近零EPS"。"""
    raise NotImplementedError


def forward_jump(eps_fwd: float | None, eps_reported: float | None) -> Check:
    """沿用 card-v2 算法與 why；degrade → warn。name="前瞻跳升"。"""
    raise NotImplementedError
