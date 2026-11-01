"""月營收動能（估值分類框架，2026-11-01 Opus 定介面）。

依據：`D:\\g\\claude\\估值定義定案草案.md` §2。稱「營收動能」，不稱「曲率」。
純函式：不讀檔、不連網。所有成長率、A、D、H 都用**小數**（0.03＝3 個百分點）。

## 定義（介面，不准改）

對月份 m（月初 Timestamp），R(m) 為該月營收：
  g3(m)  ＝ Σ R(m−2..m) ÷ Σ R(m−14..m−12) − 1
  g12(m) ＝ Σ R(m−11..m) ÷ Σ R(m−23..m−12) − 1
  h3(m)  ＝ (Σ R(m−2..m) ÷ Σ R(m−26..m−24))^(1/2) − 1
  A(m)   ＝ g3(m) − g3(m−3)            （加速度）
  D(m)   ＝ g3(m) − g12(m)             （趨勢差，只當背景）
  用到的每個曆月都要有營收（>0、非 NaN）且分母 > 0，否則該值 NaN；A、D 任一來源 NaN → NaN。
  h3 的比值 ≤ 0 → NaN。

節慶旗標（暫定，見回報「待決」）：
  holiday_flag(m)   ＝ g3 的 3 個月窗「只含一、二月其中一個」（m 的月份 ∈ {1, 4}）。
                       窗同時含一、二月（m＝2、3 月）合計已抵銷農曆年移動，不標。
  A_holiday_flag(m) ＝ holiday_flag(m) or holiday_flag(m−3 個月)（m 的月份 ∈ {1, 4, 7}）。

噪音與門檻：
  σ_A(m) ＝ 1.4826 × MAD(A 在 m 之前 36 個曆月內的非 NaN 值；**不含 m 本身**)
           MAD＝median(|A − median(A)|)
  H(m)   ＝ max(H_MIN, H_SIGMA_MULT × σ_A(m))；σ_A 為 NaN（0 個歷史值）時 H＝H_MIN。
  n_hist(m)＝上述窗內非 NaN 的 A 個數。

標籤：
  direction＝"accel"（A > H）／"decel"（A < −H）／None。
  label：g3 > 0 且 accel → "正成長加速"；g3 ≤ 0 且 accel → "衰退收斂"；
         g3 > 0 且 decel → "正成長減速"；g3 ≤ 0 且 decel → "衰退擴大"；direction None → None。
  confirmed＝(m 與前一個曆月 m−1 的 direction 相同且非 None) and n_hist(m) ≥ MIN_A_HISTORY。
  base_note：accel 且 h3(m) ≤ h3(m−3) → "可能主要來自去年低基期"；
             decel 且 h3(m) > h3(m−3) → "可能只是去年高基期"；否則 None（任一 h3 NaN → None）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

H_MIN = 0.03              # 門檻下限 3pp【經驗】
H_SIGMA_MULT = 1.5        # 1.5σ【經驗】
MAD_SCALE = 1.4826
NOISE_WINDOW = 36         # 近 36 個月的 A
MIN_A_HISTORY = 24        # 歷史 A 不足 24 個不下確認標籤
HOLIDAY_END_MONTHS = (1, 4)
A_HOLIDAY_END_MONTHS = (1, 4, 7)

LABEL_ACCEL_POS = "正成長加速"
LABEL_ACCEL_NEG = "衰退收斂"
LABEL_DECEL_POS = "正成長減速"
LABEL_DECEL_NEG = "衰退擴大"
NOTE_LOW_BASE = "可能主要來自去年低基期"
NOTE_HIGH_BASE = "可能只是去年高基期"

METRIC_COLS = ("g3", "g12", "A", "D", "h3", "holiday_flag", "A_holiday_flag")


def momentum_metrics(monthly: pd.Series) -> pd.DataFrame:
    """單一個股月營收 → 逐月動能指標。

    monthly：index＝月初 Timestamp（DatetimeIndex、嚴格遞增；可有缺月）、值＝營收。
    輸出：index＝從輸入最早到最晚的**每一個曆月**（缺月補列），欄位 METRIC_COLS，
      g3/g12/A/D/h3 為 float（定義見檔頭），兩個旗標為 bool（只看月份，與資料有無無關）。
    錯誤：index 非 DatetimeIndex、不遞增或有重複 → ValueError；index 不是月初 → ValueError。
    """
    idx = monthly.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError("index 必須是 DatetimeIndex")
    if not idx.is_monotonic_increasing or not idx.is_unique:
        raise ValueError("index 必須嚴格遞增且不重複")
    if (idx.day != 1).any():
        raise ValueError("index 必須是月初")
    if len(monthly) == 0:
        out = pd.DataFrame({c: pd.Series(dtype=float) for c in METRIC_COLS})
        return out.astype({"holiday_flag": bool, "A_holiday_flag": bool})
    full = pd.date_range(idx[0], idx[-1], freq="MS")
    r = monthly.astype(float)
    r = r.where(r > 0).reindex(full)
    s3 = r.rolling(3, min_periods=3).sum()
    s12 = r.rolling(12, min_periods=12).sum()
    g3 = s3 / s3.shift(12) - 1
    g12 = s12 / s12.shift(12) - 1
    ratio = s3 / s3.shift(24)
    h3 = (ratio.where(ratio > 0) ** 0.5) - 1
    A = g3 - g3.shift(3)
    D = g3 - g12
    out = pd.DataFrame({
        "g3": g3.astype(float), "g12": g12.astype(float), "A": A.astype(float),
        "D": D.astype(float), "h3": h3.astype(float),
        "holiday_flag": [int(x) in HOLIDAY_END_MONTHS for x in full.month],
        "A_holiday_flag": [int(x) in A_HOLIDAY_END_MONTHS for x in full.month],
    }, index=full)
    return out[list(METRIC_COLS)]


def noise_threshold(A_series: pd.Series, asof: pd.Timestamp | None = None) -> dict:
    """噪音 σ_A 與門檻 H（定義見檔頭）。

    A_series：index＝月初 Timestamp 的 A（可含 NaN）。asof 預設＝最後一個 index。
    窗＝[asof − 36 個月, asof − 1 個月]（含兩端，共 36 個曆月；不含 asof 本身）。
    回傳 {"sigma": float（無值→NaN）, "H": float, "n": int（窗內非 NaN 個數）}。
    不丟例外（A_series 空 → sigma NaN、H＝H_MIN、n＝0）。
    """
    nan = float("nan")
    if len(A_series) == 0:
        return {"sigma": nan, "H": H_MIN, "n": 0}
    if asof is None:
        asof = A_series.index[-1]
    lo = asof - pd.DateOffset(months=NOISE_WINDOW)
    hi = asof - pd.DateOffset(months=1)
    idx = A_series.index
    w = A_series[(idx >= lo) & (idx <= hi)].dropna().astype(float)
    n = int(len(w))
    if n == 0:
        return {"sigma": nan, "H": H_MIN, "n": 0}
    med = float(w.median())
    mad = float((w - med).abs().median())
    sigma = MAD_SCALE * mad
    return {"sigma": float(sigma), "H": float(max(H_MIN, H_SIGMA_MULT * sigma)), "n": n}


def momentum_label(metrics: pd.DataFrame, asof: pd.Timestamp | None = None) -> dict:
    """某月的營收動能標籤（定義見檔頭）。

    metrics：momentum_metrics 的輸出（或至少含 g3、A、h3、holiday_flag 欄、index 為逐月）。
    asof：要判斷的月份，預設＝最後一列；不在 index → KeyError。
    前一月（m−1）判 direction 時用**它自己的** H（noise_threshold(A, asof=m−1)）。

    回傳（缺值一律 None／NaN，不丟例外）：
      {"month": Timestamp, "g3", "g12", "A", "D", "h3": float,
       "sigma", "H": float, "n_hist": int,
       "direction": "accel" | "decel" | None,
       "label": 四種名稱之一 | None,      # direction 有值就給（候選）
       "confirmed": bool,                 # 見檔頭
       "base_note": str | None,
       "holiday_flag": bool, "A_holiday_flag": bool}
      g12、D 若 metrics 沒有該欄 → NaN。
    """
    nan = float("nan")
    if asof is None:
        asof = metrics.index[-1]
    if asof not in metrics.index:
        raise KeyError(asof)

    def _val(col: str, m: pd.Timestamp) -> float:
        if col not in metrics.columns or m not in metrics.index:
            return nan
        v = metrics.at[m, col]
        return nan if pd.isna(v) else float(v)

    A = metrics["A"]

    def _dir(m: pd.Timestamp, H: float) -> str | None:
        a = _val("A", m)
        if np.isnan(a):
            return None
        if a > H:
            return "accel"
        if a < -H:
            return "decel"
        return None

    nt = noise_threshold(A, asof)
    direction = _dir(asof, nt["H"])
    g3 = _val("g3", asof)
    label = None
    if direction == "accel":
        label = LABEL_ACCEL_POS if g3 > 0 else LABEL_ACCEL_NEG
    elif direction == "decel":
        label = LABEL_DECEL_POS if g3 > 0 else LABEL_DECEL_NEG

    prev_m = asof - pd.DateOffset(months=1)
    prev_dir = None
    if prev_m in metrics.index:
        prev_dir = _dir(prev_m, noise_threshold(A, prev_m)["H"])
    confirmed = bool(direction is not None and direction == prev_dir
                     and nt["n"] >= MIN_A_HISTORY)

    h_now = _val("h3", asof)
    h_old = _val("h3", asof - pd.DateOffset(months=3))
    base_note = None
    if not (np.isnan(h_now) or np.isnan(h_old)):
        if direction == "accel" and h_now <= h_old:
            base_note = NOTE_LOW_BASE
        elif direction == "decel" and h_now > h_old:
            base_note = NOTE_HIGH_BASE

    def _flag(col: str, months: tuple[int, ...]) -> bool:
        if col in metrics.columns:
            return bool(metrics.at[asof, col])
        return int(asof.month) in months

    return {
        "month": asof, "g3": g3, "g12": _val("g12", asof), "A": _val("A", asof),
        "D": _val("D", asof), "h3": h_now,
        "sigma": nt["sigma"], "H": nt["H"], "n_hist": nt["n"],
        "direction": direction, "label": label, "confirmed": confirmed,
        "base_note": base_note,
        "holiday_flag": _flag("holiday_flag", HOLIDAY_END_MONTHS),
        "A_holiday_flag": _flag("A_holiday_flag", A_HOLIDAY_END_MONTHS),
    }
