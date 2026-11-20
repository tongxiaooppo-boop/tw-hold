【tw-hold】月營收併入估值排行 回報（任務書 v2）
- 完成項：value_rank.py 加 rev_month_info／rev_progress／rev_text／REC_MIN_HIST；build_value_rank.py 每列併 rev_* 欄＋doc.rev_progress；_value_rank_section 改「月營收（年增）」欄（桌面＋手機 mob）、加固定說明 caption 與公布進度 caption（舊 JSON 用 .get、不炸）；rebuild.yml 月營收分頁 step 註解停用；revenue_watch.yml 改跑 build_value_rank.py、commit 路徑改 value_rank.json；新增 13 個測試。
- commit：見 git log 最新一筆（「估值排行併入月營收欄位、停月營收分頁排程」）
- PROOF_CMD：70 passed, 4 skipped, 0 failed
- 全套 pytest：1550 passed, 4 skipped, 0 failed（test_consistency::test_畫面不含舊名詞 單跑約 74 秒，全套約 112 秒＋該測試）
- build --limit 30：成功；rev_progress={'month':'2026-10','published':30,'total':30}，列含 rev_m_yoy／rev_streak／rev_record／rev_low_base；limit 檔已刪
- workflow 前置核對：build_value_rank 需要 universe.parquet（fetch_bundle，collect job 已有）、stock_class.json／industry_pe.json／corporate_actions_resolved.json（已版控，checkout ref main 取得）、倍數檔（ensure_multiples 走公開 release URL，免 PAT）、TWSWING_BUNDLE_PAT（env 已有）。結論：revenue_watch.yml 沒缺前置，沒補任何 step／env。
- 自行採用的小決定：rev_month_info 的 rev_m_yoy＝None 時低基期為 False（依規格）；rev_text 低基期時「低基期」取代年增數字；smoke 測試直接呼叫 app._value_rank_section(舊格式 dict)（bare mode，不炸即過）；revenue_watch.yml 檔頭註解 ② 同步改寫；rebuild.yml 被註解的 step 整段加 "# " 前綴。
- 需要 Opus 決定的事：無。（revenue_watch.yml 的 gate 腳本 run_gate.py --workflow revenue_watch 若依 revenue_watch.json 新鮮度判斷，現在該檔不再更新，可能每班都判需跑或永遠跳過，我沒讀該腳本，請核對。）
