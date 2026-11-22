"""Offline scan; raw event matching includes m=None. Percent columns use 100=100%."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
DATA = ROOT.parent / 'tw-swing/data/fundamentals'

def main():
    b = pd.read_parquet(DATA/'balance.parquet', columns=['ticker','period_end','capital_stock'])
    b['ticker'] = b.ticker.astype(str).str.split('.').str[0]
    b['period_end'] = pd.to_datetime(b.period_end)
    if b.duplicated(['ticker','period_end']).any():
        raise ValueError('Duplicate balance ticker/period_end')
    b = b.sort_values(['ticker','period_end'])
    g = b.groupby('ticker',sort=False)
    b['cap_prev'] = g.capital_stock.shift()
    b['prev_end'] = g.period_end.shift()
    start = b.period_end.dt.to_period('Q').dt.start_time
    eligible = b.period_end.ge('2021-01-01') & b.period_end.eq(b.period_end.dt.to_period('Q').dt.end_time.dt.normalize())
    valid = b.prev_end.eq(start-pd.Timedelta(days=1)) & b.cap_prev.gt(0) & b.capital_stock.ge(0) & np.isfinite(b.cap_prev) & np.isfinite(b.capital_stock)
    b['chg_pct'] = (b.capital_stock/b.cap_prev-1)*100
    jumps = b.loc[eligible & valid & b.chg_pct.abs().ge(3-1e-10)].copy()
    raw = json.loads((ROOT/'reference/corporate_actions_resolved.json').read_text(encoding='utf-8'))
    # Inspected corporate_actions.py has _MANUAL={}, so resolved events equal SPLITS.
    # Do not use _events(): it removes m=None events.
    splits = raw['events'] if 'events' in raw else raw['splits']
    evs = {str(t):[(pd.Timestamp(e['date']),e.get('type','legacy')) for e in es] for t,es in splits.items()}
    jumps['event_types'] = ['|'.join(sorted({typ for date,typ in evs.get(r.ticker,[]) if r.prev_end < date <= r.period_end})) for r in jumps.itertuples()]
    jumps['has_event'] = jumps.event_types.ne('')
    jumps = jumps.rename(columns={'capital_stock':'cap_now'})
    cols=['ticker','period_end','cap_prev','cap_now','chg_pct','has_event','event_types']
    jumps[cols].to_csv(OUT/'scan.csv',index=False,encoding='utf-8',date_format='%Y-%m-%d')
    inc=pd.read_parquet(DATA/'income.parquet',columns=['ticker','period_end','eps','equity_parent'])
    inc['ticker']=inc.ticker.astype(str).str.split('.').str[0]
    inc['period_end']=pd.to_datetime(inc.period_end)
    if inc.duplicated(['ticker','period_end']).any():
        raise ValueError('Duplicate income ticker/period_end')
    # equity_parent in this income file is parent-attributable profit, in dollars.
    # No net_income fallback: minority interests would change the numerator.
    inc['shares']=(inc.equity_parent/inc.eps).where(inc.eps.ne(0))
    inc['shares']=inc.shares.where(np.isfinite(inc.shares)&inc.shares.gt(0))
    cur=inc.rename(columns={c:c+'_now' for c in ['eps','equity_parent','shares']})
    prev=inc.rename(columns={'period_end':'prev_end',**{c:c+'_prev' for c in ['eps','equity_parent','shares']}})
    sample=jumps.loc[~jumps.has_event].assign(magnitude=lambda d:d.chg_pct.abs()).sort_values(['magnitude','ticker','period_end'],ascending=[False,True,True]).head(30)
    sample=sample.merge(cur,on=['ticker','period_end'],how='left',validate='many_to_one').merge(prev,on=['ticker','prev_end'],how='left',validate='many_to_one')
    sample['implied_chg_pct']=(sample.shares_now/sample.shares_prev-1)*100
    sample.drop(columns='magnitude').to_csv(OUT/'top30.csv',index=False,encoding='utf-8',date_format='%Y-%m-%d')
    n=b.loc[eligible,'ticker'].nunique(); a=int(jumps.has_event.sum())
    print(f'掃描 {n} 檔、跳動 {len(jumps)} 筆、有事件 {a}、無事件 {len(jumps)-a}')
    meta={'tickers':n,'jumps':len(jumps),'matched':a,'unmatched':len(jumps)-a,'unmatched_tickers':jumps.loc[~jumps.has_event,'ticker'].nunique(),
      'eligible_rows':int(eligible.sum()),'skipped_rows':int((eligible&~valid).sum()),'date_min':str(b.loc[eligible,'period_end'].min().date()),'date_max':str(b.loc[eligible,'period_end'].max().date()),
      'matched_type_combinations':jumps.loc[jumps.has_event,'event_types'].value_counts().to_dict()}
    for label,mask in [('positive',jumps.chg_pct.gt(0)),('negative',jumps.chg_pct.lt(0))]:
        meta['unmatched_'+label]=int((~jumps.has_event&mask).sum())
        meta['unmatched_'+label+'_tickers']=jumps.loc[~jumps.has_event&mask,'ticker'].nunique()
    future_any, future_close = [], []
    for r in jumps.loc[~jumps.has_event].itertuples():
        end=(r.period_end.to_period('Q')+1).end_time.normalize()
        es=[e for e in splits.get(r.ticker,[]) if r.period_end < pd.Timestamp(e['date']) <= end]
        if es:
            future_any.append(r.ticker)
        if any(e.get('m') is not None and abs(e['m']/(1+r.chg_pct/100)-1)<=.1 for e in es):
            future_close.append(r.ticker)
    meta['next_quarter_any']={'rows':len(future_any),'tickers':len(set(future_any))}
    meta['next_quarter_factor_within_10pct']={'rows':len(future_close),'tickers':len(set(future_close))}
    (OUT/'scan_summary.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':
    main()
