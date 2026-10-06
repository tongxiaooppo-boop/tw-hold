# 自建 → data_pack 轉接層（備援用）

> 2026-10-06 寫成。**平時仍用現有上游（tw-stock-scanner 的 data_pack）；這個轉接層只是上游掛了時的後路**，目前沒有任何排程或下游使用它。

## 做什麼
`scripts/selfhost_to_datapack.py` 把 `data/selfhost/*.parquet` 轉成 tw-swing 現行匯入吃的 `data_pack.zip` 格式，**下游（tw-swing 匯入、bundle、tw-hold）完全不用改**。

| zip 內檔案 | 內容 | 來源 |
| :-- | :-- | :-- |
| `data/{code}.TW.csv`／`.TWO.csv` | `Date,Open,High,Low,Close,Volume`（還原價；NaN 量補 0） | `adj_prices`（官方未還原價 × 官方因子） |
| `data/institutional/{code}_inst.csv` | 外陸資、投信、自營、合計（欄名用 tw-swing `normalize_institutional` 認得的新格式） | `inst` |
| `data/margin/{code}_margin.csv` | 融資融券（單位：張）＋ `margin_prev`／`short_prev`／`note` | `margin` |
| `data/stock_list.csv` | `ticker,code,name,market(上市/上櫃),sector` | 市場別取自自建實價；名稱與產業別取 `--stock-list`（tw-swing 的 stock_list）或 `--universe`（bundle 的 universe）；都沒有就留空 |

不輸出：集保（data_pack 的集保已停更，tw-swing 有自己的週快照）、融資融券限額（自建沒有，tw-swing 匯入也不讀）。預設只轉 4 碼（與自建收集範圍一致）。

```
python scripts/selfhost_to_datapack.py --out data/selfhost/data_pack_selfhost.zip --stock-list ../tw-swing/data/store/stock_list.parquet
python scripts/selfhost_datapack_parity.py --zip data/selfhost/data_pack_selfhost.zip --swing-root ../tw-swing --json out.json   # 驗收
```
⚠️ tw-swing 匯入後仍要緊接 `apply_chips_baseline.py`（FinMind 修好的籌碼歷史底稿疊回），順序不變。

## 驗收結果（2026-10-06，全量 2,147 檔，zip 約 202MB）
用 tw-swing 自己的 `import_data_pack.parse_one` 與 `chips.normalize_*` 解析，與 tw-swing 現行 store 逐項比（不寫入任何 store）：

| 項目 | 結果 | 說明 |
| :-- | :-- | :-- |
| 能否被 tw-swing 解析 | ✅ 2,147／2,147 日線檔、全部法人／融資券檔解析成功，0 失敗 | |
| 融資券 | ✅ 9 個欄位全部 **100% 相符**（440 萬列） | 自建多 15.6 萬列（2015–2022 歷史 tw-swing store 沒有，自建有） |
| 法人 | ✅ `foreign_net` 99.95%、`trust_net` 99.95%、`total_net` 99.74%、`dealer_net` 99.37% | `fi_prop_net`（外資自營商）只 49.5% 相符：自建在舊格式年代是空值、store 是 0（FinMind 底稿疊回後會一致）；`dealer_net` 差異多為 store 空值而自建有值 |
| **還原價** | ⚠️ 全期 ≤0.2% 只佔 26.0%；近 365 天 49.2% | **差異的來源幾乎都是上游的還原接縫缺陷（見下）**，不是轉接層的錯 |
| 成交量 | 自建比上游高約 3～11%（2330 約 +11%） | 口徑差：自建用官方量（含零股、盤後定價），上游（Yahoo）較低；已知、已接受 |

**還原價差異歸因**（近 365 天，|變動|>0.5% 的 1,432 個「比值變動點」）：
- **91.6%** 的變動點出現在**我們事件表的下一個事件之前 1～14 天內，峰值是 8 天前（64%）、7 天前（16%）**——正是「上游只重抓最近 7 天，除權息日前超過約 8 天的歷史停在尚未套用該事件的水位」的接縫特徵（docs/data-fix.md C9、HANDOFF「上游還原接縫缺陷」）。
- 變動點集中在除息旺季（2026-06～08）的少數日期，單日 30～90 檔同時出現，也是接縫的群聚特徵。
- 全期另有上游母表的**單日異常**（2021-08-17／18 約 600 檔、2020-03-13／16 約 500 檔），也使比值出現跳動。
- 所以「近一年相符率」與先前 `selfhost_recon.py` 的 89.5%（先用官方因子訂正已偵測到的接縫再比）不衝突：那份有先訂正接縫。

## 結論與限制
- **格式與單位已驗證可被 tw-swing 的匯入吃進去**；融資券與法人實質一致。
- 還原價與現行 store 不會逐列相同，原因是上游有已知缺陷；**真要切換時**，規則驗證／回測／保留段都建立在舊數字上，**必須先出「訂正前後影響報告」**（本轉接層不處理）。
- 尚未做（本週範圍外）：tw-swing 端的 `--pack-source selfhost` 切換、產 zip 的手動 workflow、tw-swing 讀私有 Release 的唯讀 PAT。見 HANDOFF〈本週待辦〉。
