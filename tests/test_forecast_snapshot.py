"""預告表快照：OpenAPI／網站兩種來源正規化結果一致、舊格式升級、累積檔只增不減、同抓取日取代。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import selfhost_forecast_snapshot as fs  # noqa: E402

F = ["除權除息日期", "股票代號", "名稱", "除權息", "無償配股率", "現金增資配股率", "現金增資認購價", "現金股利"]


def _web():
    return [["115年10月20日", "2330", "台積電", "息", "0.00000000", "0.00000000", "0.00000000", "5.00000000"],
            ["115年10月15日", "00401A", "主動摩根", "息", "0.00000000", "0.00000000", "0.00000000", "<p>待公告實際收益分配金額</p>"]]


def _openapi():
    return [{"Date": "1151020", "Code": "2330", "Name": "台積電", "Exdividend": "息", "StockDividendRatio": "",
             "SubscriptionRatio": "", "SubscriptionPricePerShare": "", "CashDividend": "5.000000"},
            {"Date": "1151015", "Code": "00401A", "Name": "主動摩根", "Exdividend": "息", "StockDividendRatio": "",
             "SubscriptionRatio": "", "SubscriptionPricePerShare": "", "CashDividend": ""}]


def test_openapi_and_web_normalize_to_same_values():
    a = {r["code"]: r for r in fs.normalize_openapi(_openapi())}
    b = {r["code"]: r for r in fs.normalize_web(F, _web())}
    assert a["2330"]["ex"] == b["2330"]["ex"] == "2026-10-20"
    assert a["2330"]["cash"] == b["2330"]["cash"] == 5.0
    assert a["00401A"]["cash"] is None and b["00401A"]["cash"] is None          # 待公告 ＝ None


def test_legacy_record_upgraded_and_lead_days():
    legacy = {"_fetched": "2026-10-06", "fields": F, "data": _web()}
    d = fs.summarize(legacy)
    assert set(d["code"]) == {"2330", "00401A"}
    assert int(d.loc[d["code"] == "2330", "lead_days"].iloc[0]) == 14
    assert int(d["cash"].isna().sum()) == 1


def test_save_load_roundtrip_and_same_day_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "OUT", tmp_path / "f.jsonl")
    mk = lambda day, src="openapi": {"_fetched": day, "source": src, "rows": fs.normalize_openapi(_openapi())}  # noqa: E731
    fs.save([mk("2026-10-13"), mk("2026-10-06")])
    assert [r["_fetched"] for r in fs.load()] == ["2026-10-06", "2026-10-13"]      # 依抓取日排序
    again = [r for r in fs.load() if r["_fetched"] != "2026-10-13"] + [mk("2026-10-13", "web")]
    fs.save(again)
    loaded = fs.load()
    assert len(loaded) == 2 and loaded[-1]["source"] == "web"                       # 同日取代、不重複


def test_fetch_falls_back_to_web(monkeypatch):
    calls = []

    class R:
        def __init__(s, js, bad=False): s.js, s.bad = js, bad
        def raise_for_status(s):
            if s.bad: raise RuntimeError("boom")
        def json(s): return s.js

    def fake_get(url, **kw):
        calls.append(url)
        if "openapi" in url:
            return R([], bad=True)
        return R({"stat": "OK", "fields": F, "data": _web()})
    monkeypatch.setattr(fs.requests, "get", fake_get)
    src, rows = fs.fetch()
    assert src == "web" and len(rows) == 2 and len(calls) == 2
