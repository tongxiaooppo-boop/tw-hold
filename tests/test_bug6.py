"""第六批最小修正的回歸測試。"""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from app import bundle_data as bd
from screener import candidate_pool as cp, classify as cl, detect as dt, val_card as vc


def _assets(monkeypatch, tmp_path, meta, digest=None, fail=False):
    payload = b'new!'
    calls = []
    assets = [{'name': '_meta.json', 'url': 'meta'},
              {'name': 'sample.parquet', 'url': 'sample', 'size': 4}]
    if digest:
        assets[1]['digest'] = 'sha256:' + hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(bd, '_ASSETS', ['sample.parquet'])
    monkeypatch.setattr(bd, '_dest', lambda name: tmp_path / name)
    monkeypatch.setattr(bd.fb, '_read_pat', lambda: 'test')
    monkeypatch.setattr(bd.fb, '_release_assets', lambda pat: assets)
    def api(url, pat, accept):
        calls.append(url)
        if url == 'meta':
            if fail:
                raise ValueError('meta')
            return json.dumps(meta).encode()
        return payload
    monkeypatch.setattr(bd.fb, '_api', api)
    return tmp_path / 'sample.parquet', calls, payload


def test_ensure_assets_redownloads_on_hash_mismatch(monkeypatch, tmp_path):
    meta = {'files': {'sample.parquet': {'sha256': hashlib.sha256(b'new!').hexdigest()}}}
    p, calls, payload = _assets(monkeypatch, tmp_path, meta)
    p.write_bytes(b'old!')
    assert bd.ensure_assets()['sample.parquet']
    assert 'sample' in calls and p.read_bytes() == payload


def test_ensure_assets_skips_when_hash_matches(monkeypatch, tmp_path):
    meta = {'files': {'sample.parquet': {'sha256': hashlib.sha256(b'new!').hexdigest()}}}
    p, calls, payload = _assets(monkeypatch, tmp_path, meta)
    p.write_bytes(payload)
    bd.ensure_assets()
    assert 'sample' not in calls


def test_ensure_assets_falls_back_to_digest_then_size(monkeypatch, tmp_path):
    p, calls, payload = _assets(monkeypatch, tmp_path, {'files': {}}, digest=True)
    p.write_bytes(b'old!')
    bd.ensure_assets()
    assert 'sample' in calls and p.read_bytes() == payload
    calls.clear()
    bd.ensure_assets()
    assert 'sample' not in calls
    p, calls, _ = _assets(monkeypatch, tmp_path, {'files': {}})
    p.write_bytes(b'old!')
    bd.ensure_assets()
    assert 'sample' not in calls


def test_ensure_assets_meta_failure_no_raise(monkeypatch, tmp_path):
    for digest in (True, False):
        p, calls, payload = _assets(monkeypatch, tmp_path, {}, digest=digest, fail=True)
        p.write_bytes(b'old!')
        assert bd.ensure_assets()['sample.parquet']
        assert ('sample' in calls) == digest


def test_read_fallback_streams_batches(monkeypatch, tmp_path):
    p = tmp_path / 'sample.parquet'
    pd.DataFrame({'ticker': [2330, 2317]*4, 'x': range(8)}).to_parquet(p)
    monkeypatch.setattr(bd, '_dest', lambda name: p)
    original = pd.read_parquet
    def read(*args, **kwargs):
        assert 'filters' in kwargs
        return original(*args, **kwargs)
    monkeypatch.setattr(pd, 'read_parquet', read)
    out = bd._read(p.name, '2330', False, ['ticker', 'x'])
    assert list(out.columns) == ['ticker', 'x']
    assert out.ticker.tolist() == [2330]*4
    assert out.x.tolist() == [0, 2, 4, 6]
    assert list(bd._read(p.name, '2330', False, ['x']).columns) == ['x']
    assert len(bd._read(p.name, '2330', False)) == 4


def test_revenue_yoy_asof_visibility():
    r = pd.DataFrame({'ticker': '2330', 'month': ['2025-08','2025-09','2026-08','2026-09'],
                      'revenue': [100, 200, 120, 300]})
    assert cp.revenue_yoy(r, pd.Timestamp('2026-10-09')).loc['2330','revenue_yoy'] == pytest.approx(.2)
    for asof in (pd.Timestamp('2026-10-10'), None):
        assert cp.revenue_yoy(r, asof).loc['2330','revenue_yoy'] == pytest.approx(.5)


def test_forward_jump():
    c = dt.forward_jump(277, 179)
    assert c.level == 'degrade' and c.value == pytest.approx(277/179)
    for e,t in [(150,120),(1,None),(1,-1),(None,1),(np.inf,1),(1,np.nan),(1,0),(1,np.inf)]:
        assert dt.forward_jump(e,t).level == 'ok'


def test_eps_base_adds_forward_jump():
    checks = []
    eps, _, forward = vc._eps_base('normal', {'ok':True,'eps_nc':3.,'flags':[],'k':1},
                                  pd.DataFrame({'eps':[1.]}), 1.5, None, False, checks)
    assert eps == 3. and forward
    assert any(c.name == '前瞻跳升' and c.level == 'degrade' for c in checks)


def test_cagr5_ok_boundary():
    for q,c,want in [(23,np.nan,True),(24,np.nan,False),(24,.13,True),(24,.05,False),(19,np.nan,True),(23,.05,False)]:
        assert cl._cagr5_ok(q,c) == want
