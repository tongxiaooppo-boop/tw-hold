# 【tw-hold】調研：哪些事件會改變發行股數、我們漏了哪些（版本 2026-11-22 r1）

> **專案：tw-hold（`D:\g\claude\tw-hold`，main 分支）。** 指令先 `cd D:\g\claude\tw-hold`。回報覆蓋寫到 `D:\g\claude\tw-hold\collab\from-codex.md`。
> 只准新增／修改 `research/share_events_2026-11/` 底下的檔案。不改正式程式、不 commit、**不上網**（需要外部確認的事寫進「待查」，不要猜成事實）。UTF-8 無 BOM，不用 PowerShell 寫檔。暫存檔放同一資料夾、結束前刪掉。

## 背景（一段就好）

估值卡「近 5 年 EPS」有「還原／實際」切換，並在年度下標註股數事件。還原靠 `reference/corporate_actions.py` 的事件表 `SPLITS`（來源 `reference/corporate_actions_resolved.json`，由 `scripts/selfhost_events.py`、`scripts/resolve_splits.py` 產生）。目前事件 type 只有：`ex_both`／`ex_rights`（除權、除權息，m＞1）、`cap_reduction`（減資，m＜1；現金減資 m=None 不還原）、`par_change`（面額變更）、`split`。使用者問：分割、增資／減資、除權、債轉股之外，**還有什麼會改變發行股數**，我們漏了哪些。

## 要讀的檔案（只准讀這些）

- `reference/corporate_actions.py` 第 1–170 行（事件格式、`_m`、`_events`）、第 380–440 行（`adjust_eps`）
- `scripts/selfhost_events.py` 第 139–330 行（官方除權息、減資／面額變更抓取）、第 354–370 行（FinMind 分割）
- `screener/val_card.py` 裡 `event_label`、`eps_years` 兩個函式（用 grep 找位置，只讀這兩個）
- 資料（唯讀）：`D:\g\claude\tw-swing\data\fundamentals\balance.parquet`（欄：ticker, period_end, capital_stock＝股本元, …）、`income.parquet`（欄：ticker, period_end, eps, **equity_parent＝歸母淨利**（名字誤導，不是權益）, net_income）、`reference/corporate_actions_resolved.json`

## 要做的三件事

### 1. 事件清單（知識整理，不上網）
台灣上市櫃普通股，**所有會改變流通／發行股數**的事件，至少涵蓋：股票分割／反分割、面額變更、盈餘轉增資／資本公積轉增資（除權）、現金增資（公開／私募）、減資（彌補虧損、現金退還、庫藏股註銷）、可轉債轉換、員工認股權／限制型股票、特別股轉普通股、合併／股份轉換／收購發新股、公司分割（分割減資）、海外存託憑證、庫藏股買回（未註銷）。漏掉的你補。

每一項一列，欄位：事件｜發行股數怎麼變｜**EPS 要不要追溯還原**（依 IAS 33：無對價的股數變動追溯；有對價的用加權平均、不追溯；附特別股利的股份合併等特殊情況寫清楚）｜股價要不要還原｜官方哪裡有公告（寫你確定的資料表名稱；不確定寫「待查」）｜本專案目前有沒有收（對照上面的 type）。

### 2. 用資料掃缺口
寫 `research/share_events_2026-11/scan.py`：
- 每檔用 balance 的 `capital_stock` 算季對季變動率；`|變動| ≥ 3%` 的列為「股本跳動」。
- 對每筆跳動，查 `SPLITS` 該檔在 **前一季季末＋1 天～本季季末** 之間有沒有事件（任何 type，含 m=None）。
- 輸出 `research/share_events_2026-11/scan.csv`：ticker, period_end, cap_prev, cap_now, chg_pct, has_event, event_types。
- 印一行摘要：`掃描 N 檔、跳動 M 筆、有事件 A、無事件 B`。
- 只掃 2021-01-01 起的季度。

### 3. 抽樣判讀無事件的跳動
從 `has_event=False` 裡依 |chg_pct| 由大到小取前 30 筆，每筆用你的知識判斷最可能是哪種事件（現增／債轉股／合併／員工認股／庫藏股註銷／資料錯誤…），信心高中低。另外用 income 的「歸母淨利 ÷ EPS」隱含股數，看同一季有沒有跟著跳，幫忙判斷是真變動還是資料錯。**不確定就寫不確定**，不要編。

## 產出

`research/share_events_2026-11/survey.md`，固定三節：`## 事件清單`（第 1 件的表）、`## 本專案覆蓋`（掃描摘要＋各類缺口數）、`## 缺口與建議`（每條：缺什麼｜影響多少檔／筆｜建議收或不收｜理由）。全文 ≤ 300 行，白話中文。

## PROOF_CMD（完成前自己跑一次，貼輸出）

```
cd D:\g\claude\tw-hold && set PYTHONIOENCODING=utf-8 && python research/share_events_2026-11/scan.py && python -c "import pathlib,csv;t=pathlib.Path('research/share_events_2026-11/survey.md').read_text(encoding='utf-8');assert all(k in t for k in ['## 事件清單','## 本專案覆蓋','## 缺口與建議']);r=list(csv.DictReader(open('research/share_events_2026-11/scan.csv',encoding='utf-8')));assert r and {'ticker','period_end','chg_pct','has_event'}<=set(r[0]);print('OK',len(r))"
```
預期：第一行是 `掃描 … 檔、跳動 … 筆、有事件 …、無事件 …`，最後一行 `OK <列數>`。

## 回報（覆蓋 `collab/from-codex.md`，只填這些欄位，不貼程式碼）

- 完成項：
- 產出檔案：
- PROOF_CMD 輸出（原文）：
- 掃描摘要：
- 最重要的 3 個缺口（一行一個）：
- 待查（需要上網或官方確認的）：
- 需要決定的事：
