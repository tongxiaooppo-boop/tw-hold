# 任務：寫 Python 模組 screener/eps_nowcast.py（含 pytest 測試）

只輸出兩個 code block：第一個是 `screener/eps_nowcast.py` 全檔，第二個是 `tests/test_eps_nowcast.py` 全檔。不要其他說明、不要改介面、不確定的地方用檔頭註解寫「假設」。純函式、不讀檔、不連網，只用 pandas / numpy / 標準庫。

## 背景
台股「前瞻 EPS」試算。用「已公布的季報」＋「月營收」，推估尚未公布季度的單季 EPS。

## 輸入
- `q`: DataFrame，一檔股票，每列一個已公布單季，欄位：`period_end`(季末 Timestamp，3/31 6/30 9/30 12/31，遞增，可缺季)、`revenue`、`gross_profit`、`op_income`、`pretax_income`、`net_income`（合併淨利）、`ni_parent`（歸母淨利，可為 NaN，NaN 時用 net_income）、`eps`（單季）。金額單位元，eps 單位元/股。
- `monthly`: pd.Series，index＝月初 Timestamp（例 2026-09-01），值＝該月營收（元），遞增。最新月可能還在季中。
- `g_far_zero`: bool，True 時遠季成長率用 0（循環股用）。

## 輸出 `nowcast(q, monthly, g_far_zero=False) -> dict`
鍵（缺的值用 None，不要丟例外；只有 q 不是 DataFrame 才丟 TypeError）：
- `ok`: bool；`reason`: str|None（ok=False 的原因）
- `last_q`: Timestamp（最後已公布季末）；`last_month`: Timestamp（月營收最新月）
- `k`: int，最新月所在季 − 最後財報季的季數（0=月營收沒超過已公布季）
- `eps_ttm`: 最近連續 4 季 eps 加總（缺季/NaN → None）
- `eps_nc`: 滾動前瞻四季＝最近 (4−k) 季實際 eps ＋ k 季試算 eps。k=0 → 等於 eps_ttm。k>3 或試算失敗 → 退回 eps_ttm 並在 `flags` 加 "EPS_NC 退回已公布 TTM"、`fallback`=True
- `nc_quarters`: list[dict]，四季明細 `{"q": "2026Q3", "kind": "actual"|"est", "eps": float, "rev": float|None, "gm": float|None, "op": float|None, "nonop": float|None}`
- `eps_f4`: 最後財報季之後的 4 個季度試算 eps 合計；`f4_quarters`: 同格式明細（kind 皆 "est"）；`f4_far_quarters`: int（完全沒有月營收、純趨勢外推的季數）
- `params`: dict：`t`(有效稅率)、`m`(非控制權益比)、`shares`、`gm_ttm`、`opex_ratio`、`nonop_med`、`g3`、`g12`、`g_far`
- `flags`: list[str]，降級原因（中文，不重複）

## 演算法（照做，數字常數放檔頭）
1. 季別用曆季（Q1=3 月）。月營收季 = 該月所在曆季。
2. `g3` = 最近連續 3 個月合計 ÷ 去年同 3 個月合計 − 1（任一缺 → None→ 視為失敗）；`g12` = 最近連續 12 月合計 ÷ 前一年同 12 月 − 1（缺 → None，g_far 用 0）。
3. 單季營收 `rev_q`：該季的月份，已公布月照實；未公布月 = 去年同月營收 ×(1+g3)（去年同月缺 → 該季失敗）。若該季完全沒有任何已公布月（遠季），rev_q = 去年同季財報營收 ×(1+g_far)，g_far = 0 若 g_far_zero 否則 g12×0.5（g12 None 則 0）；去年同季財報缺 → 失敗。去年同季若是本函式自己前面推出的季（例如 F4 的第 5 季以後）不會發生（F4 只推 4 季，其去年同季都 ≤ 最後財報季）。
4. 毛利率 gm_q = TTM 毛利率（最近 4 季 gross_profit 合計 ÷ revenue 合計）＋ 季節偏差 s_q。s_q：過去最多 3 年「該曆季毛利率 − 當時的 TTM 毛利率（含該季的連續 4 季）」的平均；觀察值少於 2 個、或正負號不一致 → s_q = 0。
5. 營業費損 = gross_profit − op_income（不是純銷管）。opex_ratio = 最近 4 季 費損合計 ÷ revenue 合計；opex_q = opex_ratio × rev_q（隨營收同比）。op_q = rev_q × gm_q − opex_q。
6. 業外 N：近 8 季（不足 8 季但 ≥4 季也行）單季 (pretax_income − op_income) 的中位數，逐季沿用。
7. 稅：取近 8 季（不足 ≥4 季也行）t = 1 − Σnet_income/Σpretax_income。pretax 合計 ≤ 0 → t=0。t 不在 [0, 0.35] → 用 0.20 並 flags 加 "稅率超界，改用 20%"。
8. 少數股權 m = 1 − Σni_parent/Σnet_income（近 8 季同樣口徑；ni_parent NaN 用 net_income）。|m| > 0.30 → flags 加 "少數股權比重大"。
9. 股數 shares = 最近 4 季中 |eps|≥0.05 者，(ni_parent ÷ eps) 的中位數（>0 者）；推不出 → ok=False。
10. eps_q = (op_q + N) × (1−t) × (1−m) ÷ shares。
11. 滾動四季：k 季試算（最後財報季之後的 k 個季，到最新月所在季為止）＋最近 (4−k) 季實際 eps（這些實際季必須連續且存在，否則失敗）。
12. F4：最後財報季之後連續 4 季都試算；每季：有任何已公布月 → 用規則 3 的月份法；否則遠季法。f4_far_quarters = 遠季數量。
13. 任何 eps_q 為 NaN → 該路徑失敗：eps_nc 退回 eps_ttm（flag），eps_f4=None。

## 測試（至少這些，名稱照寫）
- test_k0_月營收沒超過財報季_eps_nc等於ttm
- test_k1_最新月在下一季中_補一季試算
- test_k2_最新月在下兩季_補兩季試算
- test_g3用合計不用單月
- test_遠季成長率為g12一半
- test_循環股遠季成長為0
- test_稅率超界改用20且加旗標
- test_股數推不出_ok為False
- test_去年同月缺_退回ttm並加旗標
- test_季節偏差正負不一致為0
用合成資料（例如每季營收 100、毛利率 30%、費損率 20%、業外 5、稅 20%、m 0、shares 10 之類，手算預期值寫進斷言）。pytest 檔頭用 `sys.path.insert(0, 親目錄)` 讓 `from screener import eps_nowcast` 能 import。
