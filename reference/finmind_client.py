# 複製自 tw-swing @c310b60（src/twswing/data/finmind.py），2026-09-07；
# 上游改動不自動同步。用途：個股即時查（僅本地；PRD §6.5、M4）。
# 漂移後果小（FinMind API 變更才有感）。
#
# ⚠️ tw-hold 與 tw-swing 差異：
#   - `read_token()` 的 .env 路徑改成 tw-hold repo 根目錄（parents[1]）。
#   - 雲端佈署**不放** FINMIND_TOKEN，即時補抓在雲端停用（PRD §M0.2）——
#     `read_token()` 回 None 時呼叫端要走「只讀 bundle」路徑。
"""FinMind 取數：節流、續跑、落地。**本地工具。**

## 免費層規則（2026-08-31 查證，文件 + 實測一致）

| 項目 | 值 |
| :--- | :--- |
| 匿名配額 | **300/hr** |
| 註冊免費層 | **600/hr**（帶 `token=`） |
| 超額 | **HTTP 402** `Requests reach the upper limit` |
| 配額查詢 | `GET api.web.finmindtrade.com/v2/user_info`（需 token） |
| 重置機制 | ⚠️ **文件沒寫** |
| 授權 | ⚠️ **教育／非商業用途** |

⚠️ **重置機制沒寫，所以節流用「滾動一小時」而不是「整點歸零」。**
⚠️ **token 從環境變數或 .env 讀，不走命令列參數。**
⚠️ **`Throttle.seed()` 會把 n 個同時間戳灌進視窗**——若 n 接近 limit，
   下一次 `wait()` 會一次 sleep ~3600s（tw-swing F3 首跑實測卡 47 分）。
   批次抓取時寧可不 seed、只靠 min_gap 節流 + 撞 402 退避（見 tw-swing
   `fetch_raw_prices.py` 的做法）。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

API = "https://api.finmindtrade.com/api/v4/data"
USER_INFO = "https://api.web.finmindtrade.com/v2/user_info"

#: 免費層可取的 dataset（逐一實測回 200 且有資料才加入）。
#: `TaiwanStockPriceAdj`（還原價）**不在這裡**——標 `-backer-sponsor`，
#: 實測回 400「Your level is free」。
FREE_DATASETS = {
    "TaiwanStockPrice",
    "TaiwanStockInstitutionalInvestorsBuySell",
    "TaiwanStockMarginPurchaseShortSale",
    "TaiwanStockDividendResult",
    "TaiwanStockDividend",
    "TaiwanStockMonthRevenue",
    "TaiwanStockPER",
    "TaiwanStockFinancialStatements",
    "TaiwanStockBalanceSheet",
    "TaiwanStockCashFlowsStatement",
    "TaiwanStockInfo",
    # 公司行動事件（2026-09-08 實測匿名可取，含 before_price/after_price）——
    # scripts/resolve_splits.py 用來算分割/減資 factor。
    "TaiwanStockSplitPrice",
    "TaiwanStockCapitalReductionReferencePrice",
}

ANON_LIMIT = 300
TOKEN_LIMIT = 600

_REPO_ROOT = Path(__file__).resolve().parents[1]


def read_token() -> str | None:
    """依序找 `FINMIND_TOKEN` 環境變數、tw-hold repo 根目錄的 `.env`。
    找不到回 None（匿名層 / 雲端）。"""
    tok = os.environ.get("FINMIND_TOKEN")
    if tok:
        return tok.strip()
    env = _REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "FINMIND_TOKEN" and v.strip():
                return v.strip().strip('"').strip("'")
    return None


class Throttle:
    """滾動一小時的節流器，外加最小間隔（= 3600 / limit）。

    保守係數：我們不知道伺服器怎麼算這一小時，貼著上限跑會偶發 402，
    而 402 後要等多久沒有文件。寧可慢 10%。
    """

    def __init__(self, limit: int, safety: float = 0.9, pace: bool = True) -> None:
        self.limit = max(1, int(limit * safety))
        self.min_gap = 3600 / self.limit if pace else 0.0
        self.last = 0.0
        self.hits: deque[float] = deque()

    def _prune(self, now: float) -> None:
        while self.hits and now - self.hits[0] >= 3600:
            self.hits.popleft()

    def wait(self) -> float:
        """必要時 sleep，回傳實際等待秒數。"""
        slept = 0.0
        gap = self.min_gap - (time.time() - self.last)
        if gap > 0:
            time.sleep(gap)
            slept += gap
        now = time.time()
        self._prune(now)
        if len(self.hits) >= self.limit:
            more = 3600 - (now - self.hits[0]) + 1
            time.sleep(max(0.0, more))
            slept += max(0.0, more)
            now = time.time()
            self._prune(now)
        self.hits.append(now)
        self.last = now
        return slept

    def seed(self, n: int) -> None:
        """把「這一小時已經用掉 n 點」灌進視窗（重啟續跑用）。
        ⚠️ n 接近 limit 時下一次 wait() 會 sleep ~1hr——批次抓取別用。"""
        now = time.time()
        for _ in range(min(n, self.limit)):
            self.hits.append(now)


@dataclass
class Client:
    token: str | None = None
    throttle: Throttle | None = None
    backoff0: int = 60
    max_retry: int = 5
    stats: dict = field(default_factory=lambda: {"req": 0, "402": 0, "wait": 0.0})

    def __post_init__(self) -> None:
        if self.throttle is None:
            self.throttle = Throttle(TOKEN_LIMIT if self.token else ANON_LIMIT)

    def get(self, dataset: str, **params) -> list[dict]:
        if dataset not in FREE_DATASETS:
            raise ValueError(
                f"{dataset} 不在免費層清單。免費層可取的是：{sorted(FREE_DATASETS)}"
            )
        q = {"dataset": dataset, **params}
        if self.token:
            q["token"] = self.token
        url = API + "?" + urllib.parse.urlencode(q)
        wait = 0
        for attempt in range(self.max_retry):
            self.stats["wait"] += self.throttle.wait()
            self.stats["req"] += 1
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    return json.loads(r.read().decode("utf-8")).get("data") or []
            except urllib.error.HTTPError as e:
                if e.code != 402:
                    raise
                self.stats["402"] += 1
                wait = self.backoff0 * (2**attempt)
                time.sleep(wait)
                self.stats["wait"] += wait
        raise RuntimeError(f"連續 {self.max_retry} 次 402，最後等了 {wait}s 仍未恢復")


def quota(token: str) -> tuple[int, int]:
    """回傳 (已用, 上限)。這個查詢本身不扣點（2026-08-31 實測驗證）。"""
    with urllib.request.urlopen(f"{USER_INFO}?token={token}", timeout=30) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("status") != 200:
        raise RuntimeError(f"查配額失敗：{d.get('msg')}")
    return int(d["user_count"]), int(d["api_request_limit_hour"])
