"""把 tw-swing bundle 裡本來就有發佈的小檔 `index_0050.parquet`（tw-swing 稱 U1b，
遠比整包 `prices_adj.parquet` 小）從 CI 暫存的 `data/upstream/` 驗證後複製進
`data/reference/`（committed，app 執行期讀，不用再拖一整包 bundle）——2026-09-16 加，
理由見 `reference/index_proxy.load_0050` 檔頭。

跟 `scripts/fetch_index_proxy.py`（006201，獨立向 FinMind 抓）不同：0050 不用再打
一次 API，tw-swing 每天 publish 時就已經附了這份小檔，這裡只是「驗證後搬過去」。
兩支共用同一套驗證（`reference/price_series_guard.py`，拒絕理由與門檻見該檔頭）——
沒過就**保留舊檔案、不覆寫**，印出原因、exit 1（`rebuild.yml` 那步
`continue-on-error: true`，不擋主線三清單，但會被後面的告警步驟撿到）。

⚠️ 這裡驗的是**語意層**：傳輸層損毀（檔案壞掉／欄位變了）在 `fetch_bundle.py` 的
G1（sha256 + columns）就已經擋掉了，不用重複驗。守門要花力氣在 G1 看不出來的
東西上——內容縮水、歷史被回填、最後一筆跳空。

用法：
    python scripts/promote_index_0050.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from reference import price_series_guard as guard  # noqa: E402

SRC = REPO / "data" / "upstream" / "index_0050.parquet"
DEST = REPO / "data" / "reference" / "index_0050.parquet"


def validate_and_promote() -> int:
    if not SRC.exists():
        print(f"[SKIP] {SRC} 不存在——這次 bundle 沒附 U1b/index_0050，保留舊檔案")
        return 0

    new = guard.load_clean(SRC)       # 壞檔／空檔 → None → validate 回拒絕理由
    old = guard.load_clean(DEST)
    reasons = guard.validate(new, old)
    if reasons:
        for r in reasons:
            print(f"[REJECT] {r}")
        print("→ 不覆寫，保留舊檔案（前一日的資料錯誤不可原諒，寧可暫時舊）")
        return 1

    DEST.parent.mkdir(parents=True, exist_ok=True)
    new.to_parquet(DEST, index=False)
    print(f"[OK] 寫入 {DEST}：{len(new)} 筆，最後一筆 {new['date'].iloc[-1].date()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(validate_and_promote())
