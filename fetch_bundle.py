"""從 tw-swing 私有 repo 的 Release（移動 tag `data-latest`）拉上游 bundle
→ 解到 `data/upstream/`。

M0.5 骨架——**尚未接線**。以下是待實作的守門員（PRD §3.2、PLAN §M0.5）：

  G1  schema assert：`_meta.json` 帶 `schema_version` + 每檔欄位清單，
      對不上 → **大聲失敗**（兩個 repo 之間唯一的正式介面，不要「盡力而為」）
  G3  `_meta.json.trading_date` vs 預期最新交易日：不符**不失敗**，
      在清單頁標記資料日期
  G5  `reference/UPSTREAM.md` 記來源 / commit / PAT 到期日；
      `check_upstream_drift.py` 比 hash（只提醒）
  ⚠️  只有 U1a 資產（財報/PER/universe）時要能正常跑——缺 U1b 的日線檔
      就標「日線類特徵不可用」，不拋錯（M0a 才跑得起來）

PAT：fine-grained、只給 tw-swing 一個 repo 的 `contents: read`。
  - 本地：`.env` 的 `TWSWING_BUNDLE_PAT`
  - 雲端：`st.secrets["TWSWING_BUNDLE_PAT"]`（Streamlit Community Cloud）

用法（實作後）：
    python fetch_bundle.py            # 拉最新 data-latest → data/upstream/
    python fetch_bundle.py --check    # 只驗 schema/日期，不下載
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent
UPSTREAM = REPO / "data" / "upstream"

BUNDLE_REPO = "tongxiaooppo-boop/tw-swing"   # 私有 repo，bundle 走其 Release
RELEASE_TAG = "data-latest"
SCHEMA_VERSION = 1                     # G1：與 tw-swing publish step 對齊

BUNDLE_FILES = {
    # U1a（週更，`fundamentals.yml`）
    "fundamentals/income.parquet": "u1a",
    "fundamentals/balance.parquet": "u1a",
    "fundamentals/cashflow.parquet": "u1a",
    "fundamentals/dividend.parquet": "u1a",
    "fundamentals/per.parquet": "u1a",
    "_meta.json": "u1a",
    # U1b（日更，`publish_bundle.yml`）——缺這些只是「日線類特徵不可用」
    # universe.parquet 在 U1b：算市值要全宇宙最新日線，只有 publish_bundle 的
    # job 有 store（fundamentals.yml 的 runner 沒有）。M0a 沒有它 → 清單不做
    # 市值前500 過濾（可接受，M0a 是退化里程碑）。
    "fundamentals/universe.parquet": "u1b",
    "prices_adj.parquet": "u1b",
    "prices_raw_close.parquet": "u1b",
    "revenue.parquet": "u1b",
    "index_0050.parquet": "u1b",
    "chips.parquet": "u1b",          # 法人買賣超（PRD §3.1 / §5.2.1，M1 候選池要用）
}


def _read_pat() -> str | None:
    tok = os.environ.get("TWSWING_BUNDLE_PAT")
    if tok:
        return tok.strip()
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "TWSWING_BUNDLE_PAT" and v.strip():
                return v.strip().strip('"').strip("'")
    try:
        import streamlit as st  # noqa: PLC0415
        return st.secrets.get("TWSWING_BUNDLE_PAT")
    except Exception:
        return None


def main() -> int:
    raise SystemExit(
        "fetch_bundle.py 尚未接線——等 M0.1a（tw-swing publish step）產出第一個 "
        f"Release `{RELEASE_TAG}` 後實作 G1/G3/G5。目前 build_factors.py 直接讀 "
        f"{UPSTREAM}（若有）或退化執行。")


if __name__ == "__main__":
    main()
