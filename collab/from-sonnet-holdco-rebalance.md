# 回報：換股日挪到金控期限＋1 天（任務書 v1）
- commit：見下方（git log 最新一筆「實作：換股日…」）
- PROOF_CMD：test_rebalance_holdco 27 passed；PROOF_CMD 整條 7 failed / 53 passed（7 條在 test_build_classification.py，見「需要決定的事」）
- 全套：改前 32 failed／1602 passed／4 skipped；改後 7 failed／1627 passed／4 skipped
- HOLDCO import：build_factors.screen_all 函式內 `from build_lists import HOLDCO`（避免循環）
- 需要決定的事：tests/test_build_classification.py 有 7 條 gate 測試寫死舊換股日（today="2026-11-14"／"2026-11-13"，Q3 季更閘門），REBALANCE_FOR_QUARTER 依任務書改成 12/1 後必然失敗（why 變成「未到換股日 2026-12-01」）。解法是把這些測試的日期改 11/14→12/1、11/13→11/30（只改輸入日期，預期不變），但任務書禁改測試，所以沒動。失敗：test_gate_coverage_ok_and_newer_than_snapshot、waits_until_rebalance_day、after_rebalance_but_low_coverage_says_so、分母是上一季有效股票、必要欄位空值不算涵蓋、結構性缺欄、同季補資料才重建。
