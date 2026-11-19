"""金融股營收全空時，業外表仍要有資料（nonop_rows financial 旗標）。"""
import pandas as pd

from screener import eps_windows as ew
from screener import val_card
from test_val2_eps_windows import make_q


def _q_rev_nan() -> pd.DataFrame:
    q = make_q("2026Q3")
    q["revenue"] = float("nan")
    return q


def test_nonop_rows_金融營收空有資料():
    assert len(val_card.nonop_rows(_q_rev_nan(), financial=True)) == ew.NONOP_QUARTERS


def test_nonop_rows_非金融營收空為空():
    assert val_card.nonop_rows(_q_rev_nan(), financial=False) == []
