# 上游依賴登錄（G5）

tw-hold 從 tw-swing 借來的東西。**上游改動不會自動同步**——這份表是唯一的
帳本。`check_upstream_drift.py`（待寫）比對 hash，只提醒、不自動拉。

## 複製進來的參考碼（會漂移）

| tw-hold 檔 | 來源（tw-swing） | 複製自 commit | 日期 | 漂移後果 |
| :--- | :--- | :--- | :--- | :--- |
| `reference/loader.py` | `src/twswing/value/loader.py` | — | 2026-09-07 | **搬移非複製**——tw-swing 端已刪除，不會漂移 |
| `factors/factors.py` | `src/twswing/value/factors.py` | — | 2026-09-07 | 同上（搬移） |
| `screener/screen.py` | `src/twswing/value/screen.py` | — | 2026-09-07 | 同上（搬移） |
| `reference/regime.py` | `src/twswing/data/regime.py` | `c310b60` | 2026-09-07 | 無害（只是市況顯示旗標） |
| `reference/finmind_client.py` | `src/twswing/data/finmind.py` | `c310b60` | 2026-09-07 | 小（FinMind API 變更才有感） |

**待複製**（延到 M1 / M4）：
- `src/twswing/indicators/{core,ma_rules,pivots,trendlines}.py` → `reference/indicators/`（M1 長波段 screener）
- `me/.../data/price_adjuster.py`、`me/.../data/fetcher.py` → `reference/`（M4 個股查詢）

## 上游資料 bundle（每日拉，不進版控）

| 項目 | 來源 | 拉法 |
| :--- | :--- | :--- |
| bundle Release | tw-swing 私有 repo，移動 tag `data-latest` | `fetch_bundle.py`（PAT 走 `st.secrets`） |
| PAT | fine-grained、只給 `tongxiaooppo-boop/tw-swing` 的 `contents: read` | ✅ 2026-09-08 建（名稱 `tw-hold-bundle-read`） |
| PAT 放哪 | tw-hold `.env` `TWSWING_BUNDLE_PAT` + tw-hold Actions secret 同名 + Streamlit Cloud secret | ✅ 三處到位 |
| **PAT 到期日** | **~2026-12-07**（建立日 +90 天） | 🔴 **到期前換**：GitHub 撤銷→產新→更新上述三處。約 2026-11-30 開始提醒 |

bundle 內容與 schema：見 `PRD.md` §3、`PLAN.md` §M0.1a/M0.1b。
`_meta.json` 帶 `schema_version` + 每檔欄位清單，`fetch_bundle.py` 的 G1 對不上就大聲失敗。

## 漂移偵測（G5）

`check_upstream_drift.py` 比對 tw-swing 那份**現在**的 SHA-256 vs 複製當時的 baseline
（記在該檔的 `BASELINE` dict）。上游動過 → 印 `[DRIFT]`、永遠回 0（提醒不是門檻）。
手動 merge 上游改動後：更新 `check_upstream_drift.py` 的 `BASELINE` + 上表的 commit 欄。

目前 baseline @ tw-swing `c310b60`（regime.py / finmind.py 自 M0.3 起未動）。
