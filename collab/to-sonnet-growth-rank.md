# 【tw-hold】月營收成長排行（估值排行頁第二張表）（版本 2026-11-20 v1）

> 專案：tw-hold，工作目錄 `D:\g\claude\tw-hold`（main 分支，直接在這裡改，沒有 worktree）。
> 同一時間只有你改程式。**禁止** `git stash`／`reset`／`checkout`／`push`；只 `git add` 你改的檔。commit 信箱必須是 `300864627+tongxiaooppo-boop@users.noreply.github.com`（先 `git config user.email` 確認，不是就停）。
> 暫存檔只能放 `D:\g\claude\tw-hold\` 底下，結束前刪掉。不上網、不 pip install。檔案 UTF-8 無 BOM，不用 PowerShell 寫檔。

## 背景（已拍板，不要改）
估值排行頁多一張「月營收成長排行」，不看估值：只排目標月（asof 的上一個月）已公布的公司，依單月營收年增由大到小；年增 > 0、去年同月營收 ≥ 1 億（沿用 `rev_low_base`）、排除建材營造；最多 30 檔。沒公布的天然不在榜，下次重算公布了就補回。**MoM 不刪人，只標記**：MoM < −3% 且該月不碰農曆新年窗 → 標「月減」。已公布 < 90% 時標「暫排」。

## 框架（Opus 已 commit，不准改名稱、簽名、常數）
- `screener/lny.py`：已完成，直接用 `lny.month_touches_lny(month)`。
- `screener/value_rank.py` 檔尾：`MOM_WARN`、`GROWTH_TOP_N`、`GROWTH_PROVISIONAL`、`EXCLUDE_INDUSTRY`、`rev_mom`、`mom_warn`、`growth_rank`——docstring 就是規格，填實作。覺得規格有問題就停下回報，不要自行改。

## 要讀的檔案（只准讀這些）
- `screener/value_rank.py`（全檔，約 230 行）
- `screener/lny.py`（全檔）
- `build_value_rank.py`（全檔，136 行）
- `app/streamlit_app.py` 第 2109～2135 行（`_vtable`）、第 2570～2625 行（`_value_rank_section`，照它的樣式寫）、第 4214～4222 行（分頁呼叫處）
- `tests/test_value_rank.py` 第 1～20 行與 135～208 行（照它的寫法）
- `tests/test_app_smoke.py` 第 370～396 行

## 要改的檔
1. **`screener/value_rank.py`**：填 `rev_mom`、`mom_warn`、`growth_rank`。`rev_mom` 的月份解析照 `rev_month_info` 的作法（可用 `_to_month_ts`）。
2. **`build_value_rank.py`**：
   - 每列 dict 加 `rev_mom=vr.rev_mom(kw["rev"], rev_m)`、`mom_warn=vr.mom_warn(<同一個值>, rev_m)`（先算 mom 存變數再用兩次）。
   - `doc` 加 `"growth": vr.growth_rank(rows, rp["month"])`，其中 `rp = vr.rev_progress(rows, asof_s)`（`"rev_progress": rp` 共用同一個，不要算兩次）。
   - `thresholds` 加 `"mom_warn": vr.MOM_WARN, "growth_top_n": vr.GROWTH_TOP_N`。
3. **`app/streamlit_app.py`**：新增 `_growth_rank_section(data: dict | None) -> None`，放在 `_value_rank_section` 正下方；分頁呼叫處改成先 `_value_rank_section(...)` 再 `_growth_rank_section(...)`（同一個 `_load("value_rank.json")` 結果存變數傳兩次）。內容：
   - `st.header("月營收成長排行")`
   - `g = (data or {}).get("growth")`；沒有 → `st.info("月營收成長排行還沒產生（下次重算後出現）")` 並 return。
   - caption：`f"{月}月營收，市值前500已公布 {published}/{total} 檔；依單月營收年增排序，不看估值。已排除建材營造 {excluded_construction} 檔、去年同月營收不到 1 億、年增 ≤ 0。"`（月＝`int(month[5:7])`）
   - `provisional` 為真 → 再一行 caption：`"公布中（暫排）：還沒公布的公司公布後會自動補進來，名次會變動。"`
   - rows 空 → `st.write("從缺")`。
   - 表用 `_vtable`，欄：`["名次", "代號", "單月年增（%）", "月增（%）", "月減", "近3月年增（%）", "連續成長／創新高", "股價", "合理價（元）", "產業"]`。代號欄同 `_value_rank_section` 用 `_RawHtml(_tk_link(...) + " " + _esc(name))`；百分比 `f"{v*100:+.1f}"`、None → "—"；月減欄 `mom_warn` 真 → "⚠️ 月減" 否則 ""；連續成長／創新高：`rev_record` → "創新高"、`rev_streak ≥ 3` → f"連 {n} 月"，以「・」連接；股價、合理價用 `_px`，None → "—"。手機只留 名次｜代號｜單月年增｜月增：`num={0,2,3,5,7,8}`、`src={4,5,6,7,8,9}`；代號 cell 用 (name, 手機小字) tuple，小字＝月減文字（沒有就空字串）。
   - 表後 caption：`"月減＝單月營收比上月少 3% 以上，只提醒、不影響名次；農曆新年前 3 天到後 6 天碰到的月份不標（春節工作天少，月減是季節）。合理價只供參考，本表不看估值。"`
   - 讀 JSON 一律 `.get()`（舊 JSON 沒有新欄位不准炸）。

## 測試（新增，名稱與預期值照抄）
`tests/test_value_rank.py` 加：
- `test_rev_mom_基本`：month 2026-09 營收 100、2026-10 營收 90 → `rev_mom(m, "2026-10") ≈ -0.10`
- `test_rev_mom_上月缺`：只有 2026-10 → None
- `test_rev_mom_上月非正`：2026-09 為 0 → None
- `test_rev_mom_month_None`：→ None
- `test_mom_warn_門檻`：`mom_warn(-0.031,"2026-10") is True`、`mom_warn(-0.03,"2026-10") is False`、`mom_warn(None,"2026-10") is False`
- `test_mom_warn_春節月不標`：`mom_warn(-0.5,"2026-02") is False`、`mom_warn(-0.5,"2026-01") is True`、`mom_warn(-0.5,"2025-01") is False`
- `test_growth_rank_篩選與排序`：6 列，month 2026-10：A yoy 0.5、B yoy 0.8、C yoy 0.8（ticker C>B）、D yoy −0.1、E yoy 0.9 但 `rev_low_base` True、F yoy 2.0 industry 建材營造；另一列 G rev_month 2026-09 yoy 3.0 → rows 的 ticker 順序 `[B, C, A]`、rank `[1,2,3]`、`published == 6`、`total == 7`、`excluded_construction == 1`
- `test_growth_rank_取前30`：35 列都合格 → `len(rows) == 30`
- `test_growth_rank_暫排`：total 10、published 8 → provisional True；published 9 → False
- `test_growth_rank_不改輸入`：呼叫後傳入的 dict 沒有 "rank" 鍵
- `test_growth_rank_yoy_None略過`：rev_m_yoy None 的已公布列不進 rows，但算進 published

`tests/test_app_smoke.py` 加：
- `test_growth_rank_section_無growth鍵`：`app._growth_rank_section({"asof": "2026-11-19"})` 與 `app._growth_rank_section(None)` 都不炸
- `test_growth_rank_section_有資料`：給 1 列 growth（欄位只給 ticker、name、rev_m_yoy、rev_mom、mom_warn True），其餘欄缺 → 不炸

## PROOF_CMD
```
cd D:\g\claude\tw-hold && python -m pytest tests/test_value_rank.py tests/test_lny.py tests/test_app_smoke.py -q && python build_value_rank.py --limit 80 && python -c "import json; d=json.load(open('data/derived/value_rank.limit.json',encoding='utf-8')); g=d['growth']; print(g['month'], g['published'], g['total'], g['provisional'], g['excluded_construction'], len(g['rows'])); print([(r['rank'], r['ticker'], round(r['rev_m_yoy'],3), r.get('mom_warn')) for r in g['rows'][:5]])" && python -m pytest -q -x 2>&1 | tail -1
```
預期：前三個測試檔全過（含上面新增 13 個）；limit 版 JSON 有 growth、month＝`2026-10`、rows 名次從 1 連續、rev_m_yoy 遞減；全套 pytest 全過（目前基準 1536＋4 個 lny 測試，加你的 13 個＝約 1553 passed，數字以實際為準並回報）。
**跑完刪掉 `data/derived/value_rank.limit.json`。不要跑不帶 --limit 的 build（會覆寫正式 JSON）。**

## commit
一個 commit：`月營收成長排行：填 growth_rank／rev_mom／mom_warn、build 產 growth、估值排行頁第二張表`，結尾加 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`。不 push。

## 回報（寫 `collab/from-sonnet-growth-rank.md`，≤ 300 字，不貼程式碼）
- 完成項（逐檔一行）
- commit hash
- PROOF_CMD 實際輸出（最後兩行 print＋全套 pytest 最後一行）
- 需要 Opus 決定的事（沒有寫「無」）
- 小疑問自行採用的地方（沒有寫「無」）
