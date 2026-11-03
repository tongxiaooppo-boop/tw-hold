"""只讀本機 bundle，透過共用輸入與畫面資料層驗收估值卡。"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import val_inputs, val_view
from screener import val_card, river
ASOF = pd.Timestamp('2026-11-02')
CHOSEN = ('2330', '2327', '2881', '5289', '1815', '2317', '2454', '6505', '2603', '2002', '1101', '3008')


class LocalBundle:
    """只讀 clone 上游資料，依代號快取，沒有下載或寫入。"""
    def __init__(self):
        self.frames = {}

    def read(self, name, code):
        if name not in self.frames:
            path = ROOT / 'data/upstream' / (name + '.parquet')
            if name == 'per' and (ROOT / 'data/upstream/fundamentals/per.parquet').exists():
                path = ROOT / 'data/upstream/fundamentals/per.parquet'
            if name in ('income', 'balance', 'cashflow', 'per') and not path.exists():
                path = ROOT / 'data/upstream/fundamentals' / (name + '.parquet')
            if name == 'per' and not path.exists():
                return pd.DataFrame(columns=['date', 'pbr'])
            frame = pd.read_parquet(path)
            frame['ticker'] = frame['ticker'].astype(str).str.split('.').str[0]
            self.frames[name] = {str(t): f.reset_index(drop=True) for t, f in frame.groupby('ticker', sort=False)}
            self.frames[name][None] = frame.iloc[:0]
        return self.frames[name].get(str(code), self.frames[name][None]).copy()

    def company_basic(self, code):
        path = ROOT / 'data/upstream/company_basic.parquet'
        if not path.exists():
            return None
        try:
            rows = self.read('company_basic', code)
            if rows.empty:
                return None
            r = rows.iloc[0]
            return {**{k: float(r.get(k, float('nan'))) for k in
                       ('par_value', 'issued_shares', 'preferred_shares', 'paid_in_capital')}, 'asof': pd.Timestamp(r.get('asof'))}
        except Exception:
            return None


def table(headers, rows):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', '<br>') if value is not None else '—'
    return '\n'.join(['| ' + ' | '.join(map(cell, headers)) + ' |',
                      '| ' + ' | '.join('---' for _ in headers) + ' |'] +
                     ['| ' + ' | '.join(map(cell, row)) + ' |' for row in rows])


def text_value(value):
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, tuple, list)) else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--derived', type=Path, default=ROOT / '_dryrun')
    parser.add_argument('--out', type=Path, default=None, help='輸出目錄；未指定時維持原路徑')
    parser.add_argument('--asof', default=None, help='評價日；預設取倍數產物 industry_pe.json 的 asof')
    args = parser.parse_args()
    global ASOF
    industry = json.loads((args.derived / val_inputs.IND_FILE).read_text(encoding='utf-8'))
    ASOF = pd.Timestamp(args.asof or industry['asof'])
    industry = json.loads((args.derived / val_inputs.IND_FILE).read_text(encoding='utf-8'))
    if industry['asof'] != str(ASOF.date()) or not all('values' in v for v in industry['industries'].values()):
        raise ValueError('倍數產物日期不符或缺少 values，請先完成指定重建')
    meta = json.loads((ROOT / 'data/derived/stock_class.json').read_text(encoding='utf-8'))
    stocks = {str(c['ticker']): c for c in meta['stocks']}
    bundle = LocalBundle()
    cards, views, inputs, errors = {}, {}, {}, []
    tiers, tri_notes, fwd_notes, pin_counts = Counter(), Counter(), Counter(), Counter()
    started = time.perf_counter()
    for index, (code, cls) in enumerate(stocks.items(), 1):
        try:
            kw = val_inputs.card_inputs(code, ASOF, cls, args.derived, bundle)
            if 'missing' in kw:
                raise ValueError(kw['missing'])
            card = val_card.build_card(**kw)
            view = val_view.card_view(card, f"{code} {cls.get('name', '')}", meta)
            pinned = []
            for fn in (val_view.detail_tables, val_view.explain_tables, val_view.trial_tables):
                for t in fn(card):
                    assert all(isinstance(cell, str) for row in t.rows for cell in row)
                    pinned.extend(row for row in t.rows if any(cell.startswith(val_view.PIN) for cell in row))
            for label, value in view.pins.items():
                hit = [row for row in pinned if any(cell.startswith(f"＝卡片『{label}』") for cell in row)]
                assert len(hit) == 1 and any(cell == val_view.PIN + ' ' + value for cell in hit[0]), label
            assert len(pinned) == len(view.pins)
            cards[code], views[code] = card, view
            tiers[card['tier']] += 1
            tri_notes[view.price.tri_note] += 1
            fwd_notes[view.price.fwd_note] += 1
            pin_counts[len(view.pins)] += 1
            if code in CHOSEN or (card['tier'] == 'B' and not any(cards[t]['tier'] == 'B' for t in inputs)):
                inputs[code] = kw
        except Exception as exc:
            errors.append((code, f'{type(exc).__name__}: {exc}'))
        if index % 100 == 0:
            print(f'畫面 {index}/{len(stocks)}；例外 {len(errors)}', flush=True)
    lines = ['# P4a 畫面資料層乾跑', '', f'評價日：{ASOF.date()}；母體 {len(stocks)} 檔；成功 {len(views)}；例外 {len(errors)}。',
             f'耗時 {time.perf_counter() - started:.1f} 秒；倍數目錄 {args.derived}。', '',
             '## 全市場統計', '', table(('tier', '檔數'), sorted(tiers.items())), '',
             '### tri_note（含無短句）', '', table(('文字', '次數'), tri_notes.most_common()), '',
             '### fwd_note（卡片顯示；非 A 層為空）', '', table(('文字', '次數'), fwd_notes.most_common()), '',
             '### pins 數量分布', '', table(('數量', '檔數'), sorted(pin_counts.items())), '',
             '## 例外', '', table(('代號', '錯誤'), errors) if errors else '0 例外。', '',
             '## 指定 12 檔', '', '2330、2327 列結構依 card_demo.html；資料日不同，數字以本 clone 為準。', '']
    for code in CHOSEN:
        lines.extend([f"### {code} {stocks.get(code, {}).get('name', '')}", ''])
        if code not in views:
            lines.extend(['未產生畫面，見例外。', ''])
            continue
        card, view = cards[code], views[code]
        lines.extend([f"tier={card['tier']}；route={card['route']}；{view.coverage}；{view.asof_line}", '',
                      '#### 股價卡', '', table(('欄位', '內容'), [(k, text_value(v)) for k, v in asdict(view.price).items()]), '',
                      '#### EPS 卡', '', table(('標題', '副標', '數值'), view.eps.kv) if view.eps else '未顯示 EPS 卡。', ''])
        if view.eps:
            lines.extend([view.eps.growth_label, '', table(view.eps.growth_table.headers, view.eps.growth_table.rows), ''])
        lines.extend(['#### 🔍 試算細節', '', val_view.legend_row(), ''])
        for t in val_view.trial_tables(card):
            lines.extend([f'**{t.title}**', '', table(t.headers, t.rows), '', f'底色列（從 0 起）：{t.hl}', ''])
    b_code = next((code for code in inputs if cards[code]['tier'] == 'B'), None)
    lines.extend(['## 河流圖', ''])
    for code in dict.fromkeys(['2330', '2881', b_code]):
        if code is None or code not in cards:
            continue
        kw = inputs[code]
        try:
            result = river.river_frame(kw['qf'], kw['px'], kw['mh'], cards[code], code, ASOF)
            lines.extend([f"### {code}（{cards[code]['tier']} 層）", '',
                          f"metric={result['metric']}；mults={result['mults']}；note={result['note']}；reason={result['reason']}。", '',
                          table(tuple(result['frame'].columns), result['frame'].tail(3).itertuples(index=False, name=None)), ''])
        except Exception as exc:
            errors.append((code, f'river {type(exc).__name__}: {exc}'))
            lines.extend([f'河流圖 {code} 例外：{exc}', ''])
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
    views_path = args.out / 'p4a_views.md' if args.out is not None else ROOT / 'p4a_views.md'
    summary_path = args.out / 'p4a_summary.json' if args.out is not None else ROOT / '_dryrun/p4a_summary.json'
    views_path.write_text('\n'.join(lines), encoding='utf-8')
    summary = dict(n_stocks=len(stocks), n_ok=len(views), errors=errors, tiers=dict(tiers),
                   tri_notes=dict(tri_notes), fwd_notes=dict(fwd_notes), pins=dict(pin_counts))
    # summarize 只保留非正常明細；沒有該項明細即為 ok。
    summary['share_checks'] = {name: dict(Counter(next((item['level']
        for item in card['status']['share_basis']['items'] if item['name'] == name), 'ok')
        for card in cards.values()))
        for name in ('面額與特別股', '股數對不上')}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if errors or any(code not in views for code in CHOSEN):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
