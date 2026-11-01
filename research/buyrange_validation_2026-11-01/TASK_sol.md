# 任務：寫回測腳本 replay.py、bt1.py、bt2.py（台股估值驗證）

只輸出三個 code block，依序是 `replay.py`、`bt1.py`、`bt2.py` 全檔（放在同一資料夾）。不要其他說明。
附檔：PREREGISTRATION.md（**規格，照做，不得改候選格點與通過標準**）、data.py（資料載入，不准改、只准 import）、eps_nowcast.py、multiples.py、detect.py（現有產品模組，只准 `from screener import ...` 呼叫，不准改）。
環境：Python 3.14、pandas 3.x、numpy。**不准用 scipy、不准連網、不准寫入資料夾以外的檔案**。腳本從 `tw-hold/` 根目錄以 `python research/buyrange_validation_2026-11-01/bt1.py` 執行；檔頭用 `sys.path.insert` 讓 `import data`、`from screener import ...` 可用。多 CPU 非必要；請印進度（每個重播點一行）。結果寫在同資料夾 `out/`（程式自行建立）。

## replay.py（共用引擎）
- `replay_dates(start, end) -> list[Timestamp]`：每年 4/1、5/16、8/15、11/15（法定期限後一日），落在 [start, end]。若該日非交易日不需調整（財報可得性只看日期）。
- `point_in_time(d, t, rd)`：回傳該檔在 rd 當時可得資料：
  - q：`d['qf'][t]` 只留 `data.report_deadline(period_end) < rd` 的列；
  - monthly：`d['monthly'][t]` 只留 `data.revenue_deadline(month) < rd` 的月；
  - per：`d['per'][t]` 只留 date < rd；
  不足 8 季財報、或缺毛利欄（gross_profit 全 NaN，金融股）→ 回 None。
- `compute_point(d, t, rd) -> dict | None`：
  - `nc = eps_nowcast.nowcast(q, monthly)`（產品現有簽名：`nowcast(q, monthly, g_far_zero=False)`，q 需有 period_end/revenue/gross_profit/op_income/pretax_income/net_income/ni_parent/eps 欄）；nc['ok'] 為 False → 回 None。
  - TTM_t＝最近連續 4 季 eps 加總（nc['eps_ttm']）；必須 >0 才納入。
  - 目標（要看未來，用完整 d['qf'][t]，**僅供評分，不得流進預測**）：`target4`＝Q_last 之後連續 4 季實際 eps 合計（任一缺 → None）；`target_nc`＝nc['k'] 季之後的實際 TTM（Q_last+k 往前 4 季合計；缺 → None）；`naive_ttm`＝TTM_t；`naive_yoy`＝去年同四季不變即 TTM_t（兩者在本口徑相同，請只保留一個，並另算「去年同季不變」＝Q_last 之後 4 季各取其去年同季實際 eps 的合計 = Q_last-3..Q_last 合計，同為 TTM_t；故兩個樸素預測在此等價，保留一個即可並在摘要註明）。
  - 回傳 dict：t、rd、q_last(Timestamp)、k、eps_nc、eps_f4、eps_ttm、target4、target_nc、flags、params(nc['params'])。
- `eligible_universe(d, rd)`：回傳 `{t: compute_point 結果}`（跳過 None）。對 1019 檔 × 約 30 點要在合理時間（<20 分）內完成；必要時用簡單快取。

## bt1.py（見預註冊 §1）
重播點 2018-04-01～2025-08-15。對每點的 universe：
1. 誤差 e_f4＝(eps_f4 − target4)/target4、e_nc＝(eps_nc − target_nc)/target_nc，只取 target>0 且 eps_f4>0 的樣本；報 P10/P25/P50/P75/P90、中位絕對誤差；樸素預測（TTM 不變）的中位絕對誤差；skill＝1 − MAE_model/MAE_naive。全樣本與「逐重播點」兩張表。
2. 成長訊號：每個重播點對 (eps_f4/eps_ttm − 1) 與 (target4/eps_ttm − 1)（target4>0）做 Spearman rank IC（用 pandas `rank` 自行計算 Pearson of ranks）；平均 IC；Newey-West(lag=3) t（對逐點 IC 序列，自行實作）；以「重播年」為區塊的 bootstrap 95% CI（固定 seed，5000 次）；五分位（逐點內分組後合併）的實際成長中位數，是否 Q5>Q1 與是否單調。
3. 分層：全體、TTM_t 為該股近 5 年 TTM 中位數的 ≥P80 者（用可得季報自行算，≥12 個 TTM 才分層）、營收年增（近 3 月 vs 去年同期）為正／負。
4. 「排除 2026」＝目標季（Q_last+4 的季末）≥ 2026-01-01 的樣本剔除後重算 IC 與誤差。
5. 通過判定（預註冊 §1）：IC bootstrap CI 下界>0 且 Q5>Q1 且排除 2026 後方向不變；另標「F4 是否輸給樸素預測（skill≤0）」。
輸出：`out/bt1_error_by_point.csv`、`out/bt1_ic.csv`、`out/bt1_summary.md`（含上面所有數字與通過／不通過的明確結論，以及母體檔數、NC/F4 可算比例、失敗原因計數）。

## bt2.py（見預註冊 §2、§3）
重播點 2023-08-15～2025-08-15（出場須 ≤ 2026-10-30）。對每點：
1. 母體＝eligible_universe。可信度**只用當時可算的偵測**：`detect.nonop_gate(q)`、`detect.revenue_caliber(q, monthly)`、`detect.bridge_residual(q, nc['params'])`、`detect.shares_check(q)`、nc['flags'] 轉成 Check(degrade)；band 後加 `detect.dist_check(band)`、`detect.near_zero_eps(eps_nc, q)`；以 `detect.confidence(...)` 得等級，只留「高」「中」。**不准用 stock_class.json 與任何分類。**
2. 三價：`b = multiples.band(per_pit, 'per', years=5, min_months=48, cap=30.0, asof=rd)`（資料只含 date<rd）；`p = multiples.prices(eps_nc, b)`；ok 為 False 或 p 為 None → 該檔該點不納入「可買群組」（但仍在對照母體）。**排除**窗內（近 5 年）有股數事件且 |m−1|≥3% 的檔（用 d['events'][t]），因為 PER 沒修。
3. 價格：進場＝rd 之後第一個交易日的 `open`（含息還原價）；出場＝進場日往後第 252 個交易日的 `close`；缺價或出場日超過 2026-10-30 → 剔除。報酬 R＝close_exit/open_entry − 1；另算扣成本版 R−0.006。對照：同點全母體（有價可算者）等權平均 R；0050 以進場日與出場日的 close 比。超額＝R − 等權平均 R。
4. 現價定義＝進場前一交易日 close（rd 當時已知，**不得用進場後價格**）。
5. 群組（預註冊 §2，僅此四組＋P20 子群）：G0：現價 ≤ p['fair'] (P50×NC)；G1：G0 且 eps_f4 ≥ eps_ttm；G2：G0 且 eps_f4 ≥ 1.05×eps_ttm；G3：G0 且 eps_f4 ≥ 1.10×eps_ttm；每組另報「現價 ≤ p['cheap']」子群。「區間外」＝同點可買群組中不屬該組者。
6. 指標與通過判定（四條全過才算過，逐條列出）：(1) 區間內−區間外 平均超額報酬 >0（全樣本）且排除出場日在 2026 之後的重播點 >0；(2) 逐重播點為正的比例 ≥2/3；(3) 剔除該組平均超額貢獻最大的 10 檔後仍 >0；(4) 相鄰格點 G0→G1→G2→G3 方向一致。結論：通過的格點中最寬者；全不過 → 寫「不立買進區間」。另報各組檔數、逐點檔數、勝率、扣成本版。
7. 摘要首段必須固定寫上：「獨立年度約 3、樣本為現行上市櫃（存活者偏差）、區間內外同時暴露於 2026 超級循環；即使通過只算方向性證據」。
輸出：`out/bt2_groups.csv`（逐點逐組）、`out/bt2_summary.md`。

## 一般要求
- 嚴格避免前視：任何用到 rd 之後資料的地方（目標、進出場價）必須在程式裡集中、標註「僅供評分」。
- 缺值用 NaN／None，不丟例外拖垮整批；單檔例外記錄到 `out/errors.csv` 後略過。
- 全部純函式為主，常數放檔頭；以預註冊為準，若預註冊與本任務有衝突，在檔頭註解寫明並以預註冊為準。
