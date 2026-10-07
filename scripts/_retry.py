"""各收集腳本共用的重試規則（2026-10-07 使用者指定「全部一樣」）：最多請求 3 次；第 1 次失敗等 10 秒、第 2 次失敗等 20 秒，第 3 次失敗不再等。
官方端點偶爾回被截斷的 JSON／重置連線（上櫃 daily_close_quotes 約 4MB 常見）；OpenAPI 只回最新一天、漏了補不回來，所以重試要一致、不能各寫各的。"""
from __future__ import annotations

import time

TRIES = 3
WAITS = (10, 20)


def wait_after_failure(i: int) -> None:
    """第 i 次（從 0 起算）請求失敗之後呼叫：還有下一次才等（10、20 秒），最後一次失敗不等。"""
    if i < TRIES - 1:
        time.sleep(WAITS[min(i, len(WAITS) - 1)])
