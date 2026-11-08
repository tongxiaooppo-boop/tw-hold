"""D04 逐日發行股數（scripts/selfhost_shares.py）。框架 2026-11-08 Opus 定：測試名稱與預期值不得改。"""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd
import pytest

sys.path.insert(0, "scripts")
import selfhost_shares as ss  # noqa: E402

D = date(2018, 3, 15)

# 欄名照 2026-11-08 實測回應原文
TWSE_FIELDS = ["證券代號", "證券名稱", "國際證券編碼", "發行股數", "外資及陸資尚可投資股數",
               "全體外資及陸資持有股數", "外資及陸資尚可投資比率", "全體外資及陸資持股比率",
               "外資及陸資共用法令投資上限比率", "陸資法令投資上限比率", "與前日異動原因(註)",
               "最近一次上市公司申報外資及陸資持股異動日期"]
TPEX_FIELDS_2018 = ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數", "成交金額(元)",
                    "成交筆數", "最後買價", "最後賣價", "發行股數", "次日參考價", "次日漲停價", "次日跌停價"]
TPEX_FIELDS_2026 = ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數", "成交金額(元)",
                    "成交筆數", "最後買價", "最後買量(張數)", "最後賣價", "最後賣量(張數)", "發行股數",
                    "次日參考價", "次日漲停價", "次日跌停價"]


def _twse_row(code, shares):
    return [code, "名", "TW000" + code + "004", shares, "1", "1", 1.0, 1.0, "100.00", "100.00", "", "115/04/29"]


def _twse(rows, d="20180315", stat="OK"):
    return {"stat": stat, "date": d, "fields": TWSE_FIELDS, "data": rows}


def _tpex(rows, fields=TPEX_FIELDS_2018, d="20180315"):
    return {"date": d, "tables": [{"fields": fields, "data": rows, "totalCount": len(rows)}]}


def _tpex_row(code, shares, fields=TPEX_FIELDS_2018):
    r = ["x"] * len(fields)
    r[fields.index("代號")] = code
    r[fields.index("發行股數")] = shares
    return r


def _df(rows):
    """rows: (ticker, market, 'YYYY-MM-DD', shares, src)"""
    return pd.DataFrame(rows, columns=ss.COLS).assign(
        date=lambda x: pd.to_datetime(x["date"]), issued_shares=lambda x: x["issued_shares"].astype("int64"))


# ───────── 解析 ─────────
def test_shares_num_千分位與無效值():
    assert ss._shares_num("25,932,370,067") == 25932370067
    assert ss._shares_num(" 592,058,651 ") == 592058651
    for bad in ("", "-", "--", None, "abc", "0", "-5"):
        assert ss._shares_num(bad) is None


def test_parse_twse_用欄名取欄_略過ISIN欄():
    df = ss.parse_twse(_twse([_twse_row("1808", "893,031,743"), _twse_row("2330", "25,932,370,067")]), D)
    assert list(df.columns) == ss.COLS
    got = dict(zip(df["ticker"], df["issued_shares"]))
    assert got == {"1808": 893031743, "2330": 25932370067}
    assert set(df["market"]) == {"TW"} and set(df["src"]) == {"official"}
    assert (df["date"] == pd.Timestamp("2018-03-15")).all()


def test_parse_twse_只留四碼且丟無效股數():
    rows = [_twse_row("2330", "100"), _twse_row("910322", "200"), _twse_row("00400A", "300"),
            _twse_row("1101", "--"), _twse_row("2330", "999")]          # 重複代號留第一筆
    df = ss.parse_twse(_twse(rows), D)
    assert dict(zip(df["ticker"], df["issued_shares"])) == {"2330": 100}


@pytest.mark.parametrize("j", [
    None,
    {"stat": "很抱歉，沒有符合條件的資料!", "date": "20180315"},
    _twse([_twse_row("2330", "100")], d="20261106"),                       # 回應日期不符（靜靜回今天）
    _twse([]),                                                              # 交易日 0 列＝失敗
    {"stat": "OK", "date": "20180315", "fields": ["證券代號", "證券名稱"], "data": [["2330", "x"]]},  # 缺股數欄
])
def test_parse_twse_失敗情況回None(j):
    assert ss.parse_twse(j, D) is None


@pytest.mark.parametrize("fields", [TPEX_FIELDS_2018, TPEX_FIELDS_2026])
def test_parse_tpex_兩種年代欄位都吃(fields):
    df = ss.parse_tpex(_tpex([_tpex_row("8299", "197,073,993", fields), _tpex_row("5483", "592,058,651", fields)],
                             fields=fields), D)
    assert list(df.columns) == ss.COLS
    assert dict(zip(df["ticker"], df["issued_shares"])) == {"8299": 197073993, "5483": 592058651}
    assert set(df["market"]) == {"TWO"}


@pytest.mark.parametrize("j", [
    None,
    _tpex([_tpex_row("8299", "1")], d="20261106"),
    _tpex([]),
    {"date": "20180315", "tables": []},
])
def test_parse_tpex_失敗情況回None(j):
    assert ss.parse_tpex(j, D) is None


def test_fetch_day_任一邊失敗整天None(monkeypatch):
    monkeypatch.setattr(ss, "SLEEP", 0)
    monkeypatch.setattr(ss, "_get", lambda url: _twse([_twse_row("2330", "1")]) if "twse" in url else None)
    assert ss.fetch_day(D) is None


def test_fetch_day_兩邊都成功合併(monkeypatch):
    monkeypatch.setattr(ss, "SLEEP", 0)
    monkeypatch.setattr(ss, "_get", lambda url: (_twse([_twse_row("2330", "1")]) if "twse" in url
                                                 else _tpex([_tpex_row("8299", "2")])))
    df = ss.fetch_day(D)
    assert sorted(zip(df["market"], df["ticker"])) == [("TW", "2330"), ("TWO", "8299")]


# ───────── 交易日曆 ─────────
def test_trading_days_取raw_prices區間內不重複日期(tmp_path):
    p = tmp_path / "raw_prices.parquet"
    pd.DataFrame({"ticker": ["2330", "8299", "2330", "2330"], "market": ["TW", "TWO", "TW", "TW"],
                  "date": pd.to_datetime(["2026-11-03", "2026-11-03", "2026-11-05", "2026-11-10"])}).to_parquet(p)
    assert ss.trading_days(p, date(2026, 11, 1), date(2026, 11, 6)) == [date(2026, 11, 3), date(2026, 11, 5)]
    with pytest.raises(FileNotFoundError):
        ss.trading_days(tmp_path / "nope.parquet", date(2026, 11, 1), date(2026, 11, 6))


# ───────── 合併 ─────────
def test_merge_rows_official蓋TSD且計數值不同的筆數():
    old = _df([("2330", "TW", "2026-11-06", 100, "tw-stock-data"),
               ("1808", "TW", "2026-11-06", 714, "tw-stock-data"),
               ("8299", "TWO", "2026-11-05", 5, "tw-stock-data")])
    new = _df([("2330", "TW", "2026-11-06", 100, "official"),
               ("1808", "TW", "2026-11-06", 893, "official")])
    out, overridden = ss.merge_rows(old, new)
    assert overridden == 1
    assert len(out) == 3
    got = {(r.ticker, r.date.strftime("%Y-%m-%d")): (r.issued_shares, r.src) for r in out.itertuples()}
    assert got[("1808", "2026-11-06")] == (893, "official")
    assert got[("2330", "2026-11-06")] == (100, "official")
    assert got[("8299", "2026-11-05")] == (5, "tw-stock-data")
    assert str(out["issued_shares"].dtype) == "int64"
    assert list(out["date"]) == sorted(out["date"])


def test_merge_rows_TSD不蓋official():
    old = _df([("1808", "TW", "2026-11-06", 893, "official")])
    new = _df([("1808", "TW", "2026-11-06", 714, "tw-stock-data")])
    out, overridden = ss.merge_rows(old, new)
    assert overridden == 0
    assert out["issued_shares"].tolist() == [893] and out["src"].tolist() == ["official"]


def test_merge_rows_同src新的勝():
    old = _df([("2330", "TW", "2026-11-06", 1, "official")])
    new = _df([("2330", "TW", "2026-11-06", 2, "official")])
    out, _ = ss.merge_rows(old, new)
    assert out["issued_shares"].tolist() == [2]


# ───────── TSD 匯入 ─────────
def _tsd_tree(tmp_path):
    d = tmp_path / "data" / "universe" / "daily"
    d.mkdir(parents=True)
    hdr = "key,date,stock_id,name,market,open,high,low,close,volume,amount,change,limit,shares,transactions,price_basis,last_price\n"
    (d / "2018-03-15.csv").write_text(hdr +
        "k,2018-03-15,2330,台積電,twse,1,1,1,1,1,1,0,,25930380720,1,,\n"
        "k,2018-03-15,0050,元大台灣50,twse,1,1,1,1,1,1,0,,100000,1,,\n"
        "k,2018-03-15,8299,群聯,tpex,1,1,1,1,1,1,0,,197073993,1,,\n"
        "k,2018-03-15,6932,水星,emerging,1,1,1,1,1,1,0,,5000,1,,\n"
        "k,2018-03-15,910322,康師傅,twse,1,1,1,1,1,1,0,,20045400,1,,\n"
        "k,2018-03-15,1101,台泥,twse,1,1,1,1,1,1,0,,,1,,\n", encoding="utf-8")
    (d / "2026-11-06.csv").write_text(hdr + "k,2026-11-06,2330,台積電,twse,1,1,1,1,1,1,0,,25932370067,1,,\n",
                                      encoding="utf-8")
    return tmp_path


def test_import_tsd_市場對照_四碼_丟空股數(tmp_path):
    df = ss.import_tsd(_tsd_tree(tmp_path))
    assert list(df.columns) == ss.COLS
    got = sorted(zip(df["date"].dt.strftime("%Y-%m-%d"), df["market"], df["ticker"], df["issued_shares"]))
    assert got == [("2018-03-15", "TW", "0050", 100000), ("2018-03-15", "TW", "2330", 25930380720),
                   ("2018-03-15", "TWO", "8299", 197073993), ("2026-11-06", "TW", "2330", 25932370067)]
    assert set(df["src"]) == {"tw-stock-data"}


def test_import_tsd_日期區間只讀範圍內檔案(tmp_path):
    df = ss.import_tsd(_tsd_tree(tmp_path), start=date(2026, 1, 1))
    assert df["date"].dt.strftime("%Y-%m-%d").unique().tolist() == ["2026-11-06"]
    with pytest.raises(FileNotFoundError):
        ss.import_tsd(tmp_path / "nope")


# ───────── 比對 ─────────
def test_compare_同日相符率():
    off = _df([("2330", "TW", "2018-03-15", 100, "official"), ("1808", "TW", "2018-03-15", 893, "official"),
               ("9999", "TW", "2018-03-15", 1, "official"), ("8299", "TWO", "2018-03-15", 5, "official")])
    tsd = _df([("2330", "TW", "2018-03-15", 100, "tw-stock-data"), ("1808", "TW", "2018-03-15", 714, "tw-stock-data"),
               ("8299", "TWO", "2018-03-15", 5, "tw-stock-data")])
    r = ss.compare(off, tsd).set_index("market")
    assert r.loc["TW", "n_official"] == 3 and r.loc["TW", "n_tsd"] == 2
    assert r.loc["TW", "n_both"] == 2 and r.loc["TW", "n_equal"] == 1 and r.loc["TW", "ratio"] == pytest.approx(0.5)
    assert r.loc["TWO", "ratio"] == pytest.approx(1.0)


# ───────── 下游查詢 ─────────
def test_shares_asof_取最後一筆且過期不回():
    s = _df([("2330", "TW", "2026-10-01", 1, "official"), ("2330", "TW", "2026-11-05", 2, "official"),
             ("2330", "TW", "2026-11-10", 3, "official"),                     # 晚於查詢日，不可看見
             ("1589", "TW", "2026-04-01", 9, "official")])                    # 停牌太久
    r = ss.shares_asof(s, date(2026, 11, 6))
    assert r.set_index("ticker")["issued_shares"].to_dict() == {"2330": 2}
    assert r.loc[r["ticker"] == "2330", "obs_date"].iloc[0] == pd.Timestamp("2026-11-05")


# ───────── 寫檔守門 ─────────
def test_write_主鍵重複或股數非正不寫(tmp_path):
    out = tmp_path / "shares.parquet"
    dup = _df([("2330", "TW", "2026-11-06", 1, "official"), ("2330", "TW", "2026-11-06", 2, "official")])
    with pytest.raises(ValueError):
        ss.write(dup, out)
    bad = _df([("2330", "TW", "2026-11-06", 1, "official")]).assign(issued_shares=0)
    with pytest.raises(ValueError):
        ss.write(bad, out)
    assert not out.exists()
    ok = _df([("2330", "TW", "2026-11-06", 1, "official")])
    ss.write(ok, out)
    assert pd.read_parquet(out)["issued_shares"].tolist() == [1]


# ───────── CLI ─────────
def test_main_import_tsd只補缺的主鍵(tmp_path, monkeypatch):
    out = tmp_path / "shares.parquet"
    monkeypatch.setattr(ss, "OUT", out)
    ss.write(_df([("2330", "TW", "2026-11-06", 999, "official")]), out)
    assert ss.main(["--import-tsd", str(_tsd_tree(tmp_path))]) == 0
    df = pd.read_parquet(out)
    assert len(df) == 4
    r = df[(df["ticker"] == "2330") & (df["date"] == pd.Timestamp("2026-11-06"))]
    assert r["issued_shares"].tolist() == [999] and r["src"].tolist() == ["official"]


def test_main_收集只抓缺official的交易日(tmp_path, monkeypatch):
    out, rp = tmp_path / "shares.parquet", tmp_path / "raw_prices.parquet"
    monkeypatch.setattr(ss, "OUT", out)
    monkeypatch.setattr(ss, "RAW_PRICES", rp)
    pd.DataFrame({"ticker": ["2330"] * 3, "market": ["TW"] * 3,
                  "date": pd.to_datetime(["2026-11-04", "2026-11-05", "2026-11-06"])}).to_parquet(rp)
    ss.write(_df([("2330", "TW", "2026-11-04", 1, "official"), ("2330", "TW", "2026-11-05", 1, "tw-stock-data")]), out)
    asked = []

    def fake(d):
        asked.append(d)
        return _df([("2330", "TW", d.isoformat(), 7, "official")])
    monkeypatch.setattr(ss, "fetch_day", fake)
    assert ss.main(["--start", "2026-11-01", "--end", "2026-11-06"]) == 0
    assert asked == [date(2026, 11, 5), date(2026, 11, 6)]
    df = pd.read_parquet(out).set_index("date")
    assert df.loc[pd.Timestamp("2026-11-05"), "src"] == "official"
    assert df.loc[pd.Timestamp("2026-11-05"), "issued_shares"] == 7


def test_main_收集有失敗日exit1但成功的照寫(tmp_path, monkeypatch):
    out, rp = tmp_path / "shares.parquet", tmp_path / "raw_prices.parquet"
    monkeypatch.setattr(ss, "OUT", out)
    monkeypatch.setattr(ss, "RAW_PRICES", rp)
    pd.DataFrame({"ticker": ["2330"] * 2, "market": ["TW"] * 2,
                  "date": pd.to_datetime(["2026-11-05", "2026-11-06"])}).to_parquet(rp)
    monkeypatch.setattr(ss, "fetch_day", lambda d: None if d.day == 6
                        else _df([("2330", "TW", d.isoformat(), 7, "official")]))
    assert ss.main(["--start", "2026-11-01", "--end", "2026-11-06"]) == 1
    assert pd.read_parquet(out)["date"].tolist() == [pd.Timestamp("2026-11-05")]


def test_gate_納入shares資料集():
    import selfhost_gate as g
    assert g.DATASETS["shares"] == "shares.parquet"
    assert "shares" in g.DAILY
    assert g.ABS_MIN["shares"] == {"TW": 900, "TWO": 700}
