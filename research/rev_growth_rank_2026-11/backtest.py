from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent / 'out'

def main():
    OUT.mkdir(exist_ok=True)
    r = pd.read_parquet(ROOT/'data/upstream/revenue.parquet')
    b = pd.read_parquet(ROOT/'data/upstream/company_basic.parquet')
    p = pd.read_parquet(ROOT/'data/upstream/prices_raw_close.parquet')
    industry = pd.read_parquet(ROOT/'data/upstream/fundamentals/universe.parquet', columns=['ticker','industry'])
    assert not industry.ticker.duplicated().any()
    industry = industry.set_index('ticker').industry
    construction = set(industry[industry.eq('\u5efa\u6750\u71df\u9020')].index)
    assert len(construction) > 0
    assert not r.duplicated(['ticker','month']).any()
    assert not b.ticker.duplicated().any()
    p['ticker'] = p.ticker.str.replace(r'\.(TW|TWO)$','',regex=True)
    p = p[p.ticker.isin(b.ticker) & p.close.gt(0)].copy()
    p['period'] = p.date.dt.to_period('M')
    prices = p.sort_values('date').groupby(['period','ticker']).tail(1)
    rev = r.pivot(index='month',columns='ticker',values='revenue')
    rev.index = pd.PeriodIndex(rev.index,freq='M')
    rev = rev.reindex(pd.period_range(rev.index.min(),rev.index.max(),freq='M'))
    rev = rev.where(np.isfinite(rev) & rev.ge(0))
    prior = rev.shift(12)
    yoy = rev/prior.where(prior.gt(0))-1
    mom = rev/rev.shift().where(rev.shift().gt(0))-1
    hist = [mom.shift(i*12) for i in (1,2,3)]
    count = sum(x.notna().astype(int) for x in hist)
    avg = sum(x.fillna(0) for x in hist)/count.where(count.ge(2))
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        med = pd.DataFrame(np.nanmedian(np.stack([x.to_numpy() for x in hist]),axis=0),index=rev.index,columns=rev.columns).where(count.ge(2))
    ann = r.pivot(index='month',columns='ticker',values='announced')
    ann.index = pd.PeriodIndex(ann.index,freq='M')
    shares = b.set_index('ticker').issued_shares
    rows, previous = [], {}
    for mo in pd.period_range('2019-01',rev.index.max(),freq='M'):
        px = prices[prices.period.eq(mo-1)].set_index('ticker').close
        cap = (px*shares).dropna().loc[lambda x:x.gt(0)].sort_values(ascending=False,kind='stable').head(500)
        f = pd.DataFrame({'cap':cap,'yoy':yoy.loc[mo].reindex(cap.index),'mom':mom.loc[mo].reindex(cap.index),'prior':prior.loc[mo].reindex(cap.index),'avg':avg.loc[mo].reindex(cap.index),'med':med.loc[mo].reindex(cap.index),'ann':ann.loc[mo].reindex(cap.index)})
        original = f.copy()
        base = f[f.yoy.gt(0) & f.prior.ge(1e8)].sort_values('yoy',ascending=False,kind='stable')
        masks = {'YoY':pd.Series(True,index=f.index),'M1':f.mom.gt(0),'M2':f.mom.gt(f.avg),'M3':f.mom.gt(f.med)}
        for name, mask in masks.items():
            for scope in ['incl','excl']:
                f = original if scope == 'incl' else original.loc[~original.index.isin(construction)]
                mask = masks[name].reindex(f.index)
                base = f[f.yoy.gt(0) & f.prior.ge(1e8)].sort_values('yoy',ascending=False,kind='stable')
                valid = len(cap)==500
                row = dict(month=str(mo),calendar_month=mo.month,definition=name,scope=scope,status='ok' if valid else 'price_missing',universe_n=len(f),original_universe_n=len(cap),industry_unknown_n=int(industry.reindex(f.index).isna().sum()),eligible_n=len(base))
                fields = ['removed_universe','removed_eligible','removed_top30','overlap','construction','top_n','missing_reference']
                fields += [f'd{day}_{k}' for day in (3,5,7,10) for k in ['overlap','published','cap_pub','cap_unpub','yoy_pub','yoy_unpub','unknown']]
                row.update({k:np.nan for k in fields})
                if valid:
                    ranked = base.loc[mask.reindex(base.index)].head(30)
                    top = set(ranked.index)
                    row.update(removed_universe=(~mask).mean(),removed_eligible=(~mask.reindex(base.index)).mean(),removed_top30=(~mask.reindex(base.head(30).index)).mean(),top_n=len(top),missing_reference=f['avg' if name=='M2' else 'med' if name=='M3' else 'mom'].isna().mean() if name!='YoY' else 0)
                    row['construction'] = sum(ticker in construction for ticker in top)
                    key_previous = (name, scope)
                    if key_previous in previous and previous[key_previous][0]==mo-1:
                        row['overlap'] = len(top & previous[key_previous][1])
                    previous[key_previous] = (mo,top)
                    known = f.ann.notna()
                    plausible = not f.loc[known,'ann'].lt((mo+1).to_timestamp()).any()
                    for day in (3,5,7,10):
                        cutoff = (mo+1).to_timestamp()+pd.Timedelta(days=day-1)
                        pub = known & f.ann.dt.normalize().le(cutoff)
                        key = f'd{day}_'
                        row[key+'published'] = pub.mean()
                        row[key+'unknown'] = (~known).mean()
                        for col in ['cap','yoy']:
                            row[key+col+'_pub'] = f.loc[pub,col].median()
                            row[key+col+'_unpub'] = f.loc[known & ~pub,col].median()
                        if known.mean()>=.95 and plausible:
                            early = base.loc[mask.reindex(base.index) & pub.reindex(base.index)].head(30)
                            row[key+'overlap'] = len(top & set(early.index))
                rows.append(row)
    detail = pd.DataFrame(rows)
    detail.to_csv(OUT/'by_month.csv',index=False,encoding='utf-8')
    metrics = ['removed_universe','removed_top30','overlap','construction']+[f'd{d}_overlap' for d in (3,5,7,10)]
    summary=[]
    for (name,scope),g in detail.groupby(['definition','scope'],sort=False):
        for metric in metrics:
            s=g[metric].dropna()
            summary.append(dict(definition=name,scope=scope,metric=metric,mean=round(s.mean(),3) if len(s) else np.nan,n=len(s)))
    pd.DataFrame(summary).to_csv(OUT/'summary.csv',index=False,encoding='utf-8')
    detail.groupby(['definition','scope','calendar_month'])[['removed_universe','removed_eligible','removed_top30','overlap','top_n','missing_reference']].mean().to_csv(OUT/'seasonality.csv',encoding='utf-8')
    audit=dict(price_start=str(p.date.min()),price_end=str(p.date.max()),revenue_end=str(rev.index.max()),industry_source='data/upstream/fundamentals/universe.parquet: ticker, industry',construction_tickers=len(construction),rules=dict(yoy='>0',prior_revenue_min=1e8,top_n=30,M2='MoM > mean of prior three same-month MoM; at least two observations',M3='MoM > median of prior three same-month MoM; at least two observations',announced_coverage_min=.95),limitations=['Current shares, raw prices and current company set bias historical universe; not point-in-time.','Current industry classification applied unchanged to all historical months. Exclusion is after top-500 selection, without replacement. Unknown industry retained and counted.','Missing dates are not late publishers; date overlap restricted to >=95% date coverage.','Historical revenue revisions and original publication timestamps cannot be verified.','No return backtest. Whole-universe filter failures include missing references; eligible-only failures also provided.'])
    (OUT/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Wrote by_month.csv, summary.csv, seasonality.csv, audit.json; industry comparison complete.')

if __name__=='__main__':
    # Round one is retained for reference; do not use its announced timestamps.
    from round2 import main as round2_main
    round2_main()
