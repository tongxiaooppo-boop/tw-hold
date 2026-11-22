# from-sonnet-advance-capital-r2
- 完成項：share_basis 新增 LISTED_TOL／capital_for_shares，exchange_outstanding_ratio 與 common_shares 改用；common_shares 在 live＋預收股本＋掛牌股數超過淨股本股數 0.5% 時回 (listed,'listed')。bundle_data.company_basic 加 listed_shares（讀 universe.parquet，缺值 NaN）。screen._cap_basis、build_factors._top500_by_mktcap 改成預收列用 capital_stock、其餘 capital_net。新增 5 條測試。
- commit：見 git log 最新一筆（r2）
- 測試數字：相關 10 個測試檔 181 passed。完整 PROOF_CMD 在本機跑得極慢（test_app_smoke 一條數分鐘、全套 15 分鐘僅 4%），未跑完，需 Opus 自行重跑。
- 改了預期值的舊測試：無（r1 兩條測試原樣通過）。
- 自行採用的小疑問：val_inputs.py 的 company_basic 只是委派 bundle_data.company_basic，故未改該檔；scripts/val2_dryrun_cards.py 與 tests/test_val2_p5.py 的轉接層 company_basic 未動（不在清單），其 basic 無 listed_shares 時視同缺值。build_factors 改為 import screener.screen._cap_basis。
- 需要決定的事：乾跑轉接層（scripts/val2_dryrun_cards.py）是否也要補 listed_shares。
