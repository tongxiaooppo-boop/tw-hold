"""估值卡片組裝層（screener/val_card.py）與失效偵測（screener/detect.py）的路由與守門測試。
合成資料：每季營收 100、毛利率 30%、費損 20%、業外 5、稅 20%、10 股 → 單季 EPS = (10+5)*0.8/10 = 1.2。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from screener import detect as dt  # noqa: E402
from screener import val_card as vc  # noqa: E402

QE = pd.date_range("2022-03-31", periods=16, freq="QE")


def _qf(n=16, eps=1.2):
    return pd.DataFrame({
        "period_end": QE[:n], "revenue": 100.0, "gross_profit": 30.0, "op_income": 10.0,
        "pretax_income": 15.0, "net_income": 12.0, "ni_parent": 12.0, "eps": eps,
        "capital_stock": 100.0, "equity_parent": 50.0})


def _rev(last="2026-01"):
    months = pd.period_range("2021-01", last, freq="M")
    return pd.DataFrame({"month": [str(m) for m in months], "revenue": 33.0})


def _per(n_years=6, per=15.0):
    d = pd.bdate_range(end="2026-01-30", periods=260 * n_years)
    return pd.DataFrame({"date": d, "per": per, "pbr": 2.0})


def _px():
    d = pd.bdate_range(end="2026-01-30", periods=30)
    return pd.DataFrame({"date": d, "close": 20.0})


def _cls(typ="normal", state=(), sub=()):
    return {"type": typ, "display_type": "一般", "state": list(state), "subtags": list(sub),
            "why": [], "metrics": {}, "decided_at": "2025-12-31"}
