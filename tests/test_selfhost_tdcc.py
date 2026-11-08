"""D09 集保股權分散表（scripts/selfhost_tdcc.py）。框架 2026-11-08 Opus 定：測試名稱與預期值不得改。"""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd
import pytest

sys.path.insert(0, "scripts")
import selfhost_tdcc as st  # noqa: E402

HEADER = "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%"


def _levels(ticker: str, d: str, broken: bool = False, bump: int = 0) -> list[dict]:
    """一檔一週 17 列、恆等式成立（broken=True 讓合計人數多 1）。bump 加在第 1 級人數上（合計同步加）。"""
    rows = []
    for lv in range(1, 16):
        rows.append(dict(date=d, ticker=ticker, level=lv, holders=lv * 10 + (bump if lv == 1 else 0),
                         shares=lv * 1000, pct=round(100 / 15, 2)))
    rows.append(dict(date=d, ticker=ticker, level=16, holders=0, shares=5, pct=0.0))
    rows.append(dict(date=d, ticker=ticker, level=17, holders=sum(r["holders"] for r in rows[:15]) + (1 if broken else 0),
                     shares=sum(r["shares"] for r in rows[:15]) - 5, pct=100.0))
    return rows


def _week(d: str, tickers, src=st.SRC_OFFICIAL, **kw) -> pd.DataFrame:
    rows = [r for t in tickers for r in _levels(t, d, **kw)]
    return st._typed(pd.DataFrame(rows).assign(src=src))


def _csv(d8: str, codes) -> str:
    lines = ["﻿" + HEADER]
    for c in codes:
        for r in _levels(c.strip(), "x"):
            lines.append(f"{d8},{c},{r['level']},{r['holders']},\"{r['shares']:,}\",{r['pct']:.2f}")
    return "\r\n".join(lines) + "\r\n"


# ── parse_csv ───────────────────────────────────────────────────────────
def test_parse_csv_正常週_過濾代號且帶BOM(monkeypatch):
    monkeypatch.setattr(st, "MIN_TICKERS", 1)
    df = st.parse_csv(_csv("20261106", ["2330  ", "0050", "00878", "00631L", "000218", "123456"]))
    assert set(df.ticker) == {"2330", "0050", "00878", "00631L"}
    assert len(df) == 4 * 17
    assert (df.src == st.SRC_OFFICIAL).all()
    assert set(df.date) == {pd.Timestamp("2026-11-06")}
    assert df.level.dtype == "int8" and df.holders.dtype == "int32" and df.shares.dtype == "int64"
    assert list(df.columns) == st.COLS


def test_parse_csv_千分位股數(monkeypatch):
    monkeypatch.setattr(st, "MIN_TICKERS", 1)
    df = st.parse_csv(_csv("20261106", ["2330"]))
    assert int(df.loc[df.level == 17, "shares"].iloc[0]) == sum(lv * 1000 for lv in range(1, 16)) - 5


@pytest.mark.parametrize("text", [
    None,
    "",
    "資料日期,證券代號,持股分級,人數,股數\n20261106,2330,1,1,1\n",                   # 缺比例欄
    _csv("20261106", ["2330"]) + _csv("20261030", ["2317"]).split("\r\n", 1)[1],     # 兩個日期
    _csv("20261106", ["2330", "2317", "0050"]),                                      # 檔數 < MIN_TICKERS(2000)
])
def test_parse_csv_失敗回None(text):
    assert st.parse_csv(text) is None


def test_clean_不足17級整檔丟():
    rows = _levels("2330", "2026-11-06") + _levels("2317", "2026-11-06")[:-1]
    df = st._clean(pd.DataFrame(rows), st.SRC_OFFICIAL)
    assert set(df.ticker) == {"2330"} and len(df) == 17


# ── import_tsd ──────────────────────────────────────────────────────────
def _tsd_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows).rename(columns={"ticker": "stock_id", "holders": "people"})


def test_import_tsd_只匯HIST_START起_csv勝_strip代號(tmp_path):
    hist, csvd = tmp_path / "data" / "tdcc_hist", tmp_path / "data" / "tdcc"
    hist.mkdir(parents=True)
    csvd.mkdir(parents=True)
    _tsd_frame(_levels("2330", "2019-12-27")).to_parquet(hist / "2019.parquet")              # 年份 < 2020 不讀
    _tsd_frame(_levels("2330  ", "2020-01-02") + _levels("2330  ", "2020-01-03")).to_parquet(hist / "2020.parquet")
    _tsd_frame(_levels("2330", "2026-09-11", bump=1)).to_parquet(hist / "2026.parquet")      # 跟 csv 同週不同值
    _tsd_frame(_levels("2330", "2026-09-11")).to_csv(csvd / "2026-09-11.csv", index=False)
    df = st.import_tsd(tmp_path)
    assert sorted(df.date.dt.strftime("%Y-%m-%d").unique()) == ["2020-01-03", "2026-09-11"]
    assert set(df.ticker) == {"2330"}
    assert (df.src == st.SRC_TSD).all()
    w = df[(df.date == "2026-09-11") & (df.level == 1)]
    assert int(w.holders.iloc[0]) == 10                                                     # csv 的值（hist 是 11）
    assert len(df) == 34


def test_import_tsd_兩目錄都沒有raise(tmp_path):
    with pytest.raises(FileNotFoundError):
        st.import_tsd(tmp_path)


# ── load_twswing ────────────────────────────────────────────────────────
def test_load_twswing_寬轉長(tmp_path):
    row = {"ticker": "2330", "date": pd.Timestamp("2026-10-30")}
    for lv in range(1, 16):
        row[f"holders_{lv}"] = lv * 10
        row[f"pct_{lv}"] = 6.67
    row["total_holders"], row["total_shares"] = 1200, 119995
    pd.DataFrame([row]).to_parquet(tmp_path / "2026-10-30.parquet")
    df = st.load_twswing(tmp_path)
    assert sorted(df.level.unique().tolist()) == list(range(1, 16)) + [17]
    assert df.loc[df.level <= 15, "shares"].isna().all()
    l17 = df[df.level == 17].iloc[0]
    assert int(l17.holders) == 1200 and int(l17.shares) == 119995 and pd.isna(l17.pct)


# ── merge_rows ──────────────────────────────────────────────────────────
def test_merge_rows_official蓋TSD且計數值不同的筆數(capsys):
    old = _week("2026-11-06", ["2330", "2317"], src=st.SRC_TSD)
    new = _week("2026-11-06", ["2330", "2317"])
    new.loc[(new.ticker == "2330") & (new.level == 3), "holders"] = 999
    out, n = st.merge_rows(old, new)
    assert n == 1
    assert len(out) == 34 and (out.src == st.SRC_OFFICIAL).all()
    assert "::warning::" in capsys.readouterr().err


def test_merge_rows_TSD不蓋official():
    old = _week("2026-11-06", ["2330"])
    new = _week("2026-11-06", ["2330"], src=st.SRC_TSD, bump=5)
    out, n = st.merge_rows(old, new)
    assert n == 0 and (out.src == st.SRC_OFFICIAL).all()
    assert int(out.loc[out.level == 1, "holders"].iloc[0]) == 10


def test_merge_rows_同src新的勝():
    old = _week("2026-11-06", ["2330"], src=st.SRC_TSD)
    new = _week("2026-11-06", ["2330"], src=st.SRC_TSD, bump=5)
    out, n = st.merge_rows(old, new)
    assert n == 0 and int(out.loc[out.level == 1, "holders"].iloc[0]) == 15


# ── compare ─────────────────────────────────────────────────────────────
def test_compare_相符率_只比兩邊都有值的欄():
    a = _week("2026-10-30", ["2330"])
    b = a[a.level != 16].copy()
    b["shares"] = b["shares"].astype("Int64")
    b.loc[b.level <= 15, "shares"] = pd.NA            # 像 tw-swing：1–15 級沒有股數
    b.loc[b.level == 17, "pct"] = float("nan")
    b.loc[b.level == 2, "holders"] = 1                # 一格不同
    r = st.compare(a, b)
    assert len(r) == 1
    row = r.iloc[0]
    assert (row.n_a, row.n_b, row.n_both, row.n_equal) == (17, 16, 16, 15)
    assert row.ratio == pytest.approx(15 / 16)


def test_compare_無共同週回空表():
    r = st.compare(_week("2026-10-30", ["2330"]), _week("2026-11-06", ["2330"]))
    assert r.empty and {"date", "n_both", "ratio"} <= set(r.columns)


# ── identity_bad / week_gaps ────────────────────────────────────────────
def test_identity_bad_違反比例():
    df = pd.concat([_week("2026-11-06", ["2330"]), _week("2026-11-06", ["2317"], broken=True)])
    s = st.identity_bad(df)
    assert s.loc[pd.Timestamp("2026-11-06")] == pytest.approx(0.5)


def test_week_gaps_用ISO週_含跨年():
    assert st.week_gaps(pd.to_datetime(["2026-01-02", "2026-01-08", "2026-01-23"])) == {(2026, 3)}
    assert st.week_gaps(pd.to_datetime(["2025-12-26", "2026-01-09"])) == {(2026, 1)}
    assert st.week_gaps(pd.to_datetime(["2026-01-02"])) == set()


# ── gate_checks ─────────────────────────────────────────────────────────
TICKS = [f"{1000 + i}" for i in range(10)]


def _weeks(fridays, last_tickers=TICKS, **kw):
    parts = [_week(d, TICKS) for d in fridays[:-1]] + [_week(fridays[-1], last_tickers, **kw)]
    return pd.concat(parts, ignore_index=True)


FRIDAYS = [str(d.date()) for d in pd.date_range("2026-09-04", periods=9, freq="W-FRI")]


def test_gate_checks_正常無訊息(monkeypatch):
    monkeypatch.setattr(st, "MIN_TICKERS", 5)
    assert st.gate_checks(_weeks(FRIDAYS)) == ([], [])


def test_gate_checks_最新週檔數驟減報錯(monkeypatch):
    monkeypatch.setattr(st, "MIN_TICKERS", 5)
    errs, _ = st.gate_checks(_weeks(FRIDAYS, last_tickers=TICKS[:8]))
    assert len(errs) == 1 and errs[0].startswith("tdcc：")


def test_gate_checks_低於MIN_TICKERS報錯(monkeypatch):
    monkeypatch.setattr(st, "MIN_TICKERS", 50)
    errs, _ = st.gate_checks(_weeks(FRIDAYS))
    assert any(e.startswith("tdcc：") for e in errs)


def test_gate_checks_恆等式違反報錯(monkeypatch):
    monkeypatch.setattr(st, "MIN_TICKERS", 5)
    errs, _ = st.gate_checks(_weeks(FRIDAYS, broken=True))
    assert len(errs) == 1 and errs[0].startswith("tdcc：")


def test_gate_checks_新缺口只警告_已知缺口不報(monkeypatch):
    monkeypatch.setattr(st, "MIN_TICKERS", 5)
    known = ["2026-02-06", "2026-02-27"]                                   # W6、W9 → 缺 W7、W8；(2026, 8) 已知
    errs, warns = st.gate_checks(pd.concat([_week(d, TICKS) for d in known]))
    assert errs == [] and len(warns) == 1 and "7" in warns[0] and warns[0].startswith("tdcc：")


def test_gate_checks_空表():
    assert st.gate_checks(st._typed(pd.DataFrame(columns=st.COLS))) == ([], [])


# ── write / _read ───────────────────────────────────────────────────────
def test_write_主鍵重複或負值不寫(tmp_path):
    out = tmp_path / "t.parquet"
    w = _week("2026-11-06", ["2330"])
    with pytest.raises(ValueError):
        st.write(pd.concat([w, w]), out)
    bad = w.copy()
    bad.loc[0, "shares"] = -1
    with pytest.raises(ValueError):
        st.write(bad, out)
    bad = w.copy()
    bad["src"] = "finmind"
    with pytest.raises(ValueError):
        st.write(bad, out)
    assert not out.exists()


def test_write_讀回型別一致(tmp_path):
    out = tmp_path / "sub" / "t.parquet"
    w = _week("2026-11-06", ["2330", "0050"])
    st.write(w, out)
    back = st._read(out)
    assert list(back.columns) == st.COLS and len(back) == 34
    assert back.ticker.map(type).eq(str).all() and back.level.dtype == "int8"


# ── main ────────────────────────────────────────────────────────────────
def test_main_收集併入(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(st, "OUT", tmp_path / "tdcc.parquet")
    st.write(_week("2026-10-30", ["2330"], src=st.SRC_TSD), st.OUT)
    monkeypatch.setattr(st, "fetch_latest", lambda: _week("2026-11-06", ["2330", "2317"]))
    assert st.main([]) == 0
    df = st._read(st.OUT)
    assert len(df) == 51 and df.date.nunique() == 2
    assert "2026-11-06" in capsys.readouterr().out


def test_main_收集失敗exit1不寫(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "OUT", tmp_path / "tdcc.parquet")
    monkeypatch.setattr(st, "fetch_latest", lambda: None)
    assert st.main([]) == 1
    assert not st.OUT.exists()


def test_main_import_tsd只補缺的主鍵(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "OUT", tmp_path / "tdcc.parquet")
    st.write(_week("2026-11-06", ["2330"]), st.OUT)
    tsd = pd.concat([_week("2026-11-06", ["2330"], src=st.SRC_TSD, bump=5),
                     _week("2026-10-30", ["2330"], src=st.SRC_TSD)])
    monkeypatch.setattr(st, "import_tsd", lambda root, start=st.HIST_START: tsd)
    assert st.main(["--import-tsd", str(tmp_path)]) == 0
    df = st._read(st.OUT)
    assert len(df) == 34
    nov = df[df.date == "2026-11-06"]
    assert (nov.src == st.SRC_OFFICIAL).all() and int(nov.loc[nov.level == 1, "holders"].iloc[0]) == 10

