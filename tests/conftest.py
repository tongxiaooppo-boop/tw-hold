"""讓 `import factors` / `import screener` / `import reference` 在測試裡可用，
不需要安裝套件。repo 根目錄放進 sys.path，對一次就好。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_holiday_fetch(monkeypatch):
    """單元測試不可打真的證交所休市表（daily_merge 的 manifest 會呼叫 fetch_closed）。
    預設回 None（＝抓不到、fail-open）；要測有休市表的情境，測試自己再 monkeypatch。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import last_trading_day_guard as g  # noqa: PLC0415
    except Exception:       # noqa: BLE001
        return
    monkeypatch.setattr(g, "fetch_closed", lambda: None)
