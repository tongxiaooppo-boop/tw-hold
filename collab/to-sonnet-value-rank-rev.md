# 【tw-hold】任務書：合理價以下排行加「月營收警示」

- 版本：2026-11-19 v1（Opus 寫；使用者 11/19 定案，Opus＋訂閱 sol 討論一輪）
- 專案路徑：`D:/g/claude/tw-hold`（直接在 main 工作，不開 worktree）

## 決策紀錄（一頁）
- 目的：大跌時找便宜股，但合理價用過去 4 季 EPS 算，營收已轉弱時「便宜」可能是假的 → 加警示。**不改排行、不剔除**。
- 衰退：近 3 個月合計營收年增 < 0 → 警示，文字帶數字讓使用者自己判斷輕重（−1% 是邊緣）。
- 降溫：只限「高成長」組；近 3 月年增比近 12 月年增少 ≥ 20 個百分點（2026-10 資料會標 宇瞻、創見、勤誠、增你強、宏捷科）。
- 每檔都顯示「近 3 月營收年增」，沒被標的也看得到（例：華城單月 −15%、3 月持平）。
- 否決：單月年增（雜訊大）、月增率與「比 12 月內高峰掉多少」（季節性、一次性認列誤觸發）、「連續 6 個月年減」（被近 3 月規則涵蓋）、衰退門檻 −5%（只是加註，寧可多標）。

## 要讀的檔案（只准讀這些）
- `screener/value_rank.py` 全檔
- `build_value_rank.py` 60–125 行
- `tests/test_value_rank.py` 全檔
- `app/streamlit_app.py` 2570–2600 行（`_value_rank_section`）
- `tests/test_glossary.py` 290–315 行（只在名詞測試失敗時讀）

## 禁止
- 只准修改：`screener/value_rank.py`、`build_value_rank.py`、`tests/test_value_rank.py`、`app/streamlit_app.py`（只動 `_value_rank_section`）、`tests/test_glossary.py`（只在 OUTSIDE_OK 追加登記）。
- 不准改 `rank`、`category`、既有常數；不准改 workflow。
- 不准 `git stash`／`reset`／`checkout`；只 `git add` 上列檔案。不准 push（Opus 驗收後推）。
- 暫存檔只放 `D:/g/claude/tw-hold/_tmp_rank/`，自己產的結束前刪掉。`data/derived/value_rank*.json` 不准 commit。
- UTF-8 無 BOM，不用 PowerShell 寫檔。小疑問自行採用並在回報註明；改變框架才停下問。

## 第 1 步：`screener/value_rank.py` 加兩個純函式＋常數

```python
DECEL_PTS = 0.20   # 高成長組：近12月年增 − 近3月年增 ≥ 20 個百分點 → 降溫

def rev_yoy(m: pd.DataFrame) -> tuple[float | None, float | None, str | None]:
    """m＝月營收長表，欄位 month（'YYYY-MM' 字串）、revenue。
    去掉 revenue 非有限值的列後，以 month 當鍵（重複月份取最後一筆）。最新月 L＝最大的 month。
    近3月年增＝(L, L−1, L−2 合計) ÷ (同三個月各往前 12 個月 合計) − 1；
    近12月年增＝(L … L−11 合計) ÷ (L−12 … L−23 合計) − 1。
    任一需要的月份缺、或分母 ≤ 0 → 該值 None（兩值各自判斷）。m 空或缺欄 → (None, None, None)。
    回傳 (近3月年增, 近12月年增, L)。月份加減用 pd.Period(…, 'M')。"""

def rev_flag(group: str, y3: float | None, y12: float | None) -> str:
    """y3 is None → ""。
    y3 < 0 → f"近三月營收比去年少 {X}，過去獲利可能撐不住"，X＝f"{abs(y3)*100:.0f}%"，若 abs(y3)*100 < 0.5 則 X＝"不到 1%"。
    group == "高成長" and y12 is not None and y12 − y3 >= DECEL_PTS − 1e-9 →
        f"營收仍在增加，但成長放慢（近12月年增 {y12:.0%} → 近三月 {y3:.0%}），合理價要再確認"
    其他 → ""。"""
```

## 第 2 步：`build_value_rank.py`
在每檔 `rows.append(dict(...))` 前：`y3, y12, rev_m = vr.rev_yoy(kw["rev"])`（`kw["rev"]` 已含公開資訊觀測站提早公告月份）；
dict 加 `rev3m_yoy=y3, rev12m_yoy=y12, rev_month=rev_m, rev_flag=vr.rev_flag(group, y3, y12)`。
`doc["thresholds"]` 加 `"decel_pts": vr.DECEL_PTS`。其他不動。

## 第 3 步：`app/streamlit_app.py` `_value_rank_section`
- DataFrame 在「EPS 到哪一季」前加兩欄：`"近3月營收年增（%）"`＝`round(r["rev3m_yoy"]*100, 1)`（None 或缺鍵 → None，一律 `.get()`，舊 JSON 沒這欄不能炸）、`"營收警示"`＝`r.get("rev_flag") or ""`。
- 底部 caption 後再加一行 `st.caption("營收警示只提醒、不影響排名：近三月營收比去年少＝衰退；高成長股近三月年增比近 12 月少 20 個百分點以上＝成長放慢。月營收到 {最新月} 。")`，最新月取 rows 裡最常見的 `rev_month`，沒有就省略那句。
- 若 `tests/test_glossary.py` 因新字串失敗：照 2026-11-19「合理價以下排行」那段格式在 OUTSIDE_OK 追加登記，理由寫「排行營收警示；fair＝估值卡 prices.fair」之類，不准改測試邏輯。

## 測試（`tests/test_value_rank.py` 追加，名稱與預期值照抄）
用 helper 造月營收：`_m(start, vals)` → DataFrame(month=連續 'YYYY-MM' 從 start 起, revenue=vals)。
- `test_rev_yoy_基本`：2024-11 起 24 個月，前 12 個月 100、後 12 個月 110 → `(≈0.10, ≈0.10, "2026-10")`
- `test_rev_yoy_只夠15月`：2025-08 起 15 個月，前 3 個 100、其餘 120 → y3≈0.20、y12 None、"2026-10"
- `test_rev_yoy_缺去年同月`：同「基本」但刪掉 2025-09 → y3 None、y12 None、"2026-10"
- `test_rev_yoy_分母非正`：同「基本」但前 12 個月全 0 → (None, None, "2026-10")
- `test_rev_yoy_空表`：空 DataFrame → (None, None, None)
- `test_rev_flag_衰退`：`rev_flag("一般", -0.2, 0.01)` == "近三月營收比去年少 20%，過去獲利可能撐不住"
- `test_rev_flag_衰退不到1%`：`rev_flag("循環", -0.003, None)` == "近三月營收比去年少不到 1%，過去獲利可能撐不住"
- `test_rev_flag_降溫`：`rev_flag("高成長", 0.51, 0.73)` == "營收仍在增加，但成長放慢（近12月年增 73% → 近三月 51%），合理價要再確認"
- `test_rev_flag_降溫只限高成長`：`rev_flag("一般", 0.51, 0.73)` == ""
- `test_rev_flag_降溫未達門檻`：`rev_flag("高成長", 0.60, 0.73)` == ""
- `test_rev_flag_無資料`：`rev_flag("高成長", None, 0.5)` == ""

## PROOF_CMD
```
cd D:/g/claude/tw-hold && python -m pytest tests/test_value_rank.py -q && python build_value_rank.py --limit 60 && python -X utf8 -c "import json;d=json.load(open('data/derived/value_rank.limit.json',encoding='utf-8'));rs=[r for g in d['groups'].values() for r in g];print(len(rs),sum(r.get('rev3m_yoy') is not None for r in rs),[r['ticker'] for r in rs if r['rev_flag']])" && python -m pytest -q -x
```
預期：value_rank 測試 23 passed（原 12＋新 11）；第三段印出筆數、有近 3 月年增的筆數（應接近全部）、被標的代號清單；全套 ≥ 1536 passed、0 failed。結束前刪 `data/derived/value_rank.limit.json`。

## 回報（寫 `collab/from-sonnet-value-rank-rev.md`，不貼程式碼）
- 完成項／commit hash（一個 commit，訊息「排行加月營收警示（衰退／高成長降溫）」，結尾 `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`）
- PROOF_CMD 各段輸出數字
- 自行採用的小疑問
