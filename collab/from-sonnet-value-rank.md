# 【tw-hold】回報：合理價以下排行（Sonnet，2026-11-19）

## 完成項
- 第 1 步：screener/value_rank.py（四個純函式＋常數，照任務書）。
- 第 2 步：build_value_rank.py（照 build_revenue_watch 結構；--limit 寫 value_rank.limit.json）。
- 第 3 步：rebuild.yml 在「月營收分頁」後加一步（continue-on-error、帶 TWSWING_BUNDLE_PAT；commit 步是 git add data/derived/ 已會帶到）；streamlit_app.py 加 _value_rank_section＋價值分頁一行呼叫。
- 測試：tests/test_value_rank.py 12 條。

## PROOF_CMD
1. 12 passed。
2. 全 500 檔 2m41s：
   `500 500 202 {'一般': 20, '循環': 20, '高成長': 20}`
   `['2377', '6781', '2031'] ['2392', '1419', '1605'] ['5289', '8112', '3702']`（assert 通過；與預期相符）
3. 全套：1 failed, 1524 passed, 4 skipped（3m24s）。失敗＝tests/test_glossary.py::test_glossary_估值名詞只在估值模組。

## 需要 Opus 決定（卡住）
test_glossary 規定畫面字串不得出現「合理價／便宜價／近 4 季 EPS」（估值模組以外），新畫面 7 處命中（標題、說明、欄名「便宜價」「合理價」「距合理價（%）」、底部 caption）。該測試自己允許在 OUTSIDE_OK 加條目（要寫理由），但任務書禁改既有測試，我嘗試改被權限擋下，故沒改。
選項：A 在 tests/test_glossary.py 的 OUTSIDE_OK 加 7 條（理由：值取自同一張估值卡 prices.fair/cheap；我建議）；B 畫面改用別的詞（偏離使用者指定「合理價」）。
這 7 條 (檔, 名詞, 字串片段)：合理價/合理價以下排行、合理價/股價在合理價（含）以下、便宜價/便宜價、合理價/合理價、合理價/距合理價（%）、近 4 季 EPS/近 4 季 EPS 超過前 3 年平均、合理價/合理價依各股歷史倍數。
commit 因此帶著這條紅燈。

## 自行採用的小決定
- rank 額外排除 fair ≤ 0；eps_ratio／revenue_growth 缺欄位回 None。
- 母體 ticker 用 split('.')[0] 對 stock_class；lag 比較用字串大小（季別格式 YYYYQn 可比）。
- 全跑後 data/derived/value_rank.json 留在本機未 commit；limit 試跑檔已刪。
