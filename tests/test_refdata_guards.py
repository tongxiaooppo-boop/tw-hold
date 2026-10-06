"""Opus 審查 2026-10-06 的修正：上傳不可「先刪後傳」、pull 預期清單、push 不倒退閘門、孤兒 .new 後備。"""
from __future__ import annotations

import io
import json
import zipfile

import pandas as pd
import pytest

from reference import refdata as rd


def _zip_with(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, b"x")
    return buf.getvalue()


# ───── _upload：先傳暫名、成功才刪舊、最後改名 ─────
def test_upload_order_uploads_before_deleting(monkeypatch):
    calls = []

    def fake_req(url, tok, method="GET", data=None, ctype=None, accept=""):
        calls.append((method, url.split("?")[0].split("/")[-1], url))
        if method == "POST":
            return json.dumps({"id": 99}).encode()
        return b"{}"
    monkeypatch.setattr(rd, "_req", fake_req)
    monkeypatch.setattr(rd, "data_repo", lambda: "o/r")
    rd._upload("t", {"id": 1, "assets": [{"name": "pcf__A.zip", "id": 7}]}, "pcf__A.zip", b"new")
    order = [c[0] for c in calls]
    assert order == ["POST", "DELETE", "PATCH"]                 # 先傳、再刪舊、最後改名
    assert "pcf__A.zip.new" in calls[0][2]                       # 傳的是暫名
    assert calls[1][2].endswith("/assets/7") and calls[2][2].endswith("/assets/99")


def test_upload_failure_never_deletes_old(monkeypatch):
    calls = []

    def fake_req(url, tok, method="GET", data=None, ctype=None, accept=""):
        calls.append(method)
        if method == "POST":
            raise rd.RefdataError("502")
        return b"{}"
    monkeypatch.setattr(rd, "_req", fake_req)
    monkeypatch.setattr(rd, "data_repo", lambda: "o/r")
    with pytest.raises(rd.RefdataError):
        rd._upload("t", {"id": 1, "assets": [{"name": "pcf__A.zip", "id": 7}]}, "pcf__A.zip", b"new")
    assert "DELETE" not in calls                                 # 傳失敗＝舊資產原封不動（舊版會先刪掉）


def test_upload_cleans_stale_tmp_first(monkeypatch):
    calls = []

    def fake_req(url, tok, method="GET", data=None, ctype=None, accept=""):
        calls.append((method, url.rsplit("/", 1)[-1]))
        return json.dumps({"id": 5}).encode() if method == "POST" else b"{}"
    monkeypatch.setattr(rd, "_req", fake_req)
    monkeypatch.setattr(rd, "data_repo", lambda: "o/r")
    rd._upload("t", {"id": 1, "assets": [{"name": "x.new", "id": 3}]}, "x", b"b")
    assert calls[0] == ("DELETE", "3")                           # 上次中斷留下的 x.new 先清掉


# ───── pull：預期清單、空 zip、孤兒 .new ─────
def _pull_with(monkeypatch, tmp_path, assets, blobs, only="all"):
    monkeypatch.setattr(rd, "_release", lambda tok, create=False: {"assets": assets})
    monkeypatch.setattr(rd, "_req", lambda url, tok, method="GET", data=None, ctype=None, accept="": blobs[url])
    return rd.pull(only=only, root=tmp_path, tok="t")


def test_pull_flags_missing_expected_ref_assets(monkeypatch, tmp_path):
    assets = [{"name": "ref__global_macro.parquet", "url": "u1"}]
    r = _pull_with(monkeypatch, tmp_path, assets, {"u1": b"x"}, only="ref")
    assert "ref__tx_futures.parquet" in r["_missing"] and "ref__global_macro.parquet" not in r["_missing"]


def test_pull_flags_missing_pcf_zip_from_index(monkeypatch, tmp_path):
    index = json.dumps({"funds": {"AAA": {}, "BBB": {}}}).encode()
    assets = [{"name": "pcf___index.json", "url": "ui"}, {"name": "pcf__AAA.zip", "url": "ua"}]
    r = _pull_with(monkeypatch, tmp_path, assets, {"ui": index, "ua": _zip_with(["2026-10-06.parquet"])}, only="pcf")
    assert r["_missing"] == ["pcf__BBB.zip"]                     # 上傳中斷把 BBB 刪掉了 → 要大聲


def test_pull_empty_zip_is_failure(monkeypatch, tmp_path):
    index = json.dumps({"funds": {"AAA": {}}}).encode()
    assets = [{"name": "pcf___index.json", "url": "ui"}, {"name": "pcf__AAA.zip", "url": "ua"}]
    r = _pull_with(monkeypatch, tmp_path, assets, {"ui": index, "ua": _zip_with([])}, only="pcf")
    assert str(r["pcf__AAA.zip"]).startswith("失敗")


def test_pull_orphan_new_used_as_fallback(monkeypatch, tmp_path):
    index = json.dumps({"funds": {"AAA": {}}}).encode()
    assets = [{"name": "pcf___index.json", "url": "ui"}, {"name": "pcf__AAA.zip.new", "url": "ua"}]
    r = _pull_with(monkeypatch, tmp_path, assets, {"ui": index, "ua": _zip_with(["2026-10-06.parquet"])}, only="pcf")
    assert r["pcf__AAA.zip"] == 1 and "_missing" not in r        # 正式檔缺、.new 完整 → 當後備
    assert (tmp_path / "pcf" / "AAA" / "2026-10-06.parquet").exists()


def test_pull_prefers_final_over_new(monkeypatch, tmp_path):
    index = json.dumps({"funds": {"AAA": {}}}).encode()
    assets = [{"name": "pcf___index.json", "url": "ui"}, {"name": "pcf__AAA.zip", "url": "uf"},
              {"name": "pcf__AAA.zip.new", "url": "un"}]
    blobs = {"ui": index, "uf": _zip_with(["a.parquet", "b.parquet"]), "un": _zip_with(["c.parquet"])}
    r = _pull_with(monkeypatch, tmp_path, assets, blobs, only="pcf")
    assert r["pcf__AAA.zip"] == 2                                # 兩者都在時以正式檔為準


# ───── push：不倒退閘門 ─────
def _setup_pull_marker(root, pcf_counts=None, ref_sizes=None):
    (root / ".refdata_pulled.json").write_text(json.dumps({"pcf": pcf_counts or {}, "ref": ref_sizes or {}}), encoding="utf-8")


def test_push_refuses_pcf_dir_with_fewer_snapshots_than_pulled(monkeypatch, tmp_path):
    pcf = tmp_path / "pcf"
    (pcf / "A").mkdir(parents=True)
    pd.DataFrame({"a": [1]}).to_parquet(pcf / "A" / "2026-10-07.parquet")      # 殘缺：只有 1 份
    _setup_pull_marker(tmp_path, pcf_counts={"A": 15})
    monkeypatch.setattr(rd, "_release", lambda tok, create=False: {"id": 1, "assets": []})
    sent = []
    monkeypatch.setattr(rd, "_upload", lambda *a: sent.append(a[2]))
    with pytest.raises(rd.RefdataError, match="殘缺"):
        rd.push([pcf], tok="t", root=tmp_path)
    assert sent == []                                            # 一個都沒推


def test_push_allows_same_or_more_snapshots(monkeypatch, tmp_path):
    pcf = tmp_path / "pcf"
    (pcf / "A").mkdir(parents=True)
    for i in range(3):
        pd.DataFrame({"a": [i]}).to_parquet(pcf / "A" / f"2026-10-0{i + 1}.parquet")
    _setup_pull_marker(tmp_path, pcf_counts={"A": 3})
    monkeypatch.setattr(rd, "_release", lambda tok, create=False: {"id": 1, "assets": []})
    sent = []
    monkeypatch.setattr(rd, "_upload", lambda tok, rel, name, blob: sent.append(name))
    rd.push([pcf], tok="t", root=tmp_path)
    assert sent == ["pcf__A.zip"]


def test_push_refuses_ref_file_that_shrank_by_half(monkeypatch, tmp_path):
    ref = tmp_path / "reference"
    ref.mkdir()
    (ref / "tx_futures.parquet").write_bytes(b"x" * 100)
    _setup_pull_marker(tmp_path, ref_sizes={"tx_futures.parquet": 1000})
    monkeypatch.setattr(rd, "_release", lambda tok, create=False: {"id": 1, "assets": []})
    monkeypatch.setattr(rd, "_upload", lambda *a: None)
    with pytest.raises(rd.RefdataError, match="殘缺"):
        rd.push([ref / "tx_futures.parquet"], tok="t", root=tmp_path)


def test_push_without_marker_is_not_blocked(monkeypatch, tmp_path):
    ref = tmp_path / "reference"
    ref.mkdir()
    (ref / "g.parquet").write_bytes(b"x")
    monkeypatch.setattr(rd, "_release", lambda tok, create=False: {"id": 1, "assets": []})
    sent = []
    monkeypatch.setattr(rd, "_upload", lambda tok, rel, name, blob: sent.append(name))
    rd.push([ref / "g.parquet"], tok="t", root=tmp_path)
    assert sent == ["ref__g.parquet"]                            # 沒做過 pull（本機首次）不擋


def test_unzip_prunes_snapshots_trimmed_from_release(tmp_path):
    d = tmp_path / "A"
    d.mkdir()
    for n in ("old1", "old2", "keep"):
        pd.DataFrame({"a": [1]}).to_parquet(d / f"{n}.parquet")
    n = rd.unzip_pcf(_zip_with(["keep.parquet", "new.parquet"]), d)
    assert n == 2 and sorted(p.name for p in d.glob("*.parquet")) == ["keep.parquet", "new.parquet"]   # 已被 Release 修剪的 old1／old2 不留


def test_unzip_empty_zip_does_not_wipe_directory(tmp_path):
    d = tmp_path / "A"
    d.mkdir()
    pd.DataFrame({"a": [1]}).to_parquet(d / "keep.parquet")
    assert rd.unzip_pcf(_zip_with([]), d) == 0
    assert (d / "keep.parquet").exists()                          # 空 zip（異常）不可把本地快照清光
