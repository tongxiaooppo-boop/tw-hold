"""全市場自建倍數月度序列（估值 2.0，upgrade_guide §2-1、§4、§5-4）。

【框架由 Opus 定】P2 實作。rebuild 時在 build_classification 之後、build_lists 之前跑。
產出（data/derived/）：
- multiples_hist.parquet：multiples_self.HIST_COLUMNS
- eps_revision.parquet：ticker, month, window, eps_fwd, n_est_q, event("normal"/"roll"/"report")，每月 10 日後一筆
- industry_pe.json：{產業: {"median_pe": float, "n": int}}（A／B 層有效樣本，B 層反推 EPS 門檻用）
- multiples_check.json：§4-5 自建 vs 交易所 PER 核對摘要
任何一檔例外 → 記錄並跳過該檔；例外檔數 > 1% → exit 1、不覆寫舊檔。
"""
from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
