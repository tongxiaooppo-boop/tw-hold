# 【tw-swing＋tw-hold】股本扣預收股本（版本 2026-11-22 v1）

> 兩個 repo 都在主目錄直接改：`D:\g\claude\tw-swing`（master）、`D:\g\claude\tw-hold`（main）。
> 禁止：stash／reset／checkout／push／改 cron／改本文件沒列的檔案。只 `git add` 自己改的檔。
> 檔案一律 UTF-8 無 BOM，不用 PowerShell 寫檔。python 一律 `PYTHONIOENCODING=utf-8`。
> 暫存檔／一次性腳本只准放 `D:\g\claude\` 底下，結束前刪掉。不上網。
> 介面（函式名、簽名、欄名）照本文件，不准改；覺得有問題就停下回報（最多停 2 次）。小疑問自行採用並在回報註明。

## 背景（定案，不用再查）

XBRL `ifrs-full:IssuedCapital`（我們的 `capital_stock`）＝股本合計，**含預收股本**（現增已收款、新股未發，金額含溢價）。例 5483 2024Q3：普通股 58.62 億＋預收 89.63 億＝148.25 億 → 股數高估、每股淨值低估。
定案：`capital_stock` 原口徑不動；另存 `advance_capital`；tw-hold 算股數／市值時扣掉。缺值不當 0（缺就不扣）。待註銷股本不扣。近零錯值只看過去判斷。

## 要讀的檔案（只准讀這些）

tw-swing：`scripts/official_xbrl.py`（全檔 ~330 行）、`scripts/official_fin.py` 第 60–110、270–420、495–560、740–800 行、`scripts/fetch_fundamentals.py` 第 280–310 行、`tests/test_official_xbrl.py`、`tests/test_official_fin.py`、`tests/test_fetch_fundamentals.py`（找寫法樣板即可）
tw-hold：`reference/loader.py` 第 55–130 行、`reference/share_basis.py` 第 80–180 行、`screener/screen.py` 第 20–30、60–110、180–195 行、`screener/detect.py` 第 175–235 行、`build_factors.py` 第 295–310 行、`screener/val_card.py` 第 125–140、520–545 行、`app/val_view.py` 第 390–400 行、`tests/test_loader_live.py`、`tests/test_val2_share_basis.py`、`tests/test_val2_detect.py`（樣板）
資料：`D:\g\claude\p6_study\xbrl_facts\facts_<YYYYQn>.parquet`（54 季 2013Q1～2026Q2；欄 `filing, ticker, industry, report, fr, concept, start, end, unit, value`；`end`／`start` 是 int 如 20260630／0）

---

## 步驟 1：tw-swing 收 `advance_capital`

1. `scripts/official_xbrl.py`
   - 新增常數（放 `POINT_TAGS` 下面）：
     ```python
     #: 預收股本：各業別 prefix 不同，依序試。期末 AsOf。
     POINT_TAGS_MULTI = {
         "advance_capital": [f"tifrs-bsci-{i}:AdvanceReceiptsForShareCapital"
                             for i in ("ci", "basi", "bd", "fh", "ins", "mim")],
     }
     ```
   - `_VALUE_COLS` 在 `list(POINT_TAGS.keys())` 後加 `+ list(POINT_TAGS_MULTI.keys())`。
   - `parse_report`：POINT_TAGS 迴圈後 `for col, tags in POINT_TAGS_MULTI.items(): out[col] = _lookup(tags, point)`。
   - `read_comparatives` 的 point_only 判斷改成 `c in POINT_TAGS or c in POINT_TAGS_MULTI`。
2. `scripts/official_fin.py`
   - `POINT_COLS` 加 `"advance_capital"`（放最後）。
   - `_APPLY_FIELDS["balance"]` 加 `"advance_capital"`（放最後）。
   - TSD 匯入的 `cols`（約 302 行）：`fin` 沒這欄就補 NaN，`cols` 在 `capital_stock` 後加 `"advance_capital"`。
   - apply 迴圈（約 769 行）：讀 `ours` 後，若 `table == "balance"` 且 `ours` 沒有 `advance_capital` 欄 → `ours["advance_capital"] = np.nan`（加在最後一欄）。`apply_overlay` 本身不改。
   - 讀舊 `fin_official.parquet` 沒這欄時，任何地方都不能 KeyError（用 `reindex`／補 NaN）。
3. `scripts/fetch_fundamentals.py` `_upsert`：合併後，對「`old` 有、`new` 沒有」的欄位（例 `advance_capital`），同 key 的值從 `old` 帶回（FinMind 列覆蓋舊列時不准把別的來源的欄洗掉）。其餘行為不變。
4. 新檔 `scripts/backfill_advance_capital.py`
   ```python
   def load_facts(facts_dir: Path) -> pd.DataFrame:
       """讀 facts_*.parquet → [ticker, period_end, advance_capital]。
       只收：concept 結尾 ':AdvanceReceiptsForShareCapital'、ticker 符合 ^[1-9]\\d{3}$、
       start == 0、end == filing 季末（2026Q2 → 20260630）。同 ticker＋季多份依 report cr<ir<er 取一份。"""
   def fill_balance(balance: pd.DataFrame, adv: pd.DataFrame) -> tuple[pd.DataFrame, int]:
       """balance 沒有 advance_capital 欄就補 NaN；只填 NaN 的格、不覆蓋已有值、不新增列。回傳 (新表, 填入格數)。"""
   def load_zip(zip_path: Path, period: str) -> pd.DataFrame:
       """facts 沒有的新季（2026Q3）：official_xbrl.read_folder(zip_path, period) 取 [ticker, period_end, advance_capital]，dropna。"""
   def main() -> int:  # --facts-dir（預設 D:\g\claude\p6_study\xbrl_facts）、--zip（可省）、--zip-period、--dry-run
   ```
   facts 與 zip 同 key 時 zip 優先（較新）。正式跑用：`--zip "D:\g\xbrl_inbox\tifrs-2026Q3 1121.zip" --zip-period 2026Q3`（11/21 最新一包，zip 唯讀不准動）。
   印：facts 有值筆數、填入格數、`advance_capital > 0` 列數、2026Q2 `> 0` 檔數。寫回 `data/fundamentals/balance.parquet`（zstd，欄序照舊、新欄在最後）。
5. 測試（新增，名稱照抄）：
   - `tests/test_official_xbrl.py::test_parse_report_advance_capital_by_industry`：ci 與 bd prefix 都抓到期末值；沒這 tag → NaN。
   - `tests/test_official_fin.py::test_apply_adds_advance_capital_column`：ours 無此欄 → apply 後有欄且從官方填入。
   - `tests/test_fetch_fundamentals.py::test_upsert_keeps_columns_absent_from_new`：舊列 advance_capital=5、新列同 key 沒此欄 → 合併後仍 5；新 key 列為 NaN。
   - 新檔 `tests/test_backfill_advance_capital.py`：`test_load_facts_filters_and_priority`（cr 勝 ir；比較期 end 不收；start≠0 不收；非 4 碼代號不收）、`test_fill_balance_only_fills_nan`（已有值不動、不新增列、回傳格數對）。
6. 跑 `python scripts/backfill_advance_capital.py --dry-run` 確認數字合理，再正式跑一次寫檔。
7. commit（tw-swing）：程式＋測試一個 commit、`balance.parquet` 一個 commit。

## 步驟 2：tw-hold 用「淨股本」

1. `reference/loader.py` 新增並在 `merge_statements` 回傳前呼叫 `q["capital_net"] = capital_net(q)`：
   ```python
   NEAR_ZERO_RATIO = 0.10   # 本季 < 前 4 季中位數 × 此值 → 當缺值
   def capital_net(q: pd.DataFrame) -> pd.Series:
       """普通股股本口徑＝capital_stock − advance_capital。
       - advance_capital 欄不存在、NaN、< 0、或 ≥ capital_stock → 不扣（用 capital_stock 原值）。
       - 近零錯值：同 ticker 依 period_end 排序，前 4 季（不含本季、min_periods=4）的 net 中位數 × NEAR_ZERO_RATIO
         大於本季 net → 本季設 NaN。只看過去，不准用下一季。
       回傳與 q 同 index。capital_stock 欄不存在 → 全 NaN。"""
   ```
2. 下游改讀 `capital_net`（列用 `row.get("capital_net", row.get("capital_stock"))`；DataFrame 用 `d["capital_net"] if "capital_net" in d.columns else d.get("capital_stock", np.nan)`；**capital_net 是 NaN 時不准退回 capital_stock**）：
   - `reference/share_basis.py`：`exchange_outstanding_ratio` 內 `cap = row.get('capital_stock')`（約 102 行）、`common_shares` 傳給 `shares_today_basis` 的值（約 121 行）。`shares_today_basis` 簽名不改（參數名 capital_stock 照舊）。
   - `screener/screen.py`：約 99、102、191 行三處。
   - `screener/detect.py`：約 218 行；docstring（約 183 行）改成「股本股數 C＝淨股本（股本−預收股本）÷ 面額 − 特別股」。
   - `build_factors.py` 約 300–305 行退化估市值。
   - 如果 `capital_net` 在到達上述程式前被欄位白名單丟掉（例 `val_card.Q_COLS`），把 `capital_net` 加進白名單；改了哪些寫進回報。
   - **不改**：`factors/factors.py` 的 `f_noissue`、`screener/classify.py` 股本變動（預收股本也是真增資，照舊用 capital_stock）。
3. `app/val_view.py` 約 396 行「年度下的事件」說明，在「…也不標示。」後接：`原股東折價認購的現金增資，其中的紅利成分也沒有追溯（影響通常 1～6%）。`
4. 測試（新增，名稱照抄）：
   - `tests/test_loader_live.py`：`test_capital_net_subtracts_advance`（148.25e8 − 89.63e8 → 58.62e8）、`test_capital_net_missing_advance_keeps_capital`（無欄、NaN 各一）、`test_capital_net_bad_advance_ignored`（adv < 0、adv ≥ cap 都不扣）、`test_capital_net_near_zero_past_only`（序列 100,100,100,100,5,100 → 第 5 季 NaN、其餘原值；把第 6 季改成 1 或 1000，第 5 季結果不變；前 4 季不足 4 筆不判）。
   - `tests/test_val2_share_basis.py::test_common_shares_uses_capital_net`
   - `tests/test_val2_detect.py::test_share_mismatch_uses_capital_net`
   - `tests/test_screen*.py`（沿用既有檔，沒有就新建 `tests/test_screen_capital_net.py`）`::test_market_cap_fallback_uses_capital_net`（不給 market_cap 時用淨股本算）
5. commit（tw-hold）。

## PROOF_CMD（兩條都要過）

```
cd /d/g/claude/tw-swing && PYTHONIOENCODING=utf-8 python -m pytest -q -p no:cacheprovider 2>&1 | tail -3 && PYTHONIOENCODING=utf-8 python scripts/backfill_advance_capital.py --dry-run --zip "D:/g/xbrl_inbox/tifrs-2026Q3 1121.zip" --zip-period 2026Q3
cd /d/g/claude/tw-hold && PYTHONIOENCODING=utf-8 python -m pytest -q -p no:cacheprovider 2>&1 | tail -3
```
預期：兩邊 `0 failed`（tw-hold 約 1567＋新增數 passed）；backfill 乾跑（已正式寫過）填入格數＝0，`2026Q2 > 0 檔數` 在 90～100（調研數字 96；超出範圍停下回報，不要硬改）；另印 2026Q3 `> 0` 檔數。

## 回報（寫 `D:\g\claude\tw-hold\collab\from-sonnet-advance-capital.md`，欄位照抄，不貼程式碼）

- 完成項：
- commit（兩 repo，hash＋一行）：
- 測試數字（兩邊 passed／failed）：
- backfill 正式跑輸出（原文 4 行）：
- 白名單／額外改動的檔：
- 自行採用的小疑問：
- 需要決定的事：
