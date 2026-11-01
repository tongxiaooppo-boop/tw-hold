# 任務：寫 Python 模組 screener/multiples.py（含 pytest 測試）

只輸出兩個 code block：第一個是 `screener/multiples.py` 全檔，第二個是 `tests/test_multiples.py` 全檔。不要其他說明、不要改介面。純函式、不讀檔、不連網，只用 pandas / numpy / 標準庫。

## 背景
用某檔股票的歷史本益比（PE）或股價淨值比（PB）日序列，算「月底倍數分布的 P20/P50/P80」，乘以基準 EPS 或 BVPS 得到便宜／合理／昂貴三價。這是「相對自身歷史倍數的位置」，不是內在價值。

## 輸入
`per`: DataFrame，欄位 `date`(日期，可為 str 或 Timestamp)、`per`、`pbr`（float，可 NaN；per≤0 或 NaN 視為無效）。一檔股票的日資料，可能未排序、可能有重複日期（留最後一筆）。

## 函式

### `month_end_values(per, col) -> pd.Series`
取每個日曆月「最後一個有效值（>0 且非 NaN）」；index＝月底那個交易日 Timestamp，遞增。col 為 "per" 或 "pbr"。

### `band(per, col, years, min_months, cap=None, asof=None) -> dict`
- 窗：最後一個有效日（或 asof）往前 `years` 年（years=None＝全部）的月底值。
- 回傳（缺值用 None，不丟例外）：
  `ok`(bool)、`reason`(str|None)、`n_months`、`window_start`/`window_end`(YYYY-MM)、
  `raw`: {"p20","p50","p80"}（numpy percentile 預設線性插值）、
  `capped`: 同鍵，cap 不為 None 時每個值取 min(值, cap)，否則等於 raw、
  `truncated`: bool（cap 不為 None 且 raw 任一值 > cap）、
  `ratio`: p80÷p20（raw）、
  `cap`: 傳入的 cap。
- n_months < min_months → ok=False、reason="有效月數不足（x/min）"，其餘分布欄位仍盡量給。
- 若 capped 後 p50>p80 的情況不會發生（單調），但 p20==p80 時 ratio=1。

### `prices(base, b) -> dict|None`
base＝EPS 或 BVPS（float）；b＝band() 的回傳。base≤0、None 或 b["ok"] 為 False → None。
回 {"cheap": base×capped.p20, "fair": base×capped.p50, "dear": base×capped.p80, "cheap_raw","fair_raw","dear_raw"（用 raw）}。

### `high_pe_exception(per, yearly_eps, years=5, gate=30.0) -> bool`
近 `years` 個完整＋當年日曆年，每一年（至少 years 個有 ≥20 個有效 per 日的年份，否則 False）「該年有效 per 的平均 > gate」，且 yearly_eps（dict {年: 該年 EPS 合計}）裡這些年份都存在且 > 0 → True，否則 False。

### `classify_position(price, p) -> str`
p＝prices() 回傳。price < cheap → "cheap"；≤ dear（含等於 fair 以內）且 ≥ cheap → "fair"；> dear → "dear"；任一為 None → "na"。

## 測試（名稱照寫）
- test_月底取該月最後有效值
- test_無效值per小於等於0被排除
- test_窗年數裁切
- test_有效月數不足_ok為False
- test_cap截斷_truncated為True且capped不超過cap
- test_p20_p50_p80_對線性序列
- test_prices_base非正回None
- test_high_pe_exception_五年都高且獲利為True
- test_high_pe_exception_有一年虧損為False
- test_classify_position三種與na
用合成資料手算預期值。測試檔頭 `sys.path.insert(0, 親目錄)` 後 `from screener import multiples`。
