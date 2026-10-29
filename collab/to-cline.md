# 任務書：A8 交易所 PER 修正重做（2026-10-29，Opus 定框架）

> 背景一句話：個股遇到「配股」後，交易所每日本益比（PER）用的 EPS 是**最近四季「當初公布值」直接相加**（舊季不會改成新股數），所以配股後約一年內 PER 被低估、逐季混合。我們的季 EPS 已經用 `adjust_eps` 換成最新股數；要把交易所 PER 修回同一把尺。
> 舊做法（偵測換基準日、整段 ×m）已驗證是錯的，**整段刪掉重寫**。股價淨值比（pbr）、殖利率（dividend_yield）**這次不修**，原樣保留。

做完要：`pytest` 全綠、驗證腳本達標、清單重建並產出比對表、本機 `git commit`（不 push）。

## 要讀的檔案（只准讀這些；.clinerules 的「不准讀 research/」這次對下列兩個檔案例外）

| 檔案 | 範圍 |
|---|---|
| `reference/corporate_actions.py` | 第 95–130 行（`_events` 等）、第 240–376 行（`report_deadline`、`_observed_boundary`、`adjust_eps`）、第 398–503 行（舊的交易所修正，要刪掉重寫） |
| `tests/test_corporate_actions.py` | 第 1–20 行（import 與 fixture）、第 215–300 行（舊的 `test_fix_exchange_ratios_*`，要換掉） |
| `app/bundle_data.py` | 第 150–185 行（`per_history`、`financials`） |
| `build_factors.py` | 第 108–125 行（`_read_bundle_per_history`）、第 305–325 行（`screen_all` 開頭的載入） |
| `research/share_events_verify/verify_per.py` | 全檔（約 80 行，第 30 行要改呼叫方式） |
| `research/share_events_verify/compare.py` | 不用讀，照下面指令執行即可 |

不准讀其他檔案。不准讀 `reference/corporate_actions_resolved.json`（30 萬字元的資料檔）。

## 第 1 步：`adjust_eps` 加兩個篩選參數（只加參數，不准改判斷邏輯）

```python
def _events(ticker: str, types: tuple[str, ...] | None = None,
            upto: pd.Timestamp | None = None) -> list[tuple[pd.Timestamp, float]]:
    # types 給了 → 只留 e.get("type") in types 的事件（沒有 type 的舊格式事件一律排除）
    # upto 給了 → 只留事件日 <= upto 的事件
    # 其他行為完全不變（m=None、m≈1 的照舊排除）

def adjust_eps(q, col="eps", ticker_col="ticker", period_col="period_end",
               types: tuple[str, ...] | None = None,
               upto: pd.Timestamp | None = None) -> pd.DataFrame:
    # 只把 types／upto 傳給 _events；其他一行都不准動
```
`adjust_eps` 裡建 `types = {...}` 那個區域變數名稱會跟新參數撞名，改叫 `ev_types`。

## 第 2 步：重寫 `fix_exchange_ratios`

刪掉：舊的 `fix_exchange_ratios`、`_next_quarter_end`、`_exchange_switch`、`_DETECT_MIN_M`、`_DETECT_DAYS`。保留 `EXCHANGE_LAG_TYPES`、`report_deadline`。新簽名與行為（docstring 照抄、可補充）：

```python
def fix_exchange_ratios(per: pd.DataFrame, quarterly: pd.DataFrame | None = None,
                        raw_close: pd.DataFrame | None = None) -> pd.DataFrame:
    """交易所每日 PER 修回最新股本基準（只修 `per` 欄；pbr、dividend_yield 原樣）。

    實證（2026-10-29）：交易所 PER 的 EPS＝最近四季「當初公布值」加總，舊季不重編；
    配股（ex_rights／ex_both）後要四季才滾完。面額變更／分割交易所已重編，不修。
    修法：PER × 原始四季加總 ÷ 調整後四季加總（調整只計配股類、且事件日 ≤ 當天的事件）。

    per：[ticker, date, per, ...]；quarterly：[ticker, period_end, eps, ni_parent?, net_income?]
    （原始、未調整的季 EPS）；raw_close：[ticker, date, close]（未還原收盤）。
    quarterly 沒給或空 → 原樣返回。非破壞性。
    """
```
演算法（每一檔「有配股類事件、m>1」的股票各做一次；其他股票不碰）：

1. `qt`＝該檔 quarterly 依 `period_end` 排序；`raw_eps = qt.eps`（數值化）；`deadline[i] = report_deadline(period_end[i])`。
2. 該檔配股類事件日期排序成 `E1 < E2 < …`。PER 的日期分段：`[E1, E2)`、`[E2, E3)`、…、`[Ek, ∞)`；**E1 之前的日期不修**。
3. 每一段以該段起點 `Ej` 為 `upto`：`adj_eps = adjust_eps(qt, types=EXCHANGE_LAG_TYPES, upto=Ej)["eps"]`。
4. 段內每個日期 d：
   - `n` ＝ `deadline < d` 的季數（用 `np.searchsorted(deadline, d, side="left")`，deadline 要已排序；季別排序後 deadline 本來就遞增）。
   - A 組＝第 `n-4`～`n-1` 季（共 4 季）；B 組＝第 `n-3`～`n` 季，**只有當 `n < 季數` 且 `period_end[n] < d`** 才有 B 組（那季已結束、可能提早公布了）。
   - 每組算 `raw4 = Σraw_eps`、`adj4 = Σadj_eps`；一組有效＝剛好 4 季、全部有限值、`raw4 > 0` 且 `adj4 > 0`。
   - 選組：有 B 組、且 `raw_close` 有該檔當天收盤 c、且當天 per > 0 → 取 `|ln((c/per)/raw4)|` 較小的那組；否則用 A 組。選到的組無效 → 這天不修。
   - `per_fixed = per × raw4 / adj4`。
5. 必須向量化到「每檔、每段」層級（用 numpy 陣列，不准對每一天跑 python 迴圈）。效能要求：全市場 `build_factors._read_bundle_per_history(...)` ≤ 30 秒（約 480 萬列）。

## 第 3 步：接呼叫端

- `app/bundle_data.py::per_history(code)`：維持「該檔有配股類事件才修」的判斷；改成
  `fix_exchange_ratios(d, quarterly=fin, raw_close=<原本那個 prices_raw_close 讀法>)`，`fin = financials(code)`；`fin` 空的話就不修。
- `build_factors.py`：`_read_bundle_per_history(q=None, raw_close=None)`，把 `q`、`raw_close` 傳進 `fix_exchange_ratios(d, quarterly=q, raw_close=raw_close)`；`q` 是 None 時不修。`screen_all` 裡改成 `per_hist = _read_bundle_per_history(q, raw_close_hist)`（`q`、`raw_close_hist` 在第 309、317 行已載入）。**用 `grep -n "_read_bundle_per_history" -r --include=*.py .` 確認沒有其他呼叫端**；有的話停下回報。
- 更新 `app/bundle_data.py::per_history` 的 docstring 和 `reference/corporate_actions.py` 檔頭說明裡提到「PBR／殖利率會修」的句子：改成「只修 PER；PBR、殖利率定義未驗證，暫不修」。

## 第 4 步：測試

刪掉 `tests/test_corporate_actions.py` 裡全部 5 個 `test_fix_exchange_ratios_*`，換成下面這些（預期值已手算，**不准拿程式輸出回填**）。共用資料：

```python
# 代號 9989，2026-09-02 配股 m=2（monkeypatch.setitem(ca.SPLITS, "9989", [{"date":"2026-09-02","type":"ex_rights","m":2.0,"pf":None}])）
# quarterly：period_end / eps / ni_parent
#   2025-09-30 4 400；2025-12-31 4 400；2026-03-31 4 400；2026-06-30 4 400；
#   2026-09-30 2 400；2026-12-31 2 400；2027-03-31 2 400；2027-06-30 2 400
# → adjust_eps 後：2026-06-30 以前各 2；2026-09-30 以後各 2（2609 季隱含股數 200 vs 前季 100，分界在 2609）
```
1. `test_fix_per_配股後逐季混合`：per 每天 10（日期 2026-09-01、2026-10-01、2026-11-20、2027-09-01），不給 raw_close。預期：09-01 → 10（事件前不修）；10-01 → 20（A 組 2509～2606：raw 16、adj 8）；11-20 → 17.5（2512～2609：raw 14、adj 8）；2027-09-01 → 10（2609～2706：raw 8、adj 8）。
2. `test_fix_per_提早公布挑B組`：日期 2026-11-05（Q3 季末已過、期限 11/14 未到），per＝10，raw_close 當天 close＝140 → c/per＝14＝B 組 raw4 → 預期 17.5；同一天不給 raw_close → 20。
3. `test_fix_per_面額變更不修`：只有 par_change m=10 的代號，per 原樣。
4. `test_fix_per_pbr殖利率不動`：同測試 1 的資料加 `pbr`、`dividend_yield` 欄，這兩欄完全不變。
5. `test_fix_per_沒給quarterly原樣`：`fix_exchange_ratios(per)` 等於輸入。
6. `test_adjust_eps_types篩選`：同一代號有 `par_change m=10`（2026-01-05）和 `ex_rights m=2`（2026-09-02），季別 2025-06-30（eps 20、ni_parent 無）、2026-12-31（eps 1）；`adjust_eps(q, types=EXCHANGE_LAG_TYPES)` → 2025-06-30 變 10（只 ÷2）、2026-12-31 不變。
7. `test_adjust_eps_upto篩選`：同上資料、不給 types、`upto=2026-06-30` → 2025-06-30 變 2（只 ÷10）。

## 第 5 步：驗證與比對（照指令跑，把輸出存檔）

```bash
export PYTHONIOENCODING=utf-8
python -m pytest -q -p no:cacheprovider            # 要全綠，記下 passed 數
```
改 `research/share_events_verify/verify_per.py` 第 30 行為：
`fixed = ca.fix_exchange_ratios(per_t, quarterly=inc[inc.ticker.isin(tks)].assign(ni_parent=lambda x: x.equity_parent), raw_close=raw[raw.ticker.isin(tks)])`
（income.parquet 的 equity_parent 就是歸母淨利，所以這裡可以直接 assign。）然後：
```bash
python research/share_events_verify/verify_per.py > research/share_events_verify/verify_per_out.txt
```
**達標條件**：輸出的「修正後」裡 `≈m 錯` ≤ 取樣總數的 5%；「原本對、被改錯的事件」≤ 5 件。沒達標 → **不准自己改演算法**，停下回報。

清單重建（約 3 分鐘＋5 分鐘；**不准跑 fetch_bundle.py 或任何下載**，本機資料必須跟 before/ 同一份）：
```bash
time python build_lists.py > research/share_events_verify/build_lists.log 2>&1
python build_revenue_watch.py > research/share_events_verify/build_rw.log 2>&1
mkdir -p research/share_events_verify/after
cp data/derived/value_list.json data/derived/deposit_list.json data/derived/revenue_watch.json research/share_events_verify/after/
python research/share_events_verify/compare.py > research/share_events_verify/compare_out.txt 2>&1
git checkout -- data/derived/
```
build_lists 要 < 4 分鐘（記下 real 時間）。

## 第 6 步：commit（不 push）

只 add 這些：`reference/corporate_actions.py`、`app/bundle_data.py`、`build_factors.py`、`tests/test_corporate_actions.py`。research/ 底下的檔案**不要 add**。commit 訊息：
```
股數事件：交易所 PER 改用「原始四季÷調整後四季」修正（PBR、殖利率暫不修）

Co-Authored-By: Cline (DeepSeek V4 Pro) <noreply@cline.bot>
```

## 不准做

- 改 `adjust_eps` 的判斷邏輯、`_observed_boundary`、`adjust_dividends`、`adjust_prices`、`scripts/resolve_splits.py`、`reference/corporate_actions_resolved.json`、`.github/`、其他測試檔。
- 網路搜尋、網頁抓取、瀏覽器、任何下載；`git push`、`gh`。
- 在 `D:\g\claude\tw-hold` 以外寫任何檔案；暫存檔放專案內、結束前刪掉。
- 不確定就停下，寫進 `collab/from-cline.md`「需要 Opus 決定」。

## 回報（寫進 `collab/from-cline.md`，精簡、不貼程式碼）

1. commit hash；2. pytest passed 數；3. `verify_per_out.txt` 的「修正前／修正後」兩行原文＋「原本對、被改錯」件數；4. build_lists real 時間；5. `compare_out.txt` 前 40 行原文；6. 有沒有偏離任務書、需要 Opus 決定的事。
