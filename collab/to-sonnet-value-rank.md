# 【tw-hold】任務書：合理價以下排行榜（一般／循環／高成長 各前 20）

- 版本：2026-11-19 v1（Opus 寫；使用者 11/19 定：三類各前 20、沒有就從缺、範圍＝股價 ≤ 合理價）
- 專案路徑：`D:/g/claude/tw-hold`（直接在 main 工作，不開 worktree）
- 前置：`8de80af`（金融股已公布季只看 EPS）已在 main。

## 要讀的檔案（只准讀這些）
- `build_revenue_watch.py` 全檔（照它的結構：CLI、失敗不覆寫、`--limit`）
- `scripts/check_fin_eps_cards.py` 全檔（照它建卡的寫法：`LocalBundle`＋`val_inputs.card_inputs`＋`val_card.build_card`）
- `app/val_inputs.py` 13–40 行（`ensure_multiples`）
- `.github/workflows/rebuild.yml` 140–152 行、244–260 行
- `app/streamlit_app.py` 150–155 行（`_load`）、4160–4166 行（價值分頁呼叫處）；畫面寫法只參考 `_revenue_page`（2525–2600 行）

## 禁止
- 只准新增：`screener/value_rank.py`、`build_value_rank.py`、`tests/test_value_rank.py`；只准修改：`.github/workflows/rebuild.yml`（只加一步）、`app/streamlit_app.py`（只加一個函式＋價值分頁一行呼叫）。
- 不准改 `screener/val_card.py`、`eps_windows.py`、`classify.py`；不准改 cron、既有步驟。
- 不准 `git stash`／`reset`／`checkout`；只 `git add` 自己的檔。不准 push。
- 暫存檔只放 `D:/g/claude/tw-hold/_tmp_rank/`，結束前刪掉。產出的 `data/derived/value_rank.json` 不要 commit（CI 會產）。
- 檔案一律 UTF-8 無 BOM，不用 PowerShell 寫檔。小疑問自行採用並在回報註明；改變框架行為才停下問，最多 2 次。

---

## 第 1 步：純函式 `screener/value_rank.py`（不做 IO）

```python
GROWTH_REV = 0.30      # 近 4 季營收 ÷ 前 4 季營收 − 1 ≥ 30% → 高成長
SPIKE_EPS = 2.0        # 近 4 季 EPS ÷ 前 3 年平均年 EPS > 2 → EPS 暴增
TOP_N = 20
GROUPS = ("一般", "循環", "高成長")

def eps_ratio(q: pd.DataFrame) -> float | None:
    """q＝季財報（period_end、eps…），先依 period_end 排序、去掉 eps 為 NaN 的列。
    少於 16 季 → None。ttm＝最後 4 季 eps 合計；前 3 年＝倒數第 5–8、9–12、13–16 季各自合計的平均。
    平均 ≤ 0 → None。回傳 ttm ÷ 平均。"""

def revenue_growth(q: pd.DataFrame) -> float | None:
    """依 period_end 排序，取最後 8 列（不去 NaN）。少於 8 列、任一 revenue 非有限值、或前 4 季合計 ≤ 0 → None。
    回傳 最後 4 季合計 ÷ 前 4 季合計 − 1。"""

def category(typ: str | None, eps_x: float | None, rev_g: float | None) -> tuple[str, str]:
    """回傳 (組別, 原因短句)。
    grow = rev_g is not None and rev_g >= GROWTH_REV and typ != "cyclical"
    1. grow → ("高成長", f"近4季營收年增 {rev_g:.0%}")
    2. typ == "cyclical" → ("循環", "分類為景氣循環")
    3. eps_x is not None and eps_x > SPIKE_EPS → ("循環", f"EPS 為前3年平均 {eps_x:.1f} 倍、營收沒同步暴增，可能是循環高峰或一次性收益")
    4. 其他 → ("一般", "")"""

def rank(rows: list[dict]) -> dict[str, list[dict]]:
    """rows 每筆至少有 group、price、fair。只留 price、fair 皆有限且 price <= fair 的列；
    gap = price / fair − 1（寫回該列）；每組依 gap 由小到大（同 gap 依 ticker）取前 TOP_N。
    回傳三組都在的 dict（沒有就是 []）。"""
```

## 第 2 步：`build_value_rank.py`（照 build_revenue_watch 結構）

1. `asof`＝`--asof`（預設台北今天）。`val_inputs.ensure_multiples()`。
2. 母體＝`data/upstream/fundamentals/universe.parquet` 中 `in_mktcap500` 為真（市值前 500）。檔不在 → 印錯誤、回 1、不覆寫。cls 取 `data/derived/stock_class.json`（`stocks` 是 list）。
3. 每檔照 `check_fin_eps_cards.py` 方式建卡（`LocalBundle` 可直接 import 那支用的同一個類別）；例外或 `missing` → 計入 `errors`，不中斷。
4. 每檔一列：`ticker, name（universe.stock_name）, industry, type（cls.type）, display_type, route, tier, price, px_date, cheap, fair, dear`（後三者取 `card["prices"]`，None 就 None），`eps_last_q`（`card["eps"]["reported"]["quarters"][-1]["q"]`，沒有就 None），`eps_ttm`（`card["eps"]["ttm"]["eps"]`），`eps_x`＝`eps_ratio(kw["qf"])`，`rev_g`＝`revenue_growth(kw["qf"])`，`group, why`＝`category(...)`。
5. `lag`：該列 `eps_last_q` 比全母體最常見的 `eps_last_q` 舊 → `f"最新一季財報未公布，EPS 用到 {eps_last_q}"`，否則 ""。
6. 寫 `data/derived/value_rank.json`：
   `{"asof": "YYYY-MM-DD", "built_at": 台北時間ISO, "universe_n": int, "carded_n": int, "below_fair_n": int（price<=fair 總數）, "errors": int, "thresholds": {"growth_rev": 0.30, "spike_eps": 2.0, "top_n": 20}, "groups": rank(rows)}`；ensure_ascii=False。
   carded_n < 0.9 × universe_n → 印 `::error::`、回 1、不覆寫。

## 第 3 步：接線與畫面

- `rebuild.yml`：在「月營收分頁」那步之後加一步「合理價以下排行」`run: python build_value_rank.py`，`continue-on-error: true`（失敗不擋其他產出）。確認 commit 那步會帶到 `data/derived/value_rank.json`（若是逐檔列出就把它加進去）。
- `app/streamlit_app.py`：新增 `_value_rank_section(data: dict | None)`，在價值分頁 `_card_list("value", ...)` 之後呼叫 `_value_rank_section(_load("value_rank.json"))`。
  - data 是 None → `st.info("排行還沒產生（每天盤後重算）")`。
  - 標題「合理價以下排行」；一行說明：`{asof} 收盤，市值前 500 中有 {below_fair_n} 檔股價在合理價（含）以下；各類取離合理價最遠的前 20 檔。`
  - 三組依「一般、循環、高成長」各一個 `st.subheader` ＋ `st.dataframe`（`hide_index=True`）；空組顯示「從缺」。
  - 欄位（中文欄名）：代號、名稱、產業、股價、便宜價、合理價、距合理價（%，一位小數）、估價方法（PE→本益比、PB→淨值比）、EPS 到哪一季、原因（why）、備註（lag）。
  - 讀 JSON 一律 `.get()`（舊資料沒有欄位不能炸）。
  - 底下 caption：「循環＝分類為景氣循環，或近 4 季 EPS 超過前 3 年平均 2 倍、營收沒同步暴增；高成長＝近 4 季營收年增 30% 以上。合理價依各股歷史倍數，不是買賣建議。」

## 測試 `tests/test_value_rank.py`

| 測試名 | 預期 |
|---|---|
| `test_eps_ratio_基本` | 16 季，前 12 季 eps 各 1.0、後 4 季各 3.0 → 3.0 |
| `test_eps_ratio_不足16季` | 15 季 → None |
| `test_eps_ratio_前三年平均非正` | 前 12 季 eps 全 0 → None |
| `test_revenue_growth_基本` | 8 季，前 4 季營收 100、後 4 季 150 → 0.5 |
| `test_revenue_growth_有缺` | 最後一季營收 NaN → None |
| `test_category_高成長優先` | ("growth", 5.0, 0.5) → "高成長" |
| `test_category_循環分類不進高成長` | ("cyclical", None, 0.9) → "循環" |
| `test_category_eps暴增營收沒跟` | ("normal", 3.0, 0.1) → "循環"，原因含 "3.0 倍" |
| `test_category_一般` | ("normal", 1.2, 0.1) → ("一般", "") |
| `test_rank_只留合理價以下且排序` | 一般組 3 列 gap −0.5、+0.1、−0.2 → 只剩 2 列、順序 −0.5、−0.2 |
| `test_rank_取前20與從缺` | 一般 25 列全低於合理價 → 20 列；循環、高成長 → [] |
| `test_rank_缺價跳過` | fair None 或 price NaN 的列不出現 |

## PROOF_CMD（Opus 會自己重跑）

```
cd D:/g/claude/tw-hold && PYTHONIOENCODING=utf-8 python -m pytest tests/test_value_rank.py -q
cd D:/g/claude/tw-hold && PYTHONIOENCODING=utf-8 python build_value_rank.py --asof 2026-11-19 && PYTHONIOENCODING=utf-8 python -c "import json;d=json.load(open('data/derived/value_rank.json',encoding='utf-8'));g=d['groups'];print(d['universe_n'],d['carded_n'],d['below_fair_n'],{k:len(v) for k,v in g.items()});print([r['ticker'] for r in g['一般'][:3]],[r['ticker'] for r in g['循環'][:3]],[r['ticker'] for r in g['高成長'][:3]]);assert all(r['price']<=r['fair'] for v in g.values() for r in v)"
cd D:/g/claude/tw-hold && PYTHONIOENCODING=utf-8 python -m pytest -q
```
預期：
- 第一條 12 passed。
- 第二條：universe_n 500、carded_n ≥ 450、below_fair_n 約 200（±20）、三組各 20；一般組第 1 名 2377、循環組前 3 名含 2392、高成長組第 1 名 5289（Opus 11/19 用同資料試算的結果）；assert 不出錯。
- 全套 0 failed（基準 1513 passed、4 skipped）。

## Commit
- 一個 commit「合理價以下排行（一般／循環／高成長）」，結尾 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`。commit 前確認 email 是隱私信箱。不准 push。

## 回報（寫到 `collab/from-sonnet-value-rank.md`，不貼程式碼）
- 完成項（第 1／2／3 步、測試各一行）、commit hash、PROOF_CMD 三條結果（第二條貼兩行輸出）、耗時（第二條跑幾秒）、自行採用的小決定、需要 Opus 決定的事。
