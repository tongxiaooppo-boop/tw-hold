import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ca_detail", Path(__file__).resolve().parent.parent / "scripts" / "selfhost_twse_ca_detail.py")
m = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(m)


def test_num_parses_official_strings():
    assert m._num("1.5 元／股") == 1.5
    assert m._num("125,000,000 股") == 125000000.0
    assert m._num("305.56282065 股") == 305.56282065
    assert m._num("") == 0.0 and m._num(None) == 0.0


class _R:
    def __init__(self, j): self._j = j
    def json(self): return self._j


class _S:
    def __init__(self, j): self.j = j
    def get(self, *a, **k): return _R(self.j)


def test_fetch_maps_columns():
    row = ["2614  ", "東森", "0.4 元／股", "", "80 股", "0 股", "125,000,000 股", "12.8 元／股", "12,500,000 股", "12,500,000 股", "100,000,000 股", "305.56282065 股"]
    r = m.fetch("2614", __import__("pandas").Timestamp("2026-10-06"), _S({"stat": "ok", "data": [row]}))
    assert r == {"cash_div": 0.4, "bonus_per_1000": 80.0, "ca_shares": 125000000.0, "ca_price": 12.8, "ca_public": 12500000.0, "ca_staff": 12500000.0, "ca_orig": 100000000.0, "ca_per_1000": 305.56282065}
