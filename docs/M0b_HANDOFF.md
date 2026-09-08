# M0b 交接 — 給下一棒

> **自足執行指令。你在全新對話、沒有上下文。** 讀完這份就能動工。
> 環境：Windows，`d:\g\claude\` 底下有 `tw-swing\`、`tw-hold\`、`books\`。
> ⚠️ **bash 工具的 cwd 是 `d:\g\claude`**，跑腳本要 `cd /d/g/claude/tw-hold` 或 `tw-swing`。
> ⚠️ 本機 console 是 cp950——**print 不要用 emoji**（`⚠️` 等會 UnicodeEncodeError），用 `[warn]` `[ok]`。
>
> **建立**：2026-09-08 ｜ **前一棒做完**：M0.3/M0.4/M0.2/M0.5 + U2/U3/U1a + **M0a 部分上線**
> ｜ **這一棒**：M0.1b（U1b 日更 bundle）→ M0b 驗收 → 之後 M1/M2

---

## 0. 一分鐘現況

**M0a（部分上線）已達成。** tw-hold 跑在
**https://tw-hold-jchm8ooiwp7ewqisfzmpoo.streamlit.app/**（Streamlit Community Cloud，
`tongxiaooppo-boop/tw-hold` main 分支，main file `app/streamlit_app.py`）。
四分頁（價值/定存/長波段/個股查詢）都渲染正常，價值 30 檔、定存 30 檔、長波段空
（M1 未做）、個股查詢是 M4 placeholder。

**資料鏈**：
```
tw-swing fundamentals.yml (U1a)  →  私有 Release tag `data-latest`（income/balance/
  cashflow/dividend/per.parquet + _meta.json）
     ↓  fetch_bundle.py（PAT，G1 schema/sha256/欄位 assert、G3 日期 warn）
tw-hold  data/upstream/  →  build_factors.screen_all()  →  build_lists.py
     →  data/derived/{value,deposit,swing}_list.json  →  Streamlit app 只讀這裡
```

**目前是 U1a-only（M0a）**：日線類欄位（現價、季線、20 週前低、波動度、市值前 500
過濾）全 None／未套用。清單只按財報排序。**補齊這些 = M0.1b + M0b，就是這一棒。**

**tw-swing G-5**：前一棒發現 `daily.yml` 自 9/5 commit `48aa0ac` 起連續紅
（`test_serve_hub.py` 缺 gitignored 的 `fields.json`），已修（`55248c6`）並驗證綠。
**開工前仍先 `cd /d/g/claude/tw-swing && python scripts/check_daily.py` 確認沒斷。**

---

## 1. 這一棒做什麼

### M0.1b — `publish_bundle.yml`（U1b 日更半邊）· **草稿已寫、未跑過 CI**

檔案已在 `tw-swing/.github/workflows/publish_bundle.yml` + `tw-swing/scripts/build_u1b_bundle.py`
（前一棒 commit `782d916`）。**還沒實際在 CI 跑過一次**，這一棒要跑通它。

它做的事（cron 平日 UTC 06:00 + workflow_dispatch）：
1. `actions/cache` 220MB `data_pack.zip`（key `u1b-pack-*`）
2. `python scripts/update_data.py --skip-watchlist data/cache/pack/data_pack.zip`
   → 抓好 `data/store/`（還原日線）+ 籌碼
3. `python scripts/build_u1b_bundle.py --lookback-days 1200`
   → `data/bundle_out/`：`prices_adj` / `prices_raw_close` / `revenue` / `index_0050` / `chips`
4. `python scripts/build_universe.py` → `data/fundamentals/universe.parquet`（市值前500 ∪ 成交值前500）
5. `make_bundle_meta.py --pipeline u1b <那些檔>` → 合併進 `_meta.json`
6. `gh release upload data-latest <那些檔> --clobber`
7. commit `universe.parquet` 回 repo（`if: always`）
8. `notify-failure` job

**跑通它的步驟**：
```
cd /d/g/claude/tw-swing
git push  (若有本地 commit)
gh workflow run publish_bundle.yml --repo tongxiaooppo-boop/tw-swing
# 監看：gh run watch / gh run view <id> --log-failed
```
⚠️ **會失敗的地方（預期要 debug 1–2 輪，CI workflow 常態）**：
- `update_data.py` 在 Linux runner 的行為（`DEFAULT_PACK` 是 Windows 路徑，前一棒已
  改成明確傳 `data/cache/pack/data_pack.zip`，但沒驗過）
- `build_u1b_bundle.py` 的欄位假設（`inst.parquet` 的欄名、`data/revenue/` 快照格式）
- `gh release upload --clobber` 對 U1a 已有的資產不能誤刪（`make_bundle_meta` 合併邏輯要對）
- `actions/cache` 第一次一定 miss、要下載完整 220MB（~2–3 分）

### M0b 驗收

跑通 M0.1b 後：
```
cd /d/g/claude/tw-hold
python fetch_bundle.py          # 這次應該 u1b_available=True
python build_lists.py
```
- `data/derived/*_list.json` 的 `_meta.universe_filtered` 應為 `True`
- 價值/定存清單應有現價、`norm_pe`/`fcf_yield` 有值、`ann_vol` 有值
- 清單縮到「市值前 500 內」
- Streamlit app（雲端會自動 redeploy，或本地 `streamlit run app/streamlit_app.py`）
  日線類欄位不再全 None

⚠️ **Streamlit 雲端只會在 `data/derived/*.json` 有新 commit 時更新**——所以
`rebuild.yml`（tw-hold）要接上，或先手動 commit 一版。`rebuild.yml` 目前是
placeholder（`.github/workflows/rebuild.yml`，`repository_dispatch: bundle-published`
+ `workflow_dispatch`），M0.5 的 step 還是 `echo TODO`——**這一棒把它接成真的**：
`python fetch_bundle.py && python build_lists.py && git commit data/derived/ && git push`。
需要 tw-hold Actions secret `TWSWING_BUNDLE_PAT`（**已設**）。

---

## 2. 前一棒完成的東西（都 commit + push 了，別重做）

### tw-swing（`master` @ `ec9810e`；相關 commit `782d916`→`55248c6`）
| 檔 | 內容 |
| :-- | :-- |
| `data/fundamentals/{income,balance,cashflow,dividend}.parquet` | 補抓成交值前 1000（~1000 檔，原 500）。402=0 全程乾淨 |
| `data/fundamentals/universe.parquet` | **U3 新產**（1968 列，宇宙 611 檔）。🔴 金控股用 `PBR×equity` 退回算市值（FinMind balance 對金融業報 `OrdinaryShare` 不是 `CapitalStock`）——14 檔金控全進 universe |
| `data/fundamentals/per.parquet` | U2（4.7M 列、19.8MB、2015→2026、1968 檔）。整併自 `data/finmind/per/` |
| `scripts/build_universe.py` | U3。market_cap 主口徑 `close×capital_stock/10`、退回 `PBR×equity` |
| `scripts/build_per_parquet.py` | U2 整併（不抓，`data/finmind/per/` 已全） |
| `scripts/make_bundle_meta.py` | 產 `_meta.json`（schema_version=1 + 每檔 columns/sha256/max_date + trading_date） |
| `scripts/build_u1b_bundle.py` | U1b 打包（**未在 CI 驗過**） |
| `scripts/fetch_fundamentals.py` | `_top_by_turnover` 改優先讀 `universe.parquet`（CI 沒 `data/store/`）；fetch step 加 `continue-on-error` |
| `.github/workflows/fundamentals.yml` | +U1a publish step（✅ CI 跑綠、Release 已發） |
| `.github/workflows/publish_bundle.yml` | **U1b，新檔，未跑過** |
| `tests/test_serve_hub.py` | fixture：缺 `fields.json` 就地生（修 G-5） |

### tw-hold（`main` @ `94b6174`）
| 檔 | 內容 |
| :-- | :-- |
| `factors/` `screener/` `reference/loader.py` | M0.3 從 tw-swing 搬入 |
| `reference/{regime,finmind_client}.py` + `UPSTREAM.md` | M0.4 複製（baseline `c310b60`） |
| `fetch_bundle.py` | **已實作**：GitHub API 抓 Release 資產、G1/G3、只有 U1a 也收工 |
| `build_factors.py` | `screen_all()`（`build_lists` 共用）；讀 bundle `universe.parquet` |
| `build_lists.py` | → `data/derived/*_list.json`；新進/移除讀上一期 JSON |
| `screener/screen.py` | 無股價時 `value_score` 用品質排序；**加「財報不完整（缺資產負債表）」硬門檻** |
| `check_upstream_drift.py` | G5（比 tw-swing 來源檔 SHA-256 vs baseline） |
| `app/streamlit_app.py` | 四分頁骨架，只讀 `data/derived/*.json` |
| `.github/workflows/{rebuild,heartbeat}.yml` | 骨架（rebuild 的 step 還是 TODO） |
| `docs/PLAN.md` | M1 補了「主動選股候選池」里程碑（v3.1）；M0 各項打勾 |
| `.env` | `TWSWING_BUNDLE_PAT`（fine-grained、`tw-swing` contents:read、90 天）+ `FINMIND_TOKEN`。**gitignored** |

---

## 3. 🔴 已知問題（不是這一棒必須解，但要知道）

| # | 問題 | 影響 | 歸屬 |
| :-- | :-- | :-- | :-- |
| 1 | **金控股漏出定存清單**：FinMind income statement 對金融業的 `EPS`/`net_income` 欄位是 NaN（不同 XBRL type）→ 被「eps 近4季非全正」刷掉。universe 有它們了，但 screen 過不了 | 定存清單系統性缺金控/金融——**正是實驗 B 說壞掉的那批** | §7 定存線 / 實驗 B 重跑。要在 `fetch_fundamentals.py` 的 `INCOME_FIELDS` 加金融業對映（要重抓金融股 income） |
| 2 | **`per.parquet` 不會自動更新**：`build_per_parquet.py` 讀 gitignore 的 `data/finmind/per/`（CI 沒有）。`fundamentals.yml` 用 repo 內 committed 那份。目前 max_date 2026-08-28（G3 會 warn） | 估值分位帶資料會慢慢舊 | 之後：`publish_bundle.yml` 順便用 TWSE `BWIBBU_ALL` 每日整批刷 PER/PBR/殖利率 |
| 3 | **清單欄名是英文**（`value_score` `f_score` `norm_pe`…） | UI 不友善 | M3 打磨 |
| 4 | **universe 外 11 檔小型股缺 balance**（1103 等）：不在抓取範圍。screen 的「財報不完整」門檻擋掉，無害 | 無（門檻處理了） | 不用管 |
| 5 | **`div_years` 全部 = 12**：股利資料從 2015 起，連續年數上限就是 ~12 | 定存排序時 div_years 分項飽和 | 小；要更長要另外補抓更早股利 |
| 6 | **PRD §8/§9〈已定〉區塊過時**（寫於 opus 審核前，講 `tw-data` 公開 repo / tw-hold 私有）。現行以 §3.1.1 / §10.1 / 本檔為準——README 已標註 | 讀 PRD 會混淆 | 有空校準 PRD |

---

## 4. 紅線（仍然有效）

- 🔴 **不改 tw-swing `daily.yml`**（G-5 的 60 交易日時鐘上）
- 🔴 **不改 tw-swing `rules.yaml` / `portfolios` / pipeline / 回測**
- U1b 是**新開的 `publish_bundle.yml`**，不碰 `daily.yml`
- FinMind：token 600/hr、rate ≤ 450、**不要 `Throttle.seed()` 到接近上限**（會死等 1 小時）、避開週六 `fundamentals.yml` 排程（UTC 六 02:00）
- 定存 5% 殖利率硬底線不能自己放水到 4%——候選太少要回報使用者
- tw-hold 是**公開 repo**：`positions.json` / token / `.env` 絕不進版控（`.gitignore` 已擋）

---

## 5. 建議順序

0. `cd /d/g/claude/tw-swing && python scripts/check_daily.py`（G-5 沒斷再動）
1. **跑通 `publish_bundle.yml`**（`gh workflow run` → 看 log → debug → 重跑，1–2 輪）
2. Release 有 U1b 資產後：`cd /d/g/claude/tw-hold && python fetch_bundle.py`
   確認 `u1b_available=True` → `python build_lists.py` 確認 `universe_filtered=True`
3. **接 `rebuild.yml`**（把 TODO step 換成真的 `fetch_bundle && build_lists && commit && push`）
4. 手動跑一次 `rebuild.yml` → Streamlit 雲端 redeploy → 截圖確認日線類欄位有值 = **M0b 驗收**
5. 回報使用者。之後：M1 候選池（`docs/PLAN.md` §M1，前置就是 M0b）或 M2 估值/verdict，
   以及 §7 定存線 + 實驗 B 重跑（問題 #1）

### 入口點
| 要做 | 讀 |
| :-- | :-- |
| M0 全貌 / M1 里程碑 | `tw-hold/docs/PLAN.md`（§M0.1b、§M0.5、§M1、§M2） |
| 前一棒 M0 的脈絡 | `tw-hold/docs/M0_HANDOFF.md`（這份的前身） |
| 為什麼這樣設計 | `tw-hold/PRD.md`（§3 bundle、§5 候選池、§6 價值、§7 定存、§10 失敗模式） |
| 進度細節 | 記憶 `tw-hold-m0-progress` |
| tw-swing 現況 | `tw-swing/docs/STATUS.md`〈一分鐘接手〉、〈tw-hold 上游交付〉 |
| 四個回測實驗 | `tw-hold/docs/BACKTEST_HANDOFF.md` + `docs/reports/*_20260907.md` |

⚠️ **開工前**：`git status` 兩個 repo 都應乾淨（前一棒全 commit + push 了）。
