# 回報：月營收成長排行（2026-11-20 v1）

## 完成項
- screener/value_rank.py：填 rev_mom、mom_warn、growth_rank
- build_value_rank.py：列加 rev_mom／mom_warn；doc 加 growth（共用 rp）；thresholds 加 mom_warn、growth_top_n
- app/streamlit_app.py：新增 _growth_rank_section，分頁呼叫處共用同一個 _load 結果
- tests/test_value_rank.py +13、tests/test_app_smoke.py +2
- tests/test_glossary.py：加 1 筆 OUTSIDE_OK（見下）

## PROOF_CMD 輸出
- 2026-10 80 80 False 0 30
- [(1,'3661',5.158,False),(2,'2408',4.877,False),(3,'8299',3.463,False),(4,'2344',2.57,False),(5,'2383',2.031,False)]
- 全套：1567 passed, 4 skipped

## 需要 Opus 決定的事
無

## 小疑問自行採用
- test_glossary 的「估值名詞只在估值模組」攔下規格指定的表後 caption（含「合理價」）；在 OUTSIDE_OK 加一筆白名單（同欄位 prices.fair）而非改文案。limit 版 JSON 已刪。
