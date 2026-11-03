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


def _finite(x) -> bool:
    return x is not None and bool(np.isfinite(x))


def _ok(group, name, value=None) -> Check:
    return Check(group, name, "ok", value, "")


def _ordered(q):
    return q.sort_values("period_end", kind="stable").drop_duplicates("period_end", keep="last")


def _series(q, col):
    s = q[col] if col in q else pd.Series(np.nan, index=q.index)
    return s.where(np.isfinite(s))

LEVELS = ("ok", "warn", "stop", "unchecked")
GROUPS = ("data", "share_basis", "comparability", "estimate")
SEVERITY = {"ok": 0, "unchecked": 1, "warn": 2, "stop": 3}

# ── 門檻（沿用舊值者註明）──
SHARES_WARN = 0.15           # 隱含股數 vs 股本÷面額 差距（舊 SHARES_BLOCK；EPS 已調股數，差距多為調整時點 → 只提示）
# 試算停用門檻：方案 B（2026-11-02 Opus／sol／DeepSeek 投票 3:0，使用者授權；待回測的暫行值）
BRIDGE_WARN = 0.05           # 影響率（單季重算誤差平均 ÷ |已公布近 4 季 EPS|）提示
BRIDGE_STOP = 0.10           # 影響率停用（全市場約 P75）
JUMP_STOP = 0.50             # 營收劇變 |J| 停用
NONOP_SHARE = 0.20           # 沿用：近 8 季業外占稅前
NONOP_DISPERSION = 0.5       # 沿用：業外 P90−P10 ÷ |稅前中位數|
REV_CALIBER_TOL = 0.05       # 沿用
NEAR_ZERO_REL = 0.2          # 沿用
RATIO_WARN = 2.5             # 沿用（舊 RATIO_DEGRADE）；>4 也只提示（§5-2「只降級」）
FWD_JUMP_REL = 1.5           # 沿用
VAR_PP = 0.30                # 【起始值】高變動：最新季季增減 − 去年同季季增減，絕對值 ≥ 30 個百分點
PAR_DEFAULT = 10.0           # 沒有可用官方面額資料時假設 10 元
BASIC_MAX_AGE_DAYS = 30


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
    out = {}
    for group in GROUPS:
        rows = [c for c in checks if c.group == group]
        level = max((c.level for c in rows), key=SEVERITY.get) if rows else "unchecked"
        visible = [c for c in rows if c.level != "ok" or
                   (group == "estimate" and c.name == "試算季" and c.why == "沒有試算季")]
        visible.sort(key=lambda c: -SEVERITY[c.level])
        out[group] = dict(level=level, items=[dict(name=c.name, level=c.level, value=c.value, why=c.why)
                                              for c in visible])
    return out


def stopped(status: dict[str, dict], group: str) -> str | None:
    """status＝summarize() 結果；該組 level=="stop" → 回傳第一個 stop 項的 why，否則 None。"""
    row = status.get(group, {})
    if row.get("level") == "stop":
        return next((c["why"] for c in row["items"] if c["level"] == "stop"), None)
    return None


# ── data ──────────────────────────────────────────────────────────

def data_checks(q: pd.DataFrame, monthly: pd.Series, windows: dict, cls: dict | None,
                asof: pd.Timestamp, financial: bool = False, construction: bool = False) -> list[Check]:
    """windows＝eps_windows.windows(...) 結果（{"reported","ttm","fwd"}）。依序產生：
    1. 「財報缺季」：windows["reported"].ok 為 False → stop，why＝"近 4 季財報不連續或不足（{reason}）"；否則 ok。
       financial=True 改看：q 最新 4 個曆季相鄰、且每季 equity_parent 有限、ni_parent 或 eps 有限 → ok，否則 stop
       （P3：銀行／證券沒有營收欄，reported 窗口永遠不 ok）。
    2. 「財報延遲」：windows["ttm"].status=="report_late" → warn，why＝"新季營收已出兩季、財報還沒出，近 4 季用已公布財報"。
       （ok 時不必產生）
    3. 「月營收缺」（financial=True 跳過，不產生）：M＝asof 時「應已公布」的最近月（asof ≥ 次月 10 日的最近一個月）；
       monthly 在 M 沒有有限 >0 的值 → warn，why＝f"{M:%Y-%m} 月營收應已公布但沒有資料，新季不試算"；否則 ok。
    4. 「分類過期」：cls 有 decided_at 且早於 q 最新 period_end → warn（why 沿用舊句：
       "分類基準 YYYY-MM-DD 落後最新財報 YYYY-MM-DD，類型與狀態可能過期"）；解析失敗略過。
    5. 「財報矛盾」：quarter_sanity(q, construction=construction)，financial=True 跳過。"""
    reported, ttm = windows["reported"], windows["ttm"]
    if financial:
        d = _ordered(q)
        good = d[np.isfinite(_series(d, "equity_parent"))
                 & (np.isfinite(_series(d, "ni_parent")) | np.isfinite(_series(d, "eps")))]
        per = list(good["period_end"].dt.to_period("Q"))[-4:]
        fin_ok = len(per) == 4 and per[-1] == d["period_end"].dt.to_period("Q").max() and all(
            (b - a).n == 1 for a, b in zip(per, per[1:]))
        out = [_ok("data", "財報缺季") if fin_ok else
               Check("data", "財報缺季", "stop", None, "近 4 季財報不連續或不足（金融業看歸母淨利與權益）")]
    else:
        out = [_ok("data", "財報缺季") if reported.ok else
               Check("data", "財報缺季", "stop", None, f"近 4 季財報不連續或不足（{reported.reason}）")]
    if ttm.status == "report_late":
        out.append(Check("data", "財報延遲", "warn", None,
                         "新季營收已出兩季、財報還沒出，近 4 季用已公布財報"))
    if not financial:
        m = pd.Timestamp(asof).to_period("M") - (1 if pd.Timestamp(asof).day >= 10 else 2)
        v = monthly.get(m.start_time)
        out.append(_ok("data", "月營收缺") if _finite(v) and v > 0 else
                   Check("data", "月營收缺", "warn", None,
                         f"{m.start_time:%Y-%m} 月營收應已公布但沒有資料，新季不試算"))
    if cls and cls.get("decided_at") and not q.empty:
        try:
            decided = pd.Timestamp(cls["decided_at"])
            latest = pd.to_datetime(q["period_end"]).max()
            if decided < latest:
                out.append(Check("data", "分類過期", "warn", None,
                                 f"分類基準 {decided:%Y-%m-%d} 落後最新財報 {latest:%Y-%m-%d}，類型與狀態可能過期"))
        except (ValueError, TypeError):
            pass
    if not financial:
        out.append(quarter_sanity(q, construction=construction))
    return out


def quarter_sanity(q: pd.DataFrame, n: int = 8, construction: bool = False) -> Check:
    """沿用 card-v2 算法（近 n 季 EPS 與歸母淨利異號、非營建營收 ≤0、毛利 > 營收；缺欄位略過該條）。
    group="data"、name="財報矛盾"；有矛盾 → warn（舊 degrade），why 沿用舊句。"""
    d = _ordered(q).tail(n)
    bad = pd.Series(False, index=d.index)
    if "eps" in d and "ni_parent" in d:
        eps, ni = _series(d, "eps"), _series(d, "ni_parent")
        bad |= eps.notna() & ni.notna() & (eps != 0) & (ni != 0) & (np.sign(eps) != np.sign(ni))
    if "revenue" in d:
        rev = _series(d, "revenue")
        if not construction:
            bad |= rev <= 0
        if "gross_profit" in d:
            bad |= _series(d, "gross_profit") > rev
    count = int(bad.sum())
    if not count:
        return _ok("data", "財報矛盾")
    quarters = "、".join(pd.to_datetime(d.loc[bad, "period_end"]).dt.to_period("Q").astype(str))
    return Check("data", "財報矛盾", "warn", count,
                 f"近 {n} 季有 {count} 季財報數字互相矛盾（{quarters}）："
                 "EPS 與淨利正負相反／營收 ≤0／毛利 > 營收，相關數字可能不準")


# ── share_basis ───────────────────────────────────────────────────

def share_checks(ticker: str, q: pd.DataFrame, asof: pd.Timestamp, basic: dict | None = None) -> list[Check]:
    """1. 事件表：reference.share_basis.events(ticker) 丟 EventsUnavailable → 只回
          [Check("share_basis","股數事件表","stop",None,"股數事件表讀取失敗，股數基準無法確認，不給價")]（T-17）。
    2. 「現金減資區間」（卡片端即時版，與歷史序列的 excluded_months 不同）：share_basis.events(ticker) 中
       type=="cap_reduction" 且 m 為 None、date ≤ asof 的事件 e，Qe＝e.date 所在曆季季末；
       q 沒有任何 period_end ≥ Qe 且 eps 有限的列（事件後的財報還沒進來）→ stop，
       why＝"現金減資後、新財報出來前，EPS 與股價的股數基準不一致，不給價"；否則 ok。
    3. 「股數對不上」：最新一季（period_end 最大且 |eps| ≥ 0.05、ni_parent 有限）隱含股數 S＝ni_parent ÷ eps；
       股本股數 C＝capital_stock ÷ 面額 − 特別股；dev＝|S ÷ C − 1|；
       dev > SHARES_WARN → warn（why：f"隱含股數與股本差 {dev:.0%}，可能是分割／配股調整時點"），否則 ok（value=dev）；
       推不出 S 或 C 非有限 >0 → unchecked，why＝"推不出隱含股數或缺股本"。
    4. 「面額與特別股」：面額有限且正、資料日距估值日不超過 30 天才可用；
       缺或過期 → unchecked；有特別股 → warn；否則 ok。"""
    from reference import share_basis as sb

    try:
        events = sb.events(ticker)
    except sb.EventsUnavailable:
        return [Check("share_basis", "股數事件表", "stop", None,
                      "股數事件表讀取失敗，股數基準無法確認，不給價")]
    d = _ordered(q)
    blocked = any(e.get("type") == "cap_reduction" and e.get("m") is None
                  and e["date"] <= pd.Timestamp(asof)
                  and not ((pd.to_datetime(d["period_end"]) >= e["date"].to_period("Q").end_time.normalize())
                           & np.isfinite(_series(d, "eps"))).any() for e in events)
    out = [Check("share_basis", "現金減資區間", "stop", None,
                 "現金減資後、新財報出來前，EPS 與股價的股數基準不一致，不給價")
           if blocked else _ok("share_basis", "現金減資區間")]
    usable = False
    if basic is not None and _finite(basic.get("par_value")) and basic["par_value"] > 0:
        try:
            age = abs(pd.Timestamp(asof) - pd.Timestamp(basic.get("asof")))
            usable = pd.notna(age) and age <= pd.Timedelta(days=BASIC_MAX_AGE_DAYS)
        except (TypeError, ValueError):
            pass
    par = basic["par_value"] if usable else PAR_DEFAULT
    pref = basic.get("preferred_shares", 0) if usable else 0
    pref = pref if _finite(pref) else 0
    candidates = d[(_series(d, "eps").abs() >= 0.05) & _series(d, "ni_parent").notna()]
    dev = None
    if not candidates.empty:
        r = candidates.iloc[-1]
        shares = r["ni_parent"] / r["eps"]
        capital = r.get("capital_stock")
        c = capital / par - pref if _finite(capital) and _finite(par) and par > 0 else None
        if _finite(shares) and shares > 0 and _finite(c) and c > 0:
            dev = abs(shares / c - 1)
    out.append(Check("share_basis", "股數對不上", "unchecked", None, "推不出隱含股數或缺股本")
               if dev is None else Check("share_basis", "股數對不上", "warn", dev,
                                        f"隱含股數與股本差 {dev:.0%}，可能是分割／配股調整時點")
               if dev > SHARES_WARN else _ok("share_basis", "股數對不上", dev))
    out.append(Check("share_basis", "面額與特別股", "unchecked", None,
                     "面額與特別股資料缺或過期，假設面額 10 元")
               if not usable else Check("share_basis", "面額與特別股", "warn", pref,
                   f"有特別股 {pref/1e8:.2f} 億股，每股淨值含特別股權益、股價淨值比可能偏低")
               if pref > 0 else _ok("share_basis", "面額與特別股"))
    return out


# ── comparability ─────────────────────────────────────────────────

def comparability_checks(cls: dict | None, stats: dict | None) -> list[Check]:
    """全部只提示（warn）。stats＝val_card 採用的那組 multiples_self.window_stats 結果（沒有就 None，不產生倍數項）。
    1. 「倍數分布」：raw_mults P20、P80 皆有限 >0 且 P80÷P20 > RATIO_WARN → warn，
       why＝f"歷史倍數 P80÷P20＝{r:.1f}，分布寬，三價參考性較低"，value=r；否則 ok。
    2. 「倍數截斷」：stats["capped"] → warn，why＝"歷史倍數高於上限，已截斷"。
    3. 分類旗標（cls subtags）：「疑似循環」「循環未觀察完整」「僅單一景氣事件」各一條 warn（why 沿用舊句）。
    4. cls metrics：comparability_pending → 「歷史可比性」warn；switched → 「剛換類」warn（why 沿用舊句）。"""
    out = []
    if stats is not None:
        p20, _, p80 = stats["raw_mults"]
        r = p80 / p20 if _finite(p20) and p20 > 0 and _finite(p80) and p80 > 0 else None
        out.append(Check("comparability", "倍數分布", "warn", r,
                         f"歷史 80% 位置的倍數÷歷史 20% 位置的倍數＝{r:.1f}，分布寬，三價參考性較低")
                   if r is not None and r > RATIO_WARN else _ok("comparability", "倍數分布", r))
        out.append(Check("comparability", "倍數截斷", "warn", None, "歷史倍數高於上限，已截斷")
                   if stats["capped"] else _ok("comparability", "倍數截斷"))
    cls = cls or {}
    for name, why in (("疑似循環", "疑似景氣循環股（輔助條件未過）"),
                      ("循環未觀察完整", "循環沒觀察完整"),
                      ("僅單一景氣事件", "循環只靠單一景氣事件成立")):
        if name in (cls.get("subtags") or []):
            out.append(Check("comparability", name, "warn", None, why))
    m = cls.get("metrics") or {}
    if m.get("comparability_pending"):
        out.append(Check("comparability", "歷史可比性", "warn", None, "歷史可比性待確認（股本/營收斷點）"))
    if m.get("switched"):
        out.append(Check("comparability", "剛換類", "warn", None, "分類上季剛切換"))
    return out


# ── estimate ──────────────────────────────────────────────────────

def estimate_checks(q: pd.DataFrame, monthly: pd.Series, windows: dict) -> list[Check]:
    """試算季的可靠度。E＝windows["ttm"]、windows["fwd"] 兩窗口所有 EstDetail（依 q 去重）。
    E 為空 → 只回 [Check("estimate","試算季","ok",None,"沒有試算季")]。否則依序：
    1. bridge_residual(q, E[0], windows["reported"].eps 若 reported.ok 否則 None)
    2. nonop_gate(q)（方案 B：只提示）
    3. revenue_caliber(q, monthly)
    3b. revenue_jump(q, E)（方案 B 新增）
    4. variability(q)
    5. E 每個 EstDetail 的 flags（去重）→ 各一條 warn，name＝「稅率／少數股權」，why＝flag 原文
    6. near_zero_eps(windows["fwd"].eps 若 fwd.ok 且 n_est>0，否則 windows["ttm"].eps, q)
    7. forward_jump(windows["fwd"].eps, windows["reported"].eps)（fwd 或 reported 不 ok → 傳 None）"""
    details = {}
    for w in (windows["ttm"], windows["fwd"]):
        if w is not None:
            for d in w.details:
                details.setdefault(d.q, d)
    if not details:
        return [Check("estimate", "試算季", "ok", None, "沒有試算季")]
    reported_eps = windows["reported"].eps if windows["reported"].ok else None
    out = [bridge_residual(q, next(iter(details.values())), reported_eps), nonop_gate(q),
           revenue_caliber(q, monthly), revenue_jump(q, list(details.values())), variability(q)]
    flags = dict.fromkeys(flag for d in details.values() for flag in d.flags)
    out.extend(Check("estimate", "稅率／少數股權", "warn", None, flag) for flag in flags)
    fwd, ttm, reported = windows["fwd"], windows["ttm"], windows["reported"]
    out.append(near_zero_eps(fwd.eps if fwd is not None and fwd.ok and fwd.n_est > 0 else ttm.eps, q))
    out.append(forward_jump(fwd.eps if fwd is not None and fwd.ok else None,
                            reported.eps if reported.ok else None))
    return out


def bridge_residual(q: pd.DataFrame, detail, eps_reported: float | None) -> Check:
    """驗「試算公式本身」（§8：零業外改業外中位數）：對 q 最近 8 個 eps、op_income 皆有限的實際季 i：
      pretax_i = op_income_i + detail.nonop；t_i = 0 if pretax_i ≤ 0 else tax8；
      eps_hat_i = pretax_i × (1 − t_i) × (1 − detail.minority) ÷ detail.shares
    tax8＝1 − Σnet_income ÷ Σpretax_income（同 8 季）；Σpretax ≤0 或 tax8 ∉ [0, 0.35] → 0.20。
    方案 B：影響率 r＝mean|eps_hat − eps| ÷ |eps_reported|（一個試算季的典型誤差占年度 EPS 多少）；
    有效季 <4、eps_reported 為 None／非有限／0 → unchecked（why＝"實際季不足，無法驗證試算公式"）。
    r > BRIDGE_STOP → stop；> BRIDGE_WARN → warn；否則 ok。group="estimate"、name="橋接殘差"、value=r，
    why：f"用試算公式重算近 8 季，單季誤差平均占近 4 季 EPS {r:.0%}"（stop 再加「，試算停用」）。"""
    d = _ordered(q)
    d = d[_series(d, "eps").notna() & _series(d, "op_income").notna()].tail(8)
    if (len(d) < 4 or not _finite(eps_reported) or eps_reported == 0 or not _finite(detail.shares) or detail.shares <= 0
            or not _finite(detail.nonop) or not _finite(detail.minority)):
        return Check("estimate", "橋接殘差", "unchecked", None, "實際季不足，無法驗證試算公式")
    pre = _series(d, "pretax_income")
    net = _series(d, "net_income")
    tax = 1 - net.sum() / pre.sum() if pre.notna().all() and net.notna().all() and pre.sum() > 0 else 0.20
    if not _finite(tax) or not 0 <= tax <= 0.35:
        tax = 0.20
    pretax = d["op_income"] + detail.nonop
    hat = pretax * (1 - np.where(pretax <= 0, 0, tax)) * (1 - detail.minority) / detail.shares
    r = float((hat - d["eps"]).abs().mean()) / abs(float(eps_reported))
    level = "stop" if r > BRIDGE_STOP else "warn" if r > BRIDGE_WARN else "ok"
    return Check("estimate", "橋接殘差", level, r,
                 f"用試算公式重算近 8 季，單季誤差平均占近 4 季 EPS {r:.0%}" + ("，試算停用" if level == "stop" else ""))


def revenue_jump(q: pd.DataFrame, details: list) -> Check:
    """營收劇變（方案 B）：對每個試算季 E（EstDetail.q），P＝q 中 period < E 且 eps、revenue 皆有限的最新一季；
    J＝(E 營收 ÷ P 營收) ÷ (E−4 營收 ÷ P−4 營收) − 1（扣季節性；E−4、P−4 用 q 的實際 revenue）。
    任一營收缺或 ≤0 → 該季不判。取 |J| 最大者：|J| ≥ JUMP_STOP → stop，value=J，
    why＝f"試算季 {E} 營收相對 {P} 的變化比去年同期多 {J:+.0%}，沿用 {P} 利潤率不可靠，試算停用"；
    其餘 ok（value＝最大 |J| 那季的 J，都不能判 → None）。name="營收劇變"。"""
    d = _ordered(q)
    per = d["period_end"].dt.to_period("Q")
    rev = pd.Series(_series(d, "revenue").to_numpy(), index=per)
    ok_q = set(per[_series(d, "eps").notna().to_numpy() & np.isfinite(_series(d, "revenue").to_numpy())])
    best = None
    for det in details:
        e = pd.Period(det.q, "Q")
        prior = [p for p in ok_q if p < e]
        if not prior:
            continue
        p = max(prior)
        vals = [det.revenue, rev.get(p), rev.get(e - 4), rev.get(p - 4)]
        if not all(_finite(v) and v > 0 for v in vals):
            continue
        j = (vals[0] / vals[1]) / (vals[2] / vals[3]) - 1
        if best is None or abs(j) > abs(best[0]):
            best = (j, e, p)
    if best is None:
        return Check("estimate", "營收劇變", "ok", None, "")
    j, e, p = best
    if abs(j) >= JUMP_STOP:
        return Check("estimate", "營收劇變", "stop", j,
                     f"試算季 {e} 營收相對 {p} 的變化比去年同期多 {j:+.0%}，沿用 {p} 利潤率不可靠，試算停用")
    return Check("estimate", "營收劇變", "ok", j, "")


def nonop_gate(q: pd.DataFrame) -> Check:
    """沿用 card-v2 算法；方案 B（11/2 投票）：業外不穩也只提示（典型誤差已反映在橋接影響率）。
    舊 block → warn（why：f"近 8 季業外占稅前 {share:.0%} 且逐季差距大，試算可能偏差"）、degrade → warn。name="業外閘門"。"""
    d = _ordered(q).tail(8)
    nonop = (_series(d, "pretax_income") - _series(d, "op_income")).dropna()
    pre = _series(d, "pretax_income").dropna()
    if len(nonop) < 4 or pre.abs().sum() == 0:
        return _ok("estimate", "業外閘門")
    share = abs(float(nonop.sum())) / abs(float(pre.sum())) if pre.sum() != 0 else 9.9
    med = abs(float(pre.median()))
    disp = float(nonop.quantile(0.9) - nonop.quantile(0.1)) / med if med > 0 else 9.9
    if share >= NONOP_SHARE and disp >= NONOP_DISPERSION:
        return Check("estimate", "業外閘門", "warn", share,
                     f"近 8 季業外占稅前 {share:.0%} 且逐季差距大，試算可能偏差")
    if share >= NONOP_SHARE:
        return Check("estimate", "業外閘門", "warn", share,
                     f"近 8 季業外占稅前 {share:.0%}（穩定，可能是控股/權益法）")
    return _ok("estimate", "業外閘門", share)


def revenue_caliber(q: pd.DataFrame, monthly: pd.Series) -> Check:
    """沿用 card-v2 算法（近 4 季曆季相鄰，用 period_end 推 3 個月）；舊 block → stop。name="月營收口徑"。"""
    from screener.quarterly_prep import last_n_quarters

    d = _ordered(q)
    rev = _series(d, "revenue")
    rev.index = pd.DatetimeIndex(d["period_end"])
    tail = last_n_quarters(rev, 4)
    bad = tot = 0
    if tail is not None:
        for end, revenue in tail.items():
            months = [(end.to_period("M") - i).start_time for i in range(3)]
            vals = [monthly.get(m) for m in months]
            if revenue != 0 and all(_finite(v) for v in vals):
                tot += 1
                bad += abs(float(sum(vals)) / revenue - 1) > REV_CALIBER_TOL
    if tot >= 3 and bad >= 2:
        return Check("estimate", "月營收口徑", "stop", float(bad),
                     f"近 4 季有 {bad} 季月營收合計與季報營收差 >5%，前瞻 4 季不可靠")
    return _ok("estimate", "月營收口徑", float(bad))


def variability(q: pd.DataFrame) -> Check:
    """高變動（§8 新門檻）：P＝最新一季；需要 P、P−1、P−4、P−5 曆季都有 revenue 有限 >0，否則 ok。
    g_now＝rev(P)÷rev(P−1)−1；g_ly＝rev(P−4)÷rev(P−5)−1；d＝g_now − g_ly。
    |d| ≥ VAR_PP → warn，value=d，why＝f"最新一季營收季增減比去年同期多 {d:+.0%}（排除淡旺季後仍偏離），試算延續該季水準"。
    name="高變動"。"""
    d = _ordered(q)
    if d.empty:
        return _ok("estimate", "高變動")
    rev = pd.Series(_series(d, "revenue").to_numpy(), index=pd.to_datetime(d["period_end"]).dt.to_period("Q"))
    p = rev.index[-1]
    v = [rev.get(p - i) for i in (0, 1, 4, 5)]
    if not all(_finite(x) and x > 0 for x in v):
        return _ok("estimate", "高變動")
    delta = v[0] / v[1] - v[2] / v[3]
    if abs(delta) >= VAR_PP:
        return Check("estimate", "高變動", "warn", float(delta),
                     f"最新一季營收季增減比去年同期多 {delta:+.0%}（排除淡旺季後仍偏離），試算延續該季水準")
    return _ok("estimate", "高變動", float(delta))


def near_zero_eps(eps_base: float | None, q: pd.DataFrame) -> Check:
    """沿用 card-v2 算法（近 20 個 TTM 中位數 × NEAR_ZERO_REL）；舊 block → stop，
    why＝f"試算後 4 季 EPS {eps_base:.2f} 遠低於近 5 年中位 {med:.2f}，試算停用"。name="近零EPS"。"""
    from screener.quarterly_prep import last_n_quarters

    if not _finite(eps_base):
        return _ok("estimate", "近零EPS")
    d = _ordered(q)
    e = pd.Series(_series(d, "eps").to_numpy(), index=pd.DatetimeIndex(d["period_end"]))
    if e.count() < 20:
        return _ok("estimate", "近零EPS")
    # 每個窗口都驗證曆季連續，缺季不跨窗。
    totals = []
    for i in range(4, len(e) + 1):
        tail = last_n_quarters(e.iloc[:i], 4)
        if tail is not None:
            totals.append(float(tail.sum()))
    med = float(np.median(totals[-20:])) if totals else None
    if med is not None and med > 0 and eps_base < med * NEAR_ZERO_REL:
        return Check("estimate", "近零EPS", "stop", eps_base,
                     f"試算後 4 季 EPS {eps_base:.2f} 遠低於近 5 年中位 {med:.2f}，試算停用")
    return _ok("estimate", "近零EPS", eps_base)


def forward_jump(eps_fwd: float | None, eps_reported: float | None) -> Check:
    """沿用 card-v2 算法與 why；degrade → warn。name="前瞻跳升"。"""
    if not _finite(eps_fwd) or not _finite(eps_reported) or eps_reported <= 0:
        return _ok("estimate", "前瞻跳升")
    r = eps_fwd / eps_reported
    if r > FWD_JUMP_REL:
        return Check("estimate", "前瞻跳升", "warn", r,
                     f"前瞻 4 季 EPS {eps_fwd:.2f} 比已公布 4 季 EPS {eps_reported:.2f} 高 {r-1:.0%}（>{FWD_JUMP_REL-1:.0%}），營收成長未必全轉成獲利")
    return _ok("estimate", "前瞻跳升", r)
