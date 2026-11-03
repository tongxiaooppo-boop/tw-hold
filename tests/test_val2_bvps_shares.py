import numpy as np
import pandas as pd
import pytest

from reference import share_basis as sb
from screener import multiples_self as ms
from screener import val_card as vc
from test_val2_multiples import q_fixture
from test_val2_eps_windows import make_monthly


T = pd.Timestamp


@pytest.fixture(autouse=True)
def no_events(monkeypatch):
    monkeypatch.setattr(sb, "events", lambda ticker: [])


def test_shares_today_basis_一般():
    assert sb.shares_today_basis("2303", 1257e8, T("2026-09-30"), 10, None) == pytest.approx(125.7e8)


def test_shares_today_basis_面額變更(monkeypatch):
    monkeypatch.setattr(sb, "events", lambda ticker: [dict(date=T("2026-10-01"), type="par_change", m=4)])
    assert sb.shares_today_basis("2303", 1257e8, T("2026-09-30"), 2.5, None) == pytest.approx(1257e8 / 2.5)


def test_shares_today_basis_配股(monkeypatch):
    monkeypatch.setattr(sb, "events", lambda ticker: [dict(date=T("2026-10-01"), type="stock_dividend", m=1.1)])
    assert sb.shares_today_basis("2303", 1257e8, T("2026-09-30"), 10, None) == pytest.approx(125.7e8 * 1.1)


def test_shares_today_basis_扣特別股():
    assert sb.shares_today_basis("2303", 1000, T("2026-09-30"), 10, 20) == 80


@pytest.mark.parametrize("capital", [None, np.nan, np.inf, 0, -1])
def test_shares_today_basis_缺股本_None(capital):
    assert sb.shares_today_basis("2303", capital, T("2026-09-30"), 10, None) is None


def umc():
    return pd.DataFrame([dict(period_end=T("2026-09-30"), equity_parent=4709.17e8,
                              capital_stock=1257.01e8, ni_parent=748.65e8, eps=1.32)])


def test_bvps_live_用股本_官方股數與累計淨利都不影響():
    # 即時也先用同季股本：官方 issued_shares 是今天的股數，會因可轉債轉換等不在事件表的變動漂移
    basic = dict(issued_shares=60e8, par_value=10, preferred_shares=1e8, asof="2020-01-01")
    assert vc.bvps_live(umc(), "2303", basic) == pytest.approx((4709.17e8 - 1e8 * 10) / (125.701e8 - 1e8))


def test_bvps_live_沒股本_退回官方股數():
    basic = dict(issued_shares=125.70e8, par_value=10, preferred_shares=1e8, asof="2020-01-01")
    q = umc().drop(columns="capital_stock")
    assert vc.bvps_live(q, "2303", basic) == pytest.approx((4709.17e8 - 1e8 * 10) / 125.70e8)


def test_bvps_live_沒basic_用股本():
    assert vc.bvps_live(umc(), "2303") == pytest.approx(4709.17 / 125.701)


def test_bvps_live_沒股本也沒basic_退回反推():
    assert vc.bvps_live(umc().drop(columns="capital_stock"), "2303") == pytest.approx(4709.17 / (748.65 / 1.32))


def test_build_history_bvps_用股本_且有來源欄():
    q = q_fixture()
    q["capital_stock"] = 2000.0
    closes = pd.DataFrame([dict(month="2026-10", date=T("2026-10-30"), close=38.4)])
    monthly = make_monthly("2026-09", first="2019-01")
    basic = dict(par_value=10, preferred_shares=0, issued_shares=99999)
    mh = ms.build_history("9999", q, monthly, closes, None, basic=basic)
    assert mh.iloc[0].bvps == pytest.approx(5)
    assert mh.iloc[0].bvps_src == "capital"
    assert mh.columns[-1] == "bvps_src"
    mh = ms.build_history("9999", q.drop(columns="capital_stock"), monthly, closes, None, basic=basic)
    assert mh.iloc[0].bvps == pytest.approx(10)
    assert mh.iloc[0].bvps_src == "reverse"

def share_quarters(values):
    return pd.DataFrame([dict(period_end=d, capital_stock=1000, equity_parent=2000,
                              eps=1., ni_parent=v) for d, v in
                         zip(pd.date_range('2025-12-31', periods=len(values), freq='QE'), values)])


def exchange(q, ratio, start='2026-08-14', n=5):
    return pd.DataFrame(dict(date=pd.date_range(start, periods=n), close=20/ratio, pbr=1.))


@pytest.mark.parametrize('ratio,expected', [(.97,'treasury'),(.97001,'capital'),(.5,'treasury'),(.4999,'capital'),(1.,'capital'),(.815,'treasury')])
def test_treasury_boundaries(ratio, expected):
    q = share_quarters([80,80,80])
    ex = exchange(q, ratio)
    shares, src = sb.common_shares('x', q.iloc[-1], q, exch=ex, upto=T('2026-08-30'))
    assert src == expected
    assert shares == pytest.approx(100*ratio if expected=='treasury' else 100)


def test_ratio_event_cutoff_and_five_days(monkeypatch):
    q=share_quarters([80,80,80]); ex=exchange(q,.8,n=6)
    monkeypatch.setattr(sb,'events',lambda t:[dict(date=T('2026-08-18'),type='ex_both',m=1.1)])
    assert sb.exchange_outstanding_ratio('x',q,ex,T('2026-08-30')) is None
    monkeypatch.setattr(sb,'events',lambda t:[dict(date=T('2026-08-19'),type='ex_both',m=1.1)])
    assert sb.exchange_outstanding_ratio('x',q,ex,T('2026-08-30')) == pytest.approx(.8)
    assert sb.exchange_outstanding_ratio('x',q,ex.iloc[:4],T('2026-08-30')) is None


def test_ratio_upto_no_lookahead():
    q=share_quarters([80,80,80]); ex=exchange(q,.8,n=5)
    later=exchange(q,.6,start='2026-08-25',n=20)
    assert sb.exchange_outstanding_ratio('x',q,pd.concat([ex,later]),T('2026-08-20')) == pytest.approx(.8)
    assert sb.exchange_outstanding_ratio('x',q,ex,T('2026-08-17')) is None


def test_single_cumulative_spike_is_not_treasury():
    q = share_quarters([80, 80, 80, 80*4.5])
    assert sb.common_shares('x', q.iloc[-1], q) == (100, 'capital')


def test_one_reverse_observation_is_not_treasury():
    q = share_quarters([80])
    assert sb.common_shares('x', q.iloc[-1], q) == (100, 'capital')


def test_missing_par_uses_paid_in_capital_and_live_issued():
    q = share_quarters([80, 80])
    basic = dict(par_value=np.nan, paid_in_capital=1000, issued_shares=400, preferred_shares=0)
    assert sb.common_par_today(basic) == 2.5
    assert sb.common_shares('x', q.iloc[-1], q, basic) == (400, 'capital')
    assert sb.common_shares('x', q.iloc[-1], q, basic, live=True) == (400, 'capital')
    nocap = q.drop(columns='capital_stock')
    assert sb.common_shares('x', nocap.iloc[-1], nocap, basic, live=True) == (400, 'official')
    assert vc.bvps_live(q, 'x', basic) == 5
    assert sb.common_par_today(dict(basic, preferred_shares=20)) == pytest.approx(1000/420)
    assert sb.common_par_today(dict(basic, issued_shares=np.nan, preferred_shares=20)) == 10


def test_preferred_equity_and_invalid_common_equity():
    q = share_quarters([100])
    basic = dict(par_value=10, issued_shares=100, preferred_shares=20)
    assert vc.bvps_live(q, 'x', basic) == pytest.approx((2000 - 20 * 10) / (1000 / 10 - 20))
    assert sb.common_equity('x', q.iloc[-1], dict(preferred_shares=200)) is None


def test_live_and_history_use_common_function(monkeypatch):
    calls = []
    def choose(*args, **kwargs):
        live = kwargs.get('live', False)
        calls.append(live)
        expected = T('2026-09-30') if live else T('2026-06-30')
        assert args[1]['period_end'] == expected
        assert args[2]['period_end'].max() == expected
        return 100, 'treasury'
    monkeypatch.setattr(sb, 'common_shares', choose)
    q = q_fixture()
    future = q.iloc[[-1]].copy()
    future['period_end'] = T('2026-09-30')
    q = pd.concat([q, future], ignore_index=True)
    assert vc.bvps_live(q, '9999') is not None
    closes = pd.DataFrame([dict(month='2026-10', date=T('2026-10-30'), close=38.4)])
    mh = ms.build_history('9999', q, make_monthly('2026-09', first='2019-01'), closes, None)
    assert mh.iloc[0].bvps_src == 'treasury'
    assert calls == [True, False]


def test_par_factor_uses_today_basis(monkeypatch):
    monkeypatch.setattr(sb, 'events', lambda ticker: [
        dict(date=T('2026-10-01'), type='par_change', m=4),
        dict(date=T('2026-10-02'), type='ex_rights', m=1.1)])
    assert sb.share_factor_after('x', T('2026-09-30')) == pytest.approx(4.4)
    assert sb.shares_today_basis('x', 1000, T('2026-09-30'), 2.5, 0) == pytest.approx(440)

def test_2327_par_change_history_today_basis(monkeypatch):
    monkeypatch.setattr(sb,'events',lambda t:[dict(date=T('2026-08-01'),type='par_change',m=4)])
    q=q_fixture();q['capital_stock']=2000.
    closes=pd.DataFrame([dict(month='2026-10',date=T('2026-10-30'),close=40.)])
    h=ms.build_history('2327',q,make_monthly('2026-09',first='2019-01'),closes,None,basic=dict(par_value=2.5))
    assert h.iloc[0].bvps == pytest.approx(1000/(2000/10*4))


def test_exchange_metadata_preferred_and_par():
    q=share_quarters([80,80,80]);q.attrs['basic']=dict(par_value=2.5,preferred_shares=20)
    # Common equity 1950; capital common shares 380; ratio .8.
    ex=pd.DataFrame(dict(date=pd.date_range('2026-08-14',periods=5),close=1950/(380*.8),pbr=1.))
    assert sb.exchange_outstanding_ratio('x',q,ex,T('2026-08-30')) == pytest.approx(.8)


def test_exchange_newest_insufficient_uses_prior_visible_quarter():
    q=share_quarters([80,80,80,80])
    ex=pd.concat([exchange(q,.8),exchange(q,.6,start='2026-11-14',n=4)])
    assert sb.exchange_outstanding_ratio('x',q,ex,T('2026-11-18')) == pytest.approx(.8)
    # June observation window ends at September visibility; later days cannot pad it.
    ex=exchange(q,.8,start='2026-11-14',n=4)
    assert sb.exchange_outstanding_ratio('x',q,ex,T('2026-11-18')) is None
