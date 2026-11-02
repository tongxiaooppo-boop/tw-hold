# 估值 2.0 分階段計畫（Opus 定，2026-11-02）

> 規格：`docs/val2/upgrade_guide.md`（以它為準）。分支：`val2`（本地分階段，**上線一次**：P5 驗收後才合回 main、push）。
> 每階段：Opus 寫任務書 → sol（Codex 訂閱）在 `d:\g\claude\val2_work\repo`（clone 自 val2）實作 → Opus 驗收、複製回 val2 commit。
> 介面（本目錄骨架檔的簽名、dataclass、常數、測試預期值）實作者不得改；覺得有問題停下回報。

| 階段 | 內容 | 檔案 | 測試 | 驗收 |
|---|---|---|---|---|
| **P0** 框架 ✅ | 骨架、介面、測試預期值；`growth.py` 完整實作 | `screener/growth.py`、`screener/eps_windows.py`、`reference/share_basis.py`、`screener/multiples_self.py`、`build_multiples.py` | `test_val2_growth.py`（過）、`test_val2_eps_windows.py`、`test_val2_share_basis.py`（待 P1） | — |
| **P1** 地基 | `eps_windows`、`share_basis` 實作；全市場乾跑三窗口（不接任何 caller） | 只改 P1 兩檔＋新增乾跑腳本 `scripts/val2_dryrun_windows.py` | P1 兩個測試檔全過、既有全套不退步 | 全市場 3 窗口 status 分布、n_est 分布、0 例外；抽 2330／2327／2881／5289／1815 |
| **P2** 自建倍數 ✅ `e54039d` | `multiples_self`、`build_multiples`（月度序列、eps_revision、industry_pe、核對；上修判斷 `revision_event`／`revision_streak` 也在這階段）；原始收盤先用本機 `prices_raw_close`＋tw-swing `prices_raw` 合併（bundle 檔留 P5） | P2 兩檔＋測試 | `test_val2_multiples.py`（20 條，含 §10 自建 PE／減資剔除／有效月數／AB 緩衝／上修） | 自建 vs 交易所中位差分布；>2% 逐檔列；純分割連續 |
| **P3** 估值卡引擎 | `val_card` 改寫（分層 A～D、三價、前瞻三價、購買區間、B／C 層）；`detect` 可信度四組；`classify`／`build_classification` 刪死狀態＋遲滯重算；`candidate_pool` 改用 `growth`；`eps_nowcast` 刪窗口邏輯 | 見 guide §1 | §10 其餘＋既有測試改寫 | 全市場分層檔數、翻轉清單抽 20、指定 12 檔 |
| **P3b** 分類／推薦卡 ✅ | 規格 `docs/val2/P3b_spec.md`：classify 刪死狀態、金融閘門看 EPS、`by_type` 遲滯後重算；build_classification 金融有效檔＋`coverage_mktcap_k`；loader 歸母淨利頂替集中；candidate_pool 用 growth。**eps_nowcast 移到 P4 整檔刪**（已無引擎呼叫） | P3b_spec §1～4 | `test_val2_p3b.py` | 金融資料不足＝0、新舊分類交叉表、subtags_recomputed 清單、推薦卡進池差異 |
| **P4** 畫面 | 估值卡、三個展開區（§9-1／9-2／**9-3 卡片↔展開對照、📌 標記**）、怎麼算規則表；全站改名（§15）；河流圖與體檢本益比（§15-4）；`test_glossary` | `app/` | §15-3、15-4、`test_畫面不自己算` | 桌面＋手機截圖（Playwright） |
| **P5** 資料與上線 | 自建上游收 `company_basic`；tw-swing bundle 加 `monthly_raw_close`；rebuild.yml 接 `build_multiples`；使用說明網頁；拿掉「開發中」 | workflows、selfhost、tw-swing | 全套 | guide §11 全項 → 合回 main、push、Reboot |

## 不准做的事（每階段任務書都重申）
- 改骨架介面、常數值、測試預期值。
- 動該階段範圍外的檔案；「沒寫到的舊行為一律維持」。
- 網路搜尋；在 repo 與 `d:/g/claude/` 以外寫檔。
