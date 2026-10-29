"""MOPS 月營收彙總頁：解析與「第一次看到」累積的純函式層（不連網）。"""

from __future__ import annotations

import pandas as pd

from reference import revenue_mops as rm

P = pd.Period("2026-09", freq="M")


def _row(code, name, cur, prev, ly, cum, cum_ly, note="-"):
    tds = [code, name, cur, prev, ly, "1.00", "2.00", cum, cum_ly, "3.00", note]
    return "<tr align=right>" + "".join(f"<td class='tt'>{t}</td>" for t in tds) + "</tr>"


def _page(rows, title="上市公司115年9月份(累計與當月)營業收入統計表"):
    return (f"<html><body><b>{title}</b><table>"
            "<tr><th>公司 代號</th><th>公司名稱</th></tr>"
            + "".join(rows)
            + "<tr><td>合計</td><td></td><td>1,000</td><td></td><td></td><td></td>"
              "<td></td><td></td><td></td><td></td><td></td></tr>"
            + "</table></body></html>")


def test_page_url_uses_roc_year_and_no_suffix():
    assert rm.page_url("TWSE", P).endswith("/sii/t21sc03_115_9.html")
    assert rm.page_url("TPEX", pd.Period("2026-10", freq="M")).endswith("/otc/t21sc03_115_10.html")


def test_target_period_is_previous_month():
    assert str(rm.target_period(pd.Timestamp("2026-11-03 21:43"))) == "2026-10"
    assert str(rm.target_period(pd.Timestamp("2027-01-01 07:47"))) == "2026-12"


def test_parse_page_reads_rows_converts_units_and_skips_subtotals():
    html = _page([_row("2330", "台積電", "511,857,400", "300,000", "330,980,900",
                       "4,000,000", "3,000,000", "因先進製程產品需求增加所致。"),
                  _row("1256", "鮮活果汁-KY", "561,575", "648,858", "419,697",
                       "4,477,467", "3,241,531")])
    df = rm.parse_page(html, "TWSE", P)
    assert list(df["ticker"]) == ["2330.TW", "1256.TW"]
    r = df.iloc[0]
    assert r["revenue"] == 511_857_400_000            # 千元 → 元
    assert r["revenue_last_year"] == 330_980_900_000
    assert r["note"].startswith("因先進製程")
    assert (df["period"] == "2026-09").all()


def test_parse_page_otc_suffix_and_wrong_period_rejected():
    html = _page([_row("1264", "德麥", "644,874", "574,572", "626,202", "1", "1")],
                 title="上櫃公司115年9月份(累計與當月)營業收入統計表")
    assert rm.parse_page(html, "TPEX", P)["ticker"].tolist() == ["1264.TWO"]
    # 頁面自述期別對不上 → 整頁不收
    assert rm.parse_page(html, "TPEX", pd.Period("2026-08", freq="M")).empty


def test_parse_page_empty_period_page():
    html = "<html><b>上市公司115年10月份(累計與當月)營業收入統計表</b><h3>查無資料</h3></html>"
    assert rm.parse_page(html, "TWSE", pd.Period("2026-10", freq="M")).empty


def _snap(**rev):
    return pd.DataFrame([{"ticker": t, "code": t[:4], "name": t, "market": "TWSE",
                          "period": "2026-09", "revenue": v, "revenue_prev_month": 1.0,
                          "revenue_last_year": 1.0, "revenue_cum": 1.0,
                          "revenue_cum_last_year": 1.0, "note": "-"}
                         for t, v in rev.items()])


def test_merge_seen_keeps_first_seen_and_first_values_and_flags_revision():
    t1, t2, t3 = (pd.Timestamp(x) for x in ("2026-10-03 18:47", "2026-10-05 21:43",
                                             "2026-10-06 07:47"))
    a = rm.merge_seen(None, _snap(A=10.0), t1)
    b = rm.merge_seen(a, _snap(A=10.0, B=20.0), t2)
    assert b.set_index("ticker").loc["A", "first_seen_at"] == t1
    assert b.set_index("ticker").loc["B", "first_seen_at"] == t2
    assert not b["revised"].any()

    # A 被更正、B 這次沒抓到（例如上櫃那一發失敗）→ B 保留，A 數字不覆蓋但標 revised
    c = rm.merge_seen(b, _snap(A=11.0), t3).set_index("ticker")
    assert c.loc["A", "revenue"] == 10.0
    assert bool(c.loc["A", "revised"])
    assert c.loc["A", "last_seen_at"] == t3
    assert c.loc["B", "last_seen_at"] == t2
    assert list(c.columns) == rm.COLUMNS[1:]


def test_merge_seen_with_empty_snapshot_is_noop():
    t = pd.Timestamp("2026-10-03 18:47")
    a = rm.merge_seen(None, _snap(A=10.0), t)
    empty = pd.DataFrame(columns=rm.COLUMNS[:-3])
    pd.testing.assert_frame_equal(rm.merge_seen(a, empty, t + pd.Timedelta("1h")), a)
