"""B6 Opus 審查後補的測試：抓壞時 through 不前進（H2）、事件區塊排在日線寫檔之後（H1）、meta 只在需要時重寫（M4）、
事件表上傳失敗不傳 meta（H3）、meta 壞掉不崩（L3）。"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, "scripts")
import selfhost_daily_merge as dm  # noqa: E402
import selfhost_events as se  # noqa: E402
import selfhost_openapi_daily as od  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

TWSE_OK = {"stat": "OK", "fields": ["資料日期", "股票代號", "股票名稱", "除權息前收盤價", "除權息參考價", "權值+息值", "權/息"],
           "data": [["115年10月08日", "2330", "台積電", "1,000.00", "995.00", "5.00", "息"]]}
TPEX_OK = {"tables": [{"fields": ["除權息日期", "代號", "名稱", "除權息前收盤價", "除權息參考價", "權值+息值", "權/息",
                                 "現金股利", "每仟股無償配股", "現金增資股數", "現金增資認購價"], "data": []}]}
EMPTY_ACT = {"stat": "很抱歉，沒有符合條件的資料!", "tables": [{"fields": [], "data": []}]}


def _patch_http(monkeypatch, twse_ex=TWSE_OK, tpex_ex=TPEX_OK, act=EMPTY_ACT, act_exc=None):
    seen = []

    def fake(url, retries=3):
        seen.append((url, retries))
        if "TWT49U" in url:
            return twse_ex
        if "exDailyQ" in url:
            return tpex_ex
        if act_exc is not None:
            raise act_exc
        return act
    monkeypatch.setattr(se, "_http_json", fake)
    monkeypatch.setattr(se.time, "sleep", lambda s: None)
    monkeypatch.setattr(se, "_record_meta", lambda *a, **k: None)
    return seen


A, B = pd.Timestamp("2026-10-03"), pd.Timestamp("2026-10-08")


def test_正常回應_healthy_且每日窗口每個請求只試1次(monkeypatch):
    seen = _patch_http(monkeypatch)
    ev = se.fetch_recent(A, B)
    assert ev.attrs["healthy"] is True and ev.attrs["problems"] == []
    assert len(ev) == 1 and all(r == 1 for _, r in seen)                           # 不拖垮同班其他收集（H1）


def test_官方真的沒事件_stat是沒有符合條件_仍算healthy(monkeypatch):
    _patch_http(monkeypatch, twse_ex={"stat": "很抱歉，沒有符合條件的資料!"}, tpex_ex={"tables": [{"fields": list(se._TPEX_EX_FIELDS), "data": []}]})
    ev = se.fetch_recent(A, B)
    assert len(ev) == 0 and ev.attrs["healthy"] is True


def test_TWSE欄名改版_不healthy(monkeypatch):
    bad = {**TWSE_OK, "fields": ["資料日期", "股票代號", "股票名稱", "前收", "參考價", "權值+息值", "權息"]}
    _patch_http(monkeypatch, twse_ex=bad)
    ev = se.fetch_recent(A, B)
    assert ev.attrs["healthy"] is False and any("twse_ex" in p for p in ev.attrs["problems"])


def test_TWSE被擋_stat異常_不healthy(monkeypatch):
    _patch_http(monkeypatch, twse_ex={"stat": "Forbidden"})
    ev = se.fetch_recent(A, B)
    assert ev.attrs["healthy"] is False


def test_TPEX沒有tables_不healthy(monkeypatch):
    _patch_http(monkeypatch, tpex_ex={"stat": "error"})
    assert se.fetch_recent(A, B).attrs["healthy"] is False


def test_減資來源全部抓取失敗_不healthy(monkeypatch):
    _patch_http(monkeypatch, act_exc=RuntimeError("timeout"))
    ev = se.fetch_recent(A, B)
    assert ev.attrs["healthy"] is False and sum("抓取失敗" in p for p in ev.attrs["problems"]) == 4


def test_collect_events_不healthy_存列但不給meta(monkeypatch, tmp_path):
    bad = pd.DataFrame(columns=se.COLS)
    bad.attrs.update(healthy=False, problems=["twse_ex 欄名對不上"])
    monkeypatch.setattr(se, "fetch_recent", lambda a, b, retries=1: bad)
    monkeypatch.setattr(od, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(od, "SH", tmp_path)
    t, changed, meta = od.collect_events(date(2026, 10, 8), pd.Timestamp("2026-10-08 15:30"), None, hour=23)
    assert meta is None                                                            # through 不前進，不謊報已涵蓋


# ───────────── H1：事件區塊排在日線寫檔與 GITHUB_OUTPUT 之後 ─────────────
def test_main_事件區塊排在日線寫檔與output之後():
    src = (ROOT / "scripts" / "selfhost_openapi_daily.py").read_text(encoding="utf-8")
    main = src[src.index("def main() -> int:"):]
    i_write = main.index("_atomic_parquet(t, p)")
    i_out = main.index('f.write(f"changed=')
    i_events = main.index("run_events(today, fetched, now.hour)")
    assert i_write < i_out < i_events


# ───────────── M4：meta 只在需要時重寫 ─────────────
def _setup_run_events(monkeypatch, tmp_path, ev_changed, through):
    monkeypatch.setattr(od, "SH", tmp_path)
    monkeypatch.setattr(od, "EVENTS", tmp_path / "openapi_events.parquet")
    monkeypatch.setattr(od, "EVENTS_META", tmp_path / "openapi_events_meta.json")
    meta = {"through": through, "fetched_at": "x", "window": "w", "rows": 0}
    monkeypatch.setattr(od, "collect_events", lambda t, f, o, h: (pd.DataFrame({"a": [1]}), ev_changed, meta))


def test_run_events_through沒變且事件沒變_不重寫meta(monkeypatch, tmp_path):
    _setup_run_events(monkeypatch, tmp_path, ev_changed=False, through="2026-10-08")
    (tmp_path / "openapi_events_meta.json").write_text(json.dumps({"through": "2026-10-08"}), encoding="utf-8")
    assert od.run_events(date(2026, 10, 8), pd.Timestamp("2026-10-08 20:00"), 23) == (False, False)


def test_run_events_through前進_寫meta(monkeypatch, tmp_path):
    _setup_run_events(monkeypatch, tmp_path, ev_changed=False, through="2026-10-09")
    (tmp_path / "openapi_events_meta.json").write_text(json.dumps({"through": "2026-10-08"}), encoding="utf-8")
    assert od.run_events(date(2026, 10, 9), pd.Timestamp("2026-10-09 20:00"), 23) == (False, True)
    assert json.loads((tmp_path / "openapi_events_meta.json").read_text(encoding="utf-8"))["through"] == "2026-10-09"


def test_run_events_例外不拋(monkeypatch, tmp_path):
    monkeypatch.setattr(od, "EVENTS", tmp_path / "e.parquet")
    monkeypatch.setattr(od, "collect_events", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert od.run_events(date(2026, 10, 8), pd.Timestamp("2026-10-08 20:00"), 23) == (False, False)


# ───────────── H3：事件表上傳失敗就不傳 meta ─────────────
def test_workflow_事件表上傳失敗不傳meta():
    text = (ROOT / ".github" / "workflows" / "openapi_daily.yml").read_text(encoding="utf-8")
    assert "ev_ok=0" in text and '"$ev_ok" = 1' in text
    assert text.index("ev_ok=0") < text.index('"$ev_ok" = 1')


# ───────────── L3：meta 壞掉不崩 ─────────────
def test_daily_merge_meta不是dict_不崩(tmp_path):
    from tests.test_selfhost_events_daily_merge_main import _setup
    (tmp_path / "x").mkdir()
    w, dd, o = _setup(tmp_path / "x", with_meta=False)
    (dd / "openapi_events_meta.json").write_text("[1, 2]", encoding="utf-8")
    assert dm.main(["--weekly-dir", str(w), "--daily-dir", str(dd), "--out-dir", str(o)]) == 0
    man = json.loads((o / "merge_manifest.json").read_text(encoding="utf-8"))
    assert man["events_through"] == "2026-10-05"                                   # 壞 meta 當沒有，不謊報


def test_沒有資料列且fields為空_不算抓壞(monkeypatch):
    empty_tpex = {"tables": [{"fields": [], "data": []}]}
    _patch_http(monkeypatch, twse_ex={"stat": "OK", "fields": [], "data": []}, tpex_ex=empty_tpex,
                act={"stat": "OK", "tables": [{"fields": [], "data": []}]})
    ev = se.fetch_recent(A, B)
    assert len(ev) == 0 and ev.attrs["healthy"] is True
