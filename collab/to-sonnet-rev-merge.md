【tw-hold】月營收併入估值排行 — 任務書 v1（2026-11-20，Opus）
工作目錄：D:/g/claude/tw-hold（直接在主目錄做；禁 stash／reset／checkout；只 add 自己改的檔）

## 0. 決策（使用者 2026-11-20 拍板：估值保留、月營收併進估值、不要讓人誤會、類似邏輯排行只留一種）

| 原月營收分頁 | 處理 | 理由 |
|---|---|---|
| ③ 估值價差排行 | 刪 | 跟估值排行重複，且用另一套引擎（valuation.estimate vs val_card），兩頁數字會打架 |
| ④ 持有提示（到估值先賣、跌破線全賣） | 刪 | 賣出建議語氣＋同上另一套估值 |
| ② 營收成長排行 | 刪（不另開排序） | 只留一種排行＝距合理價 |
| ① 公布清單 | 改成表頭一行公布進度＋每列「月營收」欄 | 資訊保留、不再是另一張表 |

估值排行只有一種排序（距合理價，三組不變）；月營收只當欄位資訊，不影響排名、不影響分組。
月營收分頁程式（`build_revenue_watch.py`、`screener/revenue_watch.py`、`_revenue_page`）保留不刪、停排程；`REVENUE_PAGE_ON` 維持 False。

## 1. 要讀的檔案（只准讀這些）
- `screener/value_rank.py`（全檔 119 行）
- `build_value_rank.py`（全檔 134 行）
- `screener/revenue_watch.py` 第 55–135 行（`LOW_BASE_REV`、`yoy_streak`、`record_high`，直接 import 重用，不要複製）
- `app/streamlit_app.py` 中 `def _value_rank_section` 整個函式（grep 找）
- `.github/workflows/rebuild.yml` 第 145–160 行；`.github/workflows/revenue_watch.yml` 第 75–120 行
- `tests/test_value_rank.py`

## 2. 介面（照抄簽名，不准改）

`screener/value_rank.py` 新增：

```python
def rev_month_info(m: pd.DataFrame, month: str | None) -> dict:
    """月營收長表（欄 month、revenue；month 可能是 'YYYY-MM' 字串或月初 Timestamp）＋最新月 'YYYY-MM'
    → {"rev_m_yoy": 單月年增 | None, "rev_streak": int, "rev_record": bool, "rev_low_base": bool}。
    month 為 None 或表空 → {"rev_m_yoy": None, "rev_streak": 0, "rev_record": False, "rev_low_base": False}。
    - rev_m_yoy＝當月 ÷ 去年同月 − 1；任一缺或去年同月 ≤ 0 → None
    - rev_low_base＝去年同月缺或 < revenue_watch.LOW_BASE_REV
    - rev_streak／rev_record：先把 month 正規化成月初 Timestamp，再呼叫 revenue_watch.yoy_streak／record_high"""

def rev_progress(rows: list[dict], asof: str) -> dict:
    """目標月＝asof 所在月的上一個月（'YYYY-MM'）。回 {"month": 目標月, "published": rev_month ≥ 目標月 的列數, "total": len(rows)}。"""

def rev_text(r: dict) -> str:
    """排行表「月營收（年增）」欄文字。r 用 rev_month／rev_m_yoy／rev_low_base／rev3m_yoy／rev_record／rev_streak。
    - rev_month None → "—"
    - 開頭 f"{月}月 "（不補零）＋（rev_low_base → "低基期"；rev_m_yoy None → "—"；否則 _pct）
    - rev3m_yoy 非 None → 加 "｜近3月 " + _pct(rev3m_yoy)
    - 標籤（依序、"・" 相連，接在後面前面加 "・"）：rev_record → "創新高"；rev_streak ≥ 3 → f"連 {n} 月成長"
    - _pct(v)：abs(v) < 0.005 → "±0%"，否則 f"{v*100:+.0f}%"
    例：{"rev_month":"2026-10","rev_m_yoy":0.25,"rev3m_yoy":0.18,"rev_record":True,"rev_streak":7,"rev_low_base":False}
       → "10月 +25%｜近3月 +18%・創新高・連 7 月成長" """
```

## 3. 要改的檔

1. `screener/value_rank.py`：加上面三個函式。
2. `build_value_rank.py`：每列在 `rev_yoy` 之後 `**vr.rev_month_info(kw["rev"], rev_m)`；doc 加 `"rev_progress": vr.rev_progress(rows, asof_s)`（用全部建卡的 rows，不是排行後的）。docstring「價值分頁」改「估值排行分頁」。
3. `app/streamlit_app.py::_value_rank_section`：
   - 表頭 `"近3月營收年增（%）"` 換成 `"月營收（年增）"`，該格用 `vr.rev_text(r)`（`from screener import value_rank as vr`，看檔內其他 screener import 怎麼寫照做）；`_row` 裡 `mob` 那段若因此重複顯示近3月年增，把近3月那部分拿掉，其餘不動。
   - caption 後面加：`rp = data.get("rev_progress")`；若 rp 且 total > 0 且 published < 0.98×total → `st.caption(f"{int(月)}月營收公布中 {published}/{total} 檔，還沒公布的顯示上個月。")`。缺欄（舊 JSON）一律 `.get()`，不准 KeyError。
4. `.github/workflows/rebuild.yml`：「月營收分頁」整個 step 註解掉，上方加一行 `# 2026-11-20 停：月營收併入估值排行（build_value_rank.py），分頁程式保留`。
5. `.github/workflows/revenue_watch.yml`：「重算月營收分頁」step 改名「重算估值排行（含當晚月營收）」，run 改 `python build_value_rank.py`（id 仍 build、env 不變）；commit 段兩處路徑清單 `data/derived/revenue_watch.json` 改 `data/derived/value_rank.json`；commit 訊息不動。
6. `tests/test_value_rank.py` 新增（名稱與預期值照寫）：
   - `test_rev_month_info_單月年增`：24 個月，2025-10＝100、2026-10＝125（其餘 100）→ rev_m_yoy＝0.25、rev_low_base＝False（金額用 ×1e9 避免低基期）
   - `test_rev_month_info_低基期`：去年同月 5e7 → rev_low_base True
   - `test_rev_month_info_Timestamp與字串同結果`：同資料 month 用字串和 Timestamp 各跑一次，dict 相等
   - `test_rev_month_info_month_None`：→ 預設值 dict
   - `test_rev_progress`：asof "2026-11-20"，rows rev_month = ["2026-10","2026-10","2026-09",None] → {"month":"2026-10","published":2,"total":4}
   - `test_rev_text_完整`：上面 docstring 的例子
   - `test_rev_text_低基期與短連續`：rev_low_base True、rev_streak 2、rev_record False、rev3m_yoy None → "10月 低基期"
   - `test_rev_text_接近零`：rev_m_yoy 0.004 → 含 "±0%"

## 4. 不准做
- 不改排名、分組、門檻、`rank()`、`category()`、`rev_flag()`；不動 `revenue_watch.py`／`build_revenue_watch.py`／`_revenue_page`。
- 不新增 JSON 以外的產出檔；暫存檔、一次性腳本放 D:/g/claude/tw-hold/collab/tmp/，結束前刪掉。
- 不 push（Opus 驗收後 push）。小疑問自行採用並在回報註明；改變上述行為才停下回報（最多停 2 次）。

## 5. PROOF_CMD
```
cd D:/g/claude/tw-hold && python -m pytest -q tests/test_value_rank.py tests/test_app_smoke.py tests/test_workflow_schedules.py tests/test_b6_workflows.py
```
預期：全部 passed（含上面 8 個新測試），0 failed。再跑 `python -m pytest -q` 全套，回報數字。
本機若有 bundle：`python build_value_rank.py --limit 30` 應寫出 `data/derived/value_rank.limit.json`，含 `rev_progress` 與列的 `rev_m_yoy` 等欄；跑完刪掉該 limit 檔。沒 bundle 就回報「略過」。

## 6. 回報（寫 collab/from-sonnet-rev-merge.md，欄位照填，不貼程式碼）
- 完成項：
- commit（一個 commit，訊息「估值排行併入月營收欄位、停月營收分頁排程」＋ Co-Authored-By 行）：
- PROOF_CMD 數字：
- 全套 pytest 數字：
- build --limit 結果：
- 自行採用的小決定：
- 需要 Opus 決定的事：
