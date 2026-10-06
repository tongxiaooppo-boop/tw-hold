"""預告表快照：累積檔只增不減、同抓取日取代、提前天數計算。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import selfhost_forecast_snapshot as fs  # noqa: E402

F = ["除權除息日期", "股票代號", "名稱", "除權息", "無償配股率", "現金增資配股率", "現金增資認購價", "現金股利"]


def _snap(day, ex="115年10月20日"):
    return {"_fetched": day, "fields": F, "data": [[ex, "2330", "台積電", "息", "0", "0", "0", "5.0"]]}


def test_roc_and_lead_days():
    d = fs.summarize(_snap("2026-10-06"))
    assert d.loc[0, "ex"].isoformat()[:10] == "2026-10-20" and d.loc[0, "lead_days"] == 14


def test_save_load_roundtrip_and_same_day_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "OUT", tmp_path / "f.jsonl")
    fs.save([_snap("2026-10-13"), _snap("2026-10-06")])
    rows = fs.load()
    assert [r["_fetched"] for r in rows] == ["2026-10-06", "2026-10-13"]      # 依抓取日排序
    again = [r for r in rows if r["_fetched"] != "2026-10-13"] + [_snap("2026-10-13", "115年10月21日")]
    fs.save(again)
    assert len(fs.load()) == 2                                                   # 同日取代、不重複
