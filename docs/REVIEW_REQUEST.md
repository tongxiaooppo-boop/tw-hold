# 簽呈：tw-hold 專案拆分 + tw-swing 文件校準 — 請 Opus 審核

> ## ✅ 已結案（2026-09-07 晚）
>
> **審核結論：需修正後可動工。** 8 條修正**已全部套用**，不需要再審一次。
> 這份簽呈保留當歷史紀錄（當初問了什麼、為什麼這樣答），**不要照它動工**——
> 它描述的是修正前的方案。
>
> | 想知道 | 看哪裡 |
> | :--- | :--- |
> | 修正後的規格 | `tw-hold/PRD.md` **v2.1**（§11 有修正清單；**§10 是跨 repo 失敗模式與守門員**） |
> | 修正後的執行 checklist | `tw-hold/docs/PLAN.md`（M0 已拆 M0a/M0b） |
> | tw-swing 這邊要做什麼 | `tw-swing/PRD.md` §7.1.1〈審核修正〉＋ `tw-swing/docs/STATUS.md`〈tw-hold 上游交付〉 |
>
> **8 條修正摘要**：① U1 拆 U1a/U1b，`daily.yml` 不動 → M0 不必等 11 月
> ② bundle 改走 tw-swing 私有 Release + PAT，不建公開 `tw-hold-data`
> ③ 市值資料源列為 M0 硬前置（`universe` 沒市值/產業、`capital_stock` 補抓當掉、
> 前 500 是成交值排的）　④ `loader.py` 改為搬走、tw-swing 端 `value/` 整包刪除
> ⑤ 估值上緣退出 verdict ＋ 循環高峰旗標　⑥ 買入區間倒置處理、刪空條件「單檔 ≤ 30%」
> ⑦ 長波段加 `positions.json` 持倉登錄 ＋ 措辭改「條件成立區間」＋ v1.5 補跑一次回測
> ⑧「新進/移除」讀上一期 `lists/*.json`，不靠 git diff
>
> **未採納的挑戰**：無。第 4 節 6 個挑戰點全部有結論，其中 ⑥（tw-swing PRD 維護模式）
> 判定「現行模式可持續、不重寫」，只在 §3.1／§5.2 各補一行「本節是設計快照」紅字。

---

> **給接手審核的你**：這是一份自足的簽呈。你在全新對話、沒有上下文。
> 讀完這份 → 讀下面列的 4 份文件 → 回答最後〈請你回答〉那 4 題。
> 環境：Windows，`d:` 磁碟 `\g\claude\` 底下有 `tw-swing\`、`tw-hold\`、`books\`。

---

## 1. 背景（30 秒）

- **tw-swing**（`d:\g\claude\tw-swing\`）：台股**短波段**交易系統，成熟、在跑。
  live 是 pool1 `[A3, C3, H2]` + pool2 `[G7, V6-trailatr2]`，皆模擬單中；有 gate +
  樣本外 + 熔斷 + 五道真錢門檻；G-5 的「管線連續 60 交易日無中斷」時鐘運行中，鎖 11 月下旬。
- 使用者另外想做一個**價值 / 定存 / 長波段的決策支援工具**——`me`
  （`books\claude\me\taiwan-stock-analyzer-v3`，上一代專案，「什麼都做卻沒鳥用」）的升級版。
- **2026-09-07 一天內連續改判**：
  1. 先想「把價值/定存加進 tw-swing」→ 同日 AI 提醒「加著加著程式會失去焦點」（兩套
     工程紀律：一個上真錢要 gate、一個不上真錢是決策支援）→ 決定**拆成獨立專案 `tw-hold`**。
  2. 再一輪：估值方法從「投信經理人：forward EPS × 市況調整 PE → 目標價 → 安全邊際」
     改成「**被動式市值型 + 高股息低波動 ETF 的規則化指數框架**」（使用者原話要求用這個
     評估法），並把「長波段」從被動框架裡**拉回主動**（塞進季換股是類別錯誤）。
- **後果**：tw-swing 的文件同時存在「明確不做價值/定存」（PRD §7.1）與「在 tw-swing 做
  價值/定存」（STATUS 三大段）兩種描述。已做過一輪校準，**要你確認校準對不對、還有沒有矛盾**。

---

## 2. 要審的東西

| # | 檔案 | 是什麼 |
| :- | :--- | :--- |
| 1 | `d:\g\claude\tw-hold\PRD.md` | 新專案規格（**已凍結**）。§6/§7 是估值方法論的最終版 |
| 2 | `d:\g\claude\tw-hold\docs\PLAN.md` | M0–M4 執行 checklist（比照 tw-swing 的 PLAN 體例） |
| 3 | `d:\g\claude\tw-swing\PRD.md` | 看**新增的 §7.1.1**（改判留痕）＋ §1.3–1.5 改寫＋狀態列/§5.3/§6.2 校準 |
| 4 | `d:\g\claude\tw-swing\docs\STATUS.md` | 看〈tw-hold 上游交付〉那節（U1–U3）＋ 價值方法論已刪除改指到 tw-hold |

**輔助**：`d:\g\claude\tw-hold\` 的介面草模在 `...\Temp\claude\...\scratchpad\tw-hold-mock.html`
（四分頁 + 買價兩方案對照，範例資料）。tw-swing 的 `rules.yaml` / `docs\RULE_LEDGER.md` /
`docs\BENCH.md` 是規則現況的真實來源。

---

## 3. 關鍵設計決策（請逐一 sanity-check）

| | 決策 | 出處 |
| :- | :--- | :--- |
| **A 架構** | tw-swing 加 publish step → 把財報/日線/PER 整併/universe 打包成 bundle 推**公開 repo `tw-hold-data`**；tw-hold `fetch_bundle.py` 用 HTTP 拉；共用碼（loader/regime/indicators/finmind client）**複製**進 `tw-hold/reference/`，**不 import `twswing`**；tw-hold 每日 Action 重算三清單 commit 回自己 repo；執行期對 `twswing` package 零依賴 | tw-hold PRD §3、tw-swing PRD §7.1.1 |
| **B 佈署** | Streamlit Community Cloud；個股即時補抓 FinMind **只在本地**，雲端只服務前 500 大 | tw-hold PRD §8 |
| **C 評估法分軌** | 價值/定存 = 規則化因子指數（季換股 3/6/9/12、陷阱硬剔除、透明因子 rank、產業上限 40%）；長波段 = **維持主動**（每日重算清單、擇時進場、進場前寫死出場規則檢查表） | tw-hold PRD §2B、§5、§6、§7 |
| **D 價值估值** | **刪** v1.0 的「forward EPS × 市況 PE → 目標價」機器（三層外推疊乘）。改：主表「你買進的殖利率」（盈餘/FCF/EV-EBIT，不預測價格）＋ 明細「估值上緣 = TTM_EPS × P70(自身近5年 trailing PE)」＋ 便宜門檻 = normalized_EPS × P30。`regime.classify()` 降為**顯示旗標**、不進公式 | tw-hold PRD §6.2 |
| **E 定存新門檻** | 硬門檻加「近 5 年平均填息率 ≥ 60%」「近 3 年含息年化報酬 ≥ 0」；成分單一產業 ≤ 40% | tw-hold PRD §7.1 |
| **F tw-swing 移出** | `src/twswing/value/factors.py`、`screen.py`、`scripts/build_value_factors.py`、`tests/test_value.py` → M0 搬去 tw-hold（tw-swing 核心無 import，只有 build/test 用）。`loader.py` 留 tw-swing + tw-hold 複製一份 | tw-swing PRD §7.1.1 |

---

## 4. 我特別想要你挑戰的點

1. **複製共用碼 vs import / submodule**：`loader.py`（parquet→季度面板 + 45 天公告日遞延）
   在 tw-swing 留一份、tw-hold 複製一份——兩份會不會漂移？有沒有更好的切法（例如
   把 loader 抽成一個獨立的小 package 兩邊都 pip install）？

2. **公開 `tw-hold-data` repo**：放 FinMind 衍生的財報/估值數字。FinMind 的 ToS、
   資料授權、以及「把它整包公開」有沒有法律或 ToS 風險？獨立公開 repo vs
   tw-swing 私有 repo 的 Release + PAT，哪個對？

3. **價值估值「兩個都給」**：使用者本來擔心拔掉目標價引擎「感覺哪裡不對」，最後
   決定殖利率（主）+ 估值上緣（明細）都顯示。這會不會又變成 `me` 那種「資訊很多
   但不知道要幹嘛」？估值上緣用 `TTM_EPS`、便宜門檻用 `normalized_EPS` 的**不對稱**
   （成長股不被 CAPE 懲罰、但便宜 gate 保守），這個設計站得住嗎？

4. **長波段的驗證豁免**：長波段清單「每日重算 + 進場前寫死出場規則」，但**不回測、
   不進資金池、參數用合理預設不調校**。tw-swing 的紅線是「規則未過回測不得上線」
   「訊號不得提前當建議」。tw-hold 以「決策支援工具、不上真錢」豁免這條——界線
   畫得對嗎？還是長波段該至少過一次 tw-swing 的回測引擎？

5. **一個月 timebox（~10 session）現實嗎**：M0 依賴 tw-swing 先落 publish step（U1），
   而 tw-swing 的 11 月關鍵路徑（G-5、10 月分池揭露）**優先**、`daily.yml` 上線前
   不能碰。會不會 M0 永遠卡在 U1？要不要 M0 先用「手動打包 bundle 放本地」起步、
   publish step 延後？

6. **tw-swing PRD 的維護模式**：這次是「骨幹章節保留 + 加免責聲明（現況以 rules.yaml
   /workflows/STATUS 為準）+ 逐案增補小節」，而不是整份重寫。§5.2 的 7 條規則目錄、
   §3.1 的架構圖都還是舊的。這個模式可持續嗎？還是骨幹也該重寫一次？

---

## 5. 不用審的（已凍結 / 已定案，審了也不會改）

- **tw-swing 的短波段系統本體**（pool1/pool2、rules、backtest、G 門檻、daily.yml）——這次沒動。
- **因子公式細節**（Piotroski F-Score、normalized PE、存股安全分的算法）——沿用 tw-swing
  `twswing.value.factors/screen` 既有實作，只是搬家。
- **要不要拆分**——使用者已定案。要的是「拆得對不對、文件一致不一致、方案可不可行」。
- **repo 命名**（tw-swing / tw-hold 成對）、**F-Score 9 分項不加總不當 verdict**——已定。

---

## 6. 現狀（都還沒 commit）

- **tw-swing**：7 檔改動未 commit（`PRD.md`、`README.md`、`docs/PLAN.md`、`docs/STATUS.md`
  + `src/twswing/value/__init__.py`、`screen.py`、`scripts/build_value_factors.py` 的
  **docstring/註解**）。`786 tests pass`、`check_rule_coverage.py [OK]`。核心邏輯零改動。
- **tw-hold**：`PRD.md`、`docs/PLAN.md`、`PLAN.md`（指標頁）、`README.md`、
  `docs/REVIEW_REQUEST.md`（本檔）未 commit。`factors/ screener/ charts/ app/ reference/
  tests/` 是空目錄，程式還沒開始寫。
- **程式碼移動**（`twswing/value/factors.py` 等 4 檔 → tw-hold）**還沒做**，等你審。

---

## 7. 請你回答

1. **這個拆分方案可不可以動工？**（可 / 需修正後可 / 不可）
2. **第 4 節 6 個挑戰點**各自的判斷（尤其 2、4、5）。
3. **M0 有沒有遺漏的前置依賴？** 執行順序（U1 先 or 搬檔先 or 手動 bundle 起步）建議。
4. **文件還有沒有互相矛盾的地方？**（tw-hold PRD ↔ tw-hold PLAN ↔ tw-swing PRD §7.1.1
   ↔ tw-swing STATUS〈tw-hold 上游交付〉）
