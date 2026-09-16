# 審核回覆：0050 卡片 fallback + 開盤前新鮮度守門（對 `REVIEW_REQUEST_2026-09-16.md`）

審核範圍：commit `6a5e0e7` + `ec13aa2` 的全部改動，外加受影響的既有部件
（`fetch_bundle.py` G1、`app/bundle_data.py`、`reference/index_proxy.py`、
`reference/market_status.py`、`scripts/fetch_index_proxy.py`、兩份 workflow）。
不是只看 diff——每個懷疑都拿本機真實資料回算過，下面標 **實測** 的都有數字。

**先講結論**：這輪改動的方向對，`promote_index_0050.py` 的「寧可舊也不要錯」是正確
取捨。但驗證的**軸選錯了一半**——三道檢查全部只看「最後一筆」，防得住「資料倒退」
跟「最後一筆爆掉」，防不住「整份檔案縮水」，而後者剛好是唯一會讓畫面靜默壞掉、
且 `freshness_check.py` 也抓不到的情境。另外抓到一個簽呈沒提到的既存問題：
**`index_006201.parquet` 裡現在就有兩筆 close = 0 的壞資料。**

---

## 0. 先回答「有沒有你沒想到的」（§6-4）

### 0-1 ⚠️ 006201 現在就有壞資料（實測）

```
1371  2016-08-23  11.45
1372  2016-08-24   0.00   ← 收盤價 0
1373  2016-08-25  11.45
1520  2017-04-07  12.03
1521  2017-04-10   0.00   ← 收盤價 0
1522  2017-04-11  11.90
```

`data/reference/index_006201.parquet`（3825 筆）裡兩筆 `close == 0`，日報酬序列因此
出現 `inf` 與 `-100%`。這不是理論風險，是 FinMind 已經吐給我們、已經 commit 進 repo
的資料。今天**畫面沒壞**，只因為 `market_status.market_card()` 只吃尾端 200 筆，這兩筆
在 2016/2017。但同一個 FinMind 行為若發生在最近一天，`latest_change()` 會直接算出
`chg_pct = inf`，卡片渲染出荒謬數字——這正是使用者說「不可原諒」的那一類。

→ **§4-3 的答案：不是你過慮，是真疏漏，而且已經有事證。** 006201 該補等同驗證。

### 0-2 ⚠️ 截斷（row count 縮水）三道檢查全部放行

`validate_and_promote()` 只比較 `new` 的最後一筆與 `old` 的最後一筆。假設上游某天寫出
一份只有最近 30 列的 `index_0050.parquet`（欄位對、sha256 對、最後日期是今天、
最後一筆漲跌 0.3%）：

- G1（`fetch_bundle.py` 的 sha256 + columns）：**過**（檔案本身沒壞，是內容少了）
- 三道驗證：**全過**
- 結果：2848 列被 30 列覆寫，commit 進 repo
- `market_status.ma_verdict(close, 200)` → `len(s) < 200` → 回 `None` → 卡片 MA200 欄
  **靜默顯示空的**，不報錯、不告警
- 隔天 `freshness_check.py`：**抓不到**（它只看最後一筆日期，而最後一筆是新的）

這是整輪改動裡唯一「壞了沒人知道」的路徑。簽呈 §4-1 想到了「中段被竄改」，但漏了
更粗暴也更可能發生的「整份縮水」。

### 0-3 `prev_close and ...` 讓漲跌幅檢查在 0 收盤時自廢

```python
if prev_close and abs(last_close / prev_close - 1.0) > MAX_DAY_MOVE:
```

`prev_close == 0`（正是 0-1 那種壞資料）→ 條件短路 → **整道檢查被跳過、資料照樣覆寫**。
本意是防 ZeroDivisionError，副作用是「資料壞到 0」這種最嚴重的情況反而豁免。
另外全檔都沒有 `close <= 0` / `NaN` / 重複日期的檢查。

### 0-4 `load_0050()` 沒套 `adjust_per_share`，跟 fallback 路徑口徑不一致

`_bundle_close("0050")` → `bundle_data.prices()` → 會呼叫
`reference.corporate_actions.adjust_per_share()` 還原未調整的分割／面額變更。
`index_proxy.load_0050()` 是純讀檔，**不套**。兩條路徑理論上可能吐出不同基準的價格。

**實測目前沒事**：798 個重疊交易日，`index_0050` 與 `bundle prices_adj` 的收盤
最大相對差 = **0.0**（完全相同）。原因是 0050 不在 `SPLITS` 表裡（上游已還原）。
所以這是一顆「現在不響、將來 0050 再分割一次且上游沒還原時才響」的雷。

### 0-5 總經導航頁沒有接 `_bundle_err`（§4-7 的洞是可以補的）

`_ensure_bundle()` 失敗時把錯誤寫進 `st.session_state["_bundle_err"]`
（`streamlit_app.py:1280`），另外兩頁有把它接出來顯示（`:1381`、`:1589`），
**總經導航的 `tw_missing` 訊息沒有**。所以 §4-7 說的「診斷細節消失」不是這個
設計的必然代價，是漏接——照 `:1381` 那三行的既有寫法接上就還原了。

---

## 1. §4 八個挑戰點逐一裁決

| # | 我的裁決 | 理由 / 建議做法 |
| :- | :--- | :--- |
| **1** 驗證門檻站不站得住 | **一半是真隱患**（不是門檻數字，是檢查軸） | 15% 這個數字**反而比你以為的有根據**：實測 2015-01 起 2847 筆日報酬，最大絕對值 = **恰好 10.0%**（台股 ±10% 漲跌停，ETF 同受限），99.9 分位 9.26%。合法值進不了 10–15% 這個帶。可以收到 **12%** 更緊，但邊際收益小。真正該補的是另外三項：**① 列數不得大幅縮水**（`len(new) >= len(old) - 5`）、**② 重疊區一致性**（新舊共同日期取最後 60 天，收盤必須完全相同，否則視為上游回填／改寫，拒絕並告警）、**③ 全檔 sanity**（無 `NaN`、無 `close <= 0`、無重複日期、總列數 ≥ 250 才夠餵 MA200）。另外 0-3 的短路要改成明確拒絕。 |
| **2** 「保留舊檔」變慢性問題 | **真隱患，但你抓錯了監控點** | 連續 reject 時 `data/reference/index_0050.parquet` 的**最後日期會凍住** → `freshness_check.py` 的「上市代理 0050」項目隔天開盤前就會 stale 告警，機制已經覆蓋。缺的是兩件小事：**(a)** `heartbeat.yml` 的診斷文案只寫了 006201 分支，沒寫「只有 0050 stale → 看 rebuild.yml 的 promote 步驟 log／驗證被拒」；**(b)** app 端你提的那行 `st.caption` 值得加——但寫「0050 目前走備援路徑」太內部，寫成「0050 資料來源暫時改走備援，日期可能落後」比較是使用者語言。 |
| **3** 006201 沒有同等驗證 | **真疏漏，優先度最高**（見 0-1，有實據） | 不對稱處理沒有正當理由，而且 006201 的風險**高於** 0050：0050 走 bundle，上游有 G1 sha256 + columns 把關；006201 是直接吃 FinMind 回來的 JSON，`fetch()` 只檢查「不是空的」就整份覆寫。建議把驗證邏輯抽成共用函式（見 §2），006201 套同一套，並額外加「歷史列數不得減少」——它是全量重抓，縮水風險比 0050 更高。既有那兩筆 0 要另外決定是清掉還是插值（我建議直接 drop，反正 `market_card` 只看尾端）。 |
| **4** 徽章語意 | **確認失效，該改** | `_freshness_badge_html()` 的 docstring（`streamlit_app.py:2365`）現在明文寫「三清單／個股查詢／**總經導航 0050** 都吃這條」——這句在這次改動後是假的。文案跟註解都要改：徽章標籤改成「清單資料 YYYY-MM-DD」之類明確限定範圍的講法，別讓使用者站在總經導航頁把它當成這頁卡片的日期。 |
| **5** `cache_resource` 並發 | **過慮，Streamlit 已經處理**（實測原始碼） | 本機 streamlit 1.60.0，`runtime/caching/cache_utils.py:147` 有 `compute_value_lock(value_key)`，註解寫明「only one of those sessions computes the value, and the others block」，並用 double-checked locking。**不用自己加鎖。** 另外 `ensure_assets()` 的 `d.write_bytes()` 雖然不是原子寫，但它是先把整包 bytes 收完才寫，且下次進來靠 size 比對會自癒截斷檔——可接受。 |
| **6** 連假誤報 | **真限制，但別做行事曆** | 硬編台灣假日表要每年維護（會忘），接外部 API 是給一個純告警功能加一條新的外部依賴，划不來。建議改成**升級式告警**：stale 第 1 天只印 warning 不發 webhook，連續 ≥ 3 個排程日才發——連假天然會在假期結束後自己復原，真的斷線則會撐過 3 天。實作成本是存一個 stale 計數（可放 `data/derived/_heartbeat.json` 或直接看 GitHub Actions 前次結論）。若不想加狀態，退而求其次：告警訊息開頭加「若今天是連假期間，這是預期中的假警報」。 |
| **7** 診斷資訊變粗 | **取捨划算，但是漏接**（見 0-5） | 不擋頁的方向對。把 `_bundle_err` 接進 `tw_missing` 的 `st.info` 就兩全了，成本三行。 |
| **8** `scripts/` 被 app import | **可接受但該搬**，優先度低 | 不是潔癖問題：`scripts/` 定位是 CI 工具，將來有人在裡面某支加 module-level 的重 import，就會被拖進 app 冷啟路徑。建議把 `_expected_trading_date` / `_check_one` / `_meta_trading_date` 搬進 `reference/freshness.py`（app 本來就 import 這個目錄），`scripts/freshness_check.py` 退化成薄 CLI wrapper。順帶解決「app 依賴一個沒有 `__init__.py` 的 namespace package」這件本來就有點脆的事。 |

---

## 2. 建議的具體修法（照優先序）

1. **抽共用驗證模組** `reference/price_series_guard.py`：
   `validate(new_df, old_df) -> list[str]`（回拒絕原因，空 list = 過）。
   檢查項：欄位齊、非空、無 `NaN`／`close <= 0`／重複日期、列數 ≥ 250、
   `len(new) >= len(old) - 5`、最後日期不倒退、最後一筆漲跌 ≤ 12%、
   重疊區最後 60 天完全相同。`promote_index_0050.py` 與 `fetch_index_proxy.py` 共用。
2. **`fetch_index_proxy.py` 改成先寫暫存再驗證再覆寫**（現在是 `to_parquet` 直接蓋），
   驗證不過 exit 1，`rebuild.yml` 加一步告警（抄 0050 那步）。
3. **清掉 006201 現存的兩筆 0**（2016-08-24、2017-04-10）。
4. **`heartbeat.yml`**：診斷文案補 0050 分支；「OK：兩項都新鮮」→「三項」；
   檔頭註解補第三項。**`freshness_check.py`** docstring「檢查兩份」→ 三份。
5. **徽章文案 + docstring 修正**（§4-4）。
6. **總經導航接 `_bundle_err`**，並加 fallback 提示 caption（§4-2、§4-7）。
7. **共用邏輯搬進 `reference/`**（§4-8）。
8. 瑣事：`promote_index_0050.py` 的 `import sys` 未使用，刪掉。

---

## 3. 覆核過、確認沒問題的部分

- **全套 `pytest -q`：204 passed**（簽呈說只跑了受影響的檔案——補跑了，沒有間接波及）。
- `fetch_bundle.py` 的 G1 確實涵蓋 `index_0050.parquet`（`PIPELINE` 標 `u1b`，
  走 sha256 + columns 檢查），所以傳輸層損毀已經有保護，`promote` 那三道是**語意層**
  第二道防線——這個分工是對的，但也表示 `promote` 該把力氣花在 G1 抓不到的東西上
  （＝內容縮水／回填），而不是重複驗「檔案有沒有壞」。
- `_bundle_close("0050")` fallback 路徑**實測可用**：`bundle_data._read()` 會把
  `0050` 展開成 `0050.TW`／`0050.TWO` 比對（`bundle_data.py:77`），`prices_adj.parquet`
  裡是 `0050.TW`，取得 800 筆（約 3 年），足夠餵 MA200。
- `ttl=3600` 的語意跟 docstring 描述一致（`ensure_assets` 本身是 size 比對，
  TTL 只是讓比對會發生，不是每小時重抓 89MB）。
- `rebuild.yml` 的 `concurrency: rebuild` + `cancel-in-progress: false` 正確——
  promote 跟 commit 不會被並發的第二次 dispatch 打斷。
- `continue-on-error: true` + `if: steps.promote_0050.outcome == 'failure'` 的接法正確
  （`outcome` 才是原始結果，`conclusion` 會被 continue-on-error 洗成 success）。
- 新增的 6 個 promote 測試用 `monkeypatch.setattr(m, "SRC"/"DEST")` 換路徑，
  函式內確實是讀 module global，patch 有效。
- **上游沒附檔（`[SKIP]` 回 0）不告警**是刻意的，且有兜底：檔案日期凍住 →
  隔天開盤前 `freshness_check` 會抓到。偵測延遲最多一天，可接受。

---

## 3.5 修正紀錄（2026-09-16 同日完成，尚未 commit）

| 項目 | 做法 | 檔案 |
| :- | :--- | :--- |
| 共用守門 | 新增 `sanitize()` + `validate()`。**兩段式**：FinMind 每次全量重抓都會再吐一次同樣的 `close=0`，若設計成「看到就拒絕」006201 會永遠拒絕、資料凍死 → 先清再驗 | `reference/price_series_guard.py`（新） |
| 筆數縮水 | `len(new) < len(old) - 5` 或 `< 250` 筆 → 拒絕（舊版唯一放行、且畫面靜默壞掉的洞） | 同上 |
| 歷史回填 | 比**日報酬**不比價格：還原型序列每逢除息/分割會整段重訂基準，價格全變但日報酬只有事件日那一筆會變 → 容許 1 天，≥2 天判定竄改 | 同上 |
| 漲跌幅門檻 | 15% → **12%**（實測 0050 歷史最大單日 10.0%＝漲跌停）；並修掉 `prev_close and ...` 在 0 收盤時整道檢查被短路的洞 | 同上 |
| 006201 補驗證 | `main()` 改成 sanitize → validate → 沒過保留舊檔 exit 1 | `scripts/fetch_index_proxy.py` |
| 清掉既有壞資料 | 2016-08-24、2017-04-10 兩筆 `close=0` 已 drop（3825 → 3823 筆），清完最大日報酬 10.0% | `data/reference/index_006201.parquet` |
| 告警 | 兩支代理合併成一個告警步驟，任一沒更新都發；訊息區分「驗證擋下」vs「抓取失敗」 | `.github/workflows/rebuild.yml` |
| 診斷文案 | 補 0050 分支、補連假假警報說明、「兩項」→「三項」、檔頭補第三項 | `.github/workflows/heartbeat.yml` |
| 搬出 scripts/ | 判斷本體 → `reference/freshness.py`，CLI 退成薄包裝，app 不再 import `scripts/` | `reference/freshness.py`（新）、`scripts/freshness_check.py` |
| 徽章 | 文案「資料日期」→「**清單資料**」+ docstring 改寫（原本明文寫「總經導航 0050 都吃這條」已是假話） | `app/streamlit_app.py` |
| 備援留痕 | fallback 發生時印一行 caption；`tw_missing` 接回 `_bundle_err` 診斷細節 | `app/streamlit_app.py` |
| 測試 | 新增 `test_price_series_guard.py`（13）、`test_fetch_index_proxy.py`（3）；`test_promote_index_0050.py` 改寫（假資料補足筆數，加縮水案例）。**全套 221 passed** | `tests/` |

**沒做**（刻意）：§4-6 的連假升級式告警（要存 stale 計數，為一個告警功能加狀態不划算）
——改成在告警訊息裡明寫「若正值連假這是已知假警報」。農曆春節仍會每天誤報。

### 附帶：雲端 `AttributeError: load_0050` 不是程式 bug

Streamlit Cloud 的主腳本每次 rerun 都重新執行（＝新版），但 `sys.modules` 裡已經
import 過的 `reference.index_proxy` 沿用舊進程的舊物件（＝還沒有 `load_0050`）。
**Manage app → Reboot app** 即可。只要哪次部署是「在既有模組裡新增函式」就可能再遇到。

---

## 4. 沒有改變的裁決

- badge-only 不擋頁：維持（§5 的定案），上面找到的問題都不足以推翻它。
- 選股規則／因子／verdict：本輪完全沒碰，確認無誤。
