"""依類型的補位倍數推導（Opus 第 2 輪規則；2026-11-01）。
低＝P20、中＝sqrt(P20×P50)、高＝P50；母體＝stock_class.json 的 1019 檔分類母體；
取 2021–2025 各年「最後交易日」橫斷面 PE>0 的 P20／P50，再取 5 年中位數；
樣本少的類別按 n/(n+100) 往全體收縮（sol 反對對金融、特殊收縮，改用原始錨；見 HANDOFF A15）。
從 tw-hold/ 根目錄執行：python research/valuation_v2_experiment/multiples_by_type.py"""
import json
import numpy as np
import pandas as pd

p = pd.read_parquet('data/upstream/per.parquet', columns=['ticker', 'date', 'per'])
p['t'] = p.ticker.astype(str).str.split('.').str[0]
p['date'] = pd.to_datetime(p['date'])
cls = {x['ticker']: x['type'] for x in json.load(open('data/derived/stock_class.json', encoding='utf-8'))['stocks']}
p = p[p.t.isin(cls) & (p.per > 0)].copy()
p['type'] = p.t.map(cls)
types = ['normal', 'growth', 'cyclical', 'financial', 'special', 'insufficient']
res = {t: {'p20': [], 'p50': [], 'n': []} for t in types + ['all']}
for y in range(2021, 2026):
    d = p[p.date.dt.year == y]
    s = d[d.date == d.date.max()]
    for t in types + ['all']:
        g = s if t == 'all' else s[s.type == t]
        res[t]['p20'].append(g.per.quantile(.2))
        res[t]['p50'].append(g.per.quantile(.5))
        res[t]['n'].append(len(g))
a_all, b_all = np.median(res['all']['p20']), np.median(res['all']['p50'])
print(f'全體 P20 {a_all:.1f} P50 {b_all:.1f}')
for t in types:
    n = np.mean(res[t]['n'])
    a, b = np.median(res[t]['p20']), np.median(res[t]['p50'])
    w = n / (n + 100)
    a2, b2 = w * a + (1 - w) * a_all, w * b + (1 - w) * b_all
    print(f'{t:12s} n≈{n:4.0f} 原始 {a:.1f}/{np.sqrt(a*b):.1f}/{b:.1f}  收縮後 {a2:.1f}/{np.sqrt(a2*b2):.1f}/{b2:.1f}')
