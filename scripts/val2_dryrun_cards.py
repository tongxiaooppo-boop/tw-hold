"""只讀本機資料及既有倍數，逐檔建立新舊卡與乾跑報告。"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from reference import corporate_actions as ca, loader
from screener import val_card

ASOF = pd.Timestamp("2026-11-02")


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def dump(path, value):
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2,
                               allow_nan=False), encoding="utf-8")


def grouped(frame, order):
    frame = frame.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.split(".").str[0]
    return {code: rows.sort_values(order).reset_index(drop=True)
            for code, rows in frame.groupby("ticker", sort=False)}


def load_inputs(with_history=True):
    # 新舊卡共用已調整 EPS 的面板；只將日線裁至評價日，財報採 live=True。
    stocks = json.loads((ROOT / "data/derived/stock_class.json").read_text(encoding="utf-8"))["stocks"]
    data = dict(stocks=stocks, q=grouped(ca.adjust_eps(loader.load_quarterly(live=True)), "period_end"))
    for key, file, order in [("rev", "revenue", "month"),
                              ("px", "prices_raw_close", "date"), ("per", "per", "date")]:
        frame = pd.read_parquet(ROOT / f"data/upstream/{file}.parquet")
        if order == "date":
            frame = frame[pd.to_datetime(frame["date"]) <= ASOF]
        data[key] = grouped(frame, order)
    if with_history:
        for key, file in [("mh", "multiples_hist"), ("rev_hist", "eps_revision")]:
            data[key] = grouped(pd.read_parquet(ROOT / f"_dryrun/{file}.parquet"), "month")
        industry = json.loads((ROOT / "_dryrun/industry_pe.json").read_text(encoding="utf-8"))
        if industry["asof"] != str(ASOF.date()) or not all("values" in v for v in industry["industries"].values()):
            raise ValueError("倍數產物日期不符或缺少 values，請先完成指定重建")
        data["industry_pe"] = industry["industries"]
    return data


def table(headers, rows):
    def cell(v):
        return str(v).replace("|", "\\|").replace("\n", " ") if v is not None else "—"
    return "\n" + "\n".join(["| " + " | ".join(map(cell, headers)) + " |",
                       "| " + " | ".join(["---"] * len(headers)) + " |"] +
                      ["| " + " | ".join(map(cell, row)) + " |" for row in rows]) + "\n"


def report(data, cards, meta, old, old_meta):
    classes = {str(c["ticker"]): c for c in data["stocks"]}
    counts = Counter(c["tier"] for c in cards.values())
    lines = ["# 估值 2.0 P3a 全母體乾跑", "", f"評價日：{ASOF.date()}；母體：{len(classes)} 檔。",
             f"新卡：{meta['started']} ～ {meta['ended']}，{meta['seconds']:.2f} 秒；成功 {len(cards)}，例外 {len(meta['errors'])}。",
             f"舊卡：{old_meta['started']} ～ {old_meta['ended']}，{old_meta['seconds']:.2f} 秒；成功 {len(old)}，例外 {len(old_meta['errors'])}。",
             "新卡計時含共用資料載入；舊卡計時含舊引擎擷取與逐檔計算，不重複計入資料載入。",
             "", "口徑：依 stocks 原始順序；同一份 live 季報調整 EPS 一次，日線與 PER 排序並裁至評價日。位置比較納入 na（引擎回傳位置）；舊有價嚴格依 no_price is None，不額外以 fair 篩選。例外不列入卡片統計。前瞻三價可用指 cheap／fair／dear 都非空；cap=50 以主三價計算。estimate stop 原因依 items.name 分組，一檔在同一原因只計一次，可跨原因重複；另列原始 why 前三名供追溯。", "", "## 例外"]
    for label, run in [("新卡", meta), ("舊卡", old_meta)]:
        lines += [f"{label}：{len(run['errors'])} 檔。", table(["ticker", "錯誤"], [(e['ticker'], e['error']) for e in run['errors']]), ""]
    lines += ["## 分層與路線", table(["tier", "檔數"], [(t, counts[t]) for t in "ABCD"]), "",
              table(["A 路線", "檔數"], Counter(c['route'] for c in cards.values() if c['tier']=='A').items()), "",
              table(["D reason", "檔數"], Counter(c['reason'] for c in cards.values() if c['tier']=='D').most_common()), "",
              table(["route", "檔數"], Counter(c['route'] for c in cards.values()).items()), ""]
    feature = Counter({'前瞻三價可用': 0})
    for c in cards.values():
        if c['fwd_prices'] and all(c['fwd_prices'].get(k) is not None for k in ['cheap','fair','dear']): feature['前瞻三價可用'] += 1
        for name, note in [('NOTE_FWD_SAME', val_card.NOTE_FWD_SAME), ('NOTE_CAP_FLAT', val_card.NOTE_CAP_FLAT)]:
            feature[name] += note in c['notes']
        for state in ['normal','fwd_up']:
            feature['buy_range '+state] += (c['buy_range'] or {}).get('state') == state
        feature['cap=50'] += (c['prices'] or {}).get('cap') == 50
    lines += ["## 三價與購買區間", table(['項目','檔數'], feature.items()), "", "## 可信度"]
    for group in ['data','share_basis','comparability','estimate']:
        levels = Counter(c['status'][group]['level'] for c in cards.values())
        lines += [table([group+' level','檔數'], [(level, levels[level]) for level in ['ok','unchecked','warn','stop']]), ""]
    stopped = {t:c for t,c in cards.items() if c['status']['estimate']['level']=='stop'}
    reason_names = Counter(name for c in stopped.values() for name in
                           {item['name'] for item in c['status']['estimate']['items'] if item['level']=='stop'})
    reasons = Counter(item['why'] for c in stopped.values() for item in c['status']['estimate']['items'] if item['level']=='stop')
    lines += [f"estimate stop：{len(stopped)} 檔；前 3 名原因：", table(['原因名稱','檔數'], reason_names.most_common(3)), "",
              "原始 why 前三名（保留數值、不合併百分比）：", table(['why','筆數'], reasons.most_common(3)), "",
              "share_basis stop：", table(['ticker','名稱','原因'], [(t,classes[t]['name'],c['reason']) for t,c in cards.items() if c['status']['share_basis']['level']=='stop']), "", "## 舊卡與新卡"]
    priced = {t:c for t,c in old.items() if c['no_price'] is None}
    positions = sorted({str(c['position']) for c in priced.values()})
    lines += [f"舊有價：{len(priced)} 檔；其中新卡例外 {sum(t not in cards for t in priced)} 檔。",
              table(['舊位置 → 新 tier']+list('ABCD'), [(p, *[sum(str(o['position'])==p and t in cards and cards[t]['tier']==tier for t,o in priced.items()) for tier in 'ABCD']) for p in positions]), ""]
    flips = [t for t,o in old.items() if t in cards and o['position'] and cards[t]['position'] and o['position'] != cards[t]['position']]
    cross = Counter((old[t]['position'],cards[t]['position']) for t in flips)
    lines += [f"位置翻轉：{len(flips)} 檔（兩邊都有 position 且不同，含 na）。",
              f"其中兩邊皆為 cheap／fair／dear 的翻轉：{sum(old[t]['position'] != 'na' and cards[t]['position'] != 'na' for t in flips)} 檔。",
              table(['舊位置','新位置','檔數'], [(a,b,n) for (a,b),n in sorted(cross.items())]), "",
              "### 隨機抽 20 檔翻轉（seed=7，先依 ticker 排序再抽樣）"]
    sample = random.Random(7).sample(sorted(flips), min(20,len(flips)))
    lines += [table(['ticker','名稱','舊位置','舊合理價','舊 source','新 tier','新位置','新合理價','新 base_name'],
                    [(t,classes[t]['name'],old[t]['position'],old[t]['fair'],old[t]['source'],cards[t]['tier'],cards[t]['position'],(cards[t]['prices'] or {}).get('fair'),(cards[t]['prices'] or {}).get('base_name')) for t in sample]), "", "## 指定個股完整摘要"]
    chosen = ['2330','2327','2881','2882','3211','2408','5904','3661','1815','6477','5878']
    construction = next((str(c['ticker']) for c in data['stocks'] if c['type']=='special' and 'construction' in (c.get('metrics',{}).get('special_triggers') or [])), None)
    loss = next((t for t,c in cards.items() if c['tier']=='C'), None)
    lines += [f"第一檔營建：{construction}；第一檔 C：{loss}。", ""]
    for t in dict.fromkeys(chosen + [x for x in [construction,loss] if x]):
        lines += [f"### {t} {classes.get(t,{}).get('name','')}", ""]
        if t not in cards:
            lines += ['無卡片（請見例外表）。','']; continue
        c = cards[t]
        summary = {k:c.get(k) for k in ['tier','route','reason','price','prices','fwd_prices','buy_range','revision','b_tier','c_tier','roe','eps_3y_avg']}
        summary['status'] = {g:dict(level=s['level'], items=[i['name'] for i in s['items']]) for g,s in c['status'].items()}
        summary['growth'] = [dict(key=row['key'], period=row['period'],
                                  rev_text=(row.get('rev') or {}).get('text'),
                                  eps_text=(row.get('eps') or {}).get('text'))
                             for row in c['growth']]
        lines += ['```json',json.dumps(clean(summary),ensure_ascii=False,indent=2),'```','']
    lines += ['## 執行驗證', '']
    for label, file in [('倍數重建', 'rebuild_run.json'), ('全套 pytest', 'pytest_result.json')]:
        path = ROOT / '_dryrun' / file
        if path.exists():
            lines += [label, '```json', path.read_text(encoding='utf-8'), '```', '']
    check = json.loads((ROOT / '_dryrun/multiples_check.json').read_text(encoding='utf-8'))
    lines += [f"倍數母體 {check['n_tickers']}；成功 {check['n_ok']}；失敗 {check['n_failed']}。", '']
    text = '\n'.join(lines)
    # 標題前後保留空行，確保 Markdown 顯示穩定。
    formatted = []
    for line in text.splitlines():
        if line.startswith('#'):
            if formatted and formatted[-1] != '':
                formatted.append('')
            formatted.extend([line, ''])
        else:
            formatted.append(line)
    (ROOT / 'val2_card_dryrun_out.md').write_text('\n'.join(formatted),encoding='utf-8')


def main():
    started, clock = timestamp(), time.perf_counter()
    data = load_inputs()
    cards, errors = {}, []
    for index, cls in enumerate(data['stocks'], 1):
        code = str(cls['ticker'])
        try:
            cards[code] = val_card.build_card(data['q'].get(code), data['rev'].get(code),
                data['px'].get(code), cls, data['mh'].get(code), data['rev_hist'].get(code), data['industry_pe'], ASOF)
        except Exception as exc:
            errors.append(dict(ticker=code,error=f'{type(exc).__name__}: {exc}'))
        if index % 100 == 0: print(f'新卡 {index}/{len(data["stocks"])}',flush=True)
    meta = dict(started=started,ended=timestamp(),seconds=time.perf_counter()-clock,n_stocks=len(data['stocks']),errors=errors)
    dump(ROOT / '_dryrun/new_cards.json',cards)
    dump(ROOT / '_dryrun/new_run.json',meta)
    from val2_old_cards import run
    old, old_meta = run(data)
    report(data,cards,meta,old,old_meta)
    print(json.dumps(dict(new=meta,old=old_meta),ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
