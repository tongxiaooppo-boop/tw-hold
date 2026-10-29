"""產 `data/derived/revenue_watch.json`（「月營收」分頁）。框架 2026-10-29 由 Opus 定。

步驟（Cline 照這個順序實作，不准改步驟與輸出格式）：
1. `bundle_data.ensure_assets()`；讀 `data/upstream/fundamentals/universe.parquet`，
   universe ＝ `in_mktcap500` 為真的 ticker（裸代號）。檔案不在 → 印錯誤、回 1、不覆寫舊 JSON。
2. **一次**把 bundle 的 prices_adj / per / revenue / income / balance / cashflow 讀進記憶體，
   用 `_install_preloaded_reader()` 換掉 `bundle_data._read`，之後照常呼叫
   `bundle_data.prices(code)`、`per_history`、`revenue`、`financials`——正規化沿用原函式，
   但不再每檔重讀 parquet（500 檔 × 6 張表逐檔讀會很慢）。
3. 今天收盤：`scripts/pcf_fetchers.fetch_twse_closes(codes)` 拿上市收盤（上櫃抓不到就算了，
   沿用 bundle 最後收盤）；比 bundle 最後一天新才 append 到 px 尾端再算均線與估值。
4. 對 `revenue_watch.periods_to_show(今天台北日期)` 的每一期：
   - 有 `data/revenue_mops/<month>.parquet` → source="mops"，營收數字、note、
     first_seen_at、revised 都取它；has_first_seen=True。
   - 沒有 → source="bundle"，從 bundle revenue 長表取該月；上月／去年同月從同一張長表找；
     note=""、first_seen_at=None、revised=False；has_first_seen=False。
   - 只處理 universe 內、該月有營收的公司。
   - hist ＝ bundle_data.revenue(code)，若沒有該月就把該月（來自 mops）append 上去；
     再**截到 ≤ 該月**（算上一期時不能看到更新的月份）。
   - 估值：`valuation.estimate(qf, hist, px, per)`，qf＝`factors.factors.quarterly_factors(fin)`；
     任何例外 → 該列 est_ok=False、est_reason="計算失敗：<例外類型>"，**不中斷整批**。
   - 用 `revenue_watch.make_row` 組列。
5. 寫 JSON（ensure_ascii=False、indent=None、浮點不四捨五入）。
   任一期 rows 為 0 不算失敗（例：月初第一晚）。

用法：
    python build_revenue_watch.py              # 寫 data/derived/revenue_watch.json
    python build_revenue_watch.py --limit 20   # 只算前 20 檔（本機試跑）
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "app"))

OUT = REPO / "data" / "derived" / "revenue_watch.json"
MOPS_DIR = REPO / "data" / "revenue_mops"


def _install_preloaded_reader() -> None:
    """把 bundle_data._read 換成「第一次整檔讀進記憶體、之後按 ticker 切片」的版本。
    行為（回傳欄位、suffixed 比對 .TW/.TWO/裸代號、缺欄時只回存在的欄）必須與原 _read 相同。"""
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
