# 審核回覆：個股查詢／多軌體檢頁圖表改善

> 對應 `docs/REVIEW_REQUEST_2026-09-24b.md`。Opus 確認 5 處 clamp 都對、
> 重新排序沒漏圖，但抓到「策略最長只用 5 年」這個前提是錯的，而且真的
> 造成一個退步（定存軌股利圖）；另外挖到 2 個既有 bug（不是這輪 diff
> 造成的，但剛好在這次動到的函式裡）。Bug 已直接修完；「5 年」這個數字
> 本身要不要改，因為是使用者原本基於錯誤前提做的決定，退回來問。

---

## 已直接修的 Bug

| # | 問題 | 修法 |
| :- | :--- | :--- |
| 1 | 股利圖窗口改成 5 年後，定存軌「連續配息 ≥7年」判準看不到完整佐證資料；`div_cut_5y` 本身也要 6 年；bundle 股利歷史實測最長剛好 13 年 | `DIVIDEND_YEARS_LOOKBACK` 改回 **13 年**（`app/stockcharts.py`） |
| 2 | 三率圖（`margins()`）毛利率吃 TTM 欄位、營益率/淨利率吃單季，同張圖三條線口徑不一致（既有 bug，不是這輪 diff 造成，實測最大可以差 13.5pp） | 改成三條都用單季（新增 `gross_margin_q = gross_profit/revenue`） |
| 3 | 價值/定存軌 caption 寫死「近5年」，但 PE 河流圖實際顯示長度會被 clamp 到 px⋈per 實際重疊資料（可能遠短於5年，實測 2330 只有約2.5年） | caption 改成不寫死年數，講清楚「實際顯示長度依資料而定」 |
| 4 | 註解裡「策略最長只用5年封頂、原本24季/13年是隨手訂的」這個說法本身不成立 | 改寫成準確敘述，並標記 `QUARTERS_LOOKBACK` 為「待使用者重新裁決」 |

新增 3 個回歸測試（`tests/test_charts.py`）：毛利率口徑一致性、新股 clamp
不留白、股利圖年數下限。`pytest -q` 243 passed（240 + 3 新增）。

---

## 退回來問使用者的（不是 bug，是數字要不要改）

`QUARTERS_LOOKBACK`（季度圖窗口：季EPS/三率/ROE/負債比/現金流，目前 5年）
——原本改成 5 年的理由「篩選邏輯最長只用到5年」已經被推翻（定存軌7年
配息、`div_cut_5y`6年、`normalized_eps`需要22季都超過5年）。Opus 的技術
建議是回到原本的 24 季（6年），但這個數字本身沒有造成任何顯示 bug
（TTM/ROE/負債比都是吃完整歷史算好才裁切顯示，5年窗口本身沒有算錯，
只是「5年是最合理長度」這個理由站不住腳了）——**5年、6年、或其他數字，
交給使用者重新決定**。

---

## 其他建議（供參考，不主動套用）

- 固定圖標題「近N年」其實是請求上限，資料不足的新股也會顯示同樣字樣，
  可以改成用資料實際首尾日期算
- Streamlit Cloud 若有舊模組快取，`ch.QUARTERS_LOOKBACK`/`DIVIDEND_YEARS_LOOKBACK`
  不在 `_chart()` 的 try 保護內，部署後如果炸掉記得 Reboot app 或改用
  `getattr` 防呆
- 短線軌拿掉了分頁間的分隔 caption，跟其他三軌不一致；無資料時選擇器
  照樣會出現
- PE 河流圖的河道分位數口徑（用 px⋈per 重疊期間算）跟判準用的
  `screener/pricing.py` 5年per分位不是同一個數，要不要對齊是設計選擇

---

## 測試

`pytest -q` 243 passed。已修改 `app/stockcharts.py`、`app/streamlit_app.py`、
`tests/test_charts.py`，還沒 commit。
