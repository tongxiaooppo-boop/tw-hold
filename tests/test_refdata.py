"""私有參考資料存取（reference/refdata.py）：命名、zip 往返、路徑穿越防護、token strip、沒 token 不動作。"""
from __future__ import annotations

import io
import json
import zipfile

import pandas as pd
import pytest

from reference import refdata as rd


def test_asset_names():
    assert rd.ref_asset("global_macro.parquet") == "ref__global_macro.parquet"
    assert rd.pcf_asset("00403A") == "pcf__00403A.zip"


def test_pcf_zip_roundtrip(tmp_path):
    src = tmp_path / "pcf" / "00403A"
    src.mkdir(parents=True)
    pd.DataFrame({"a": [1]}).to_parquet(src / "2026-10-05.parquet")
    pd.DataFrame({"a": [2]}).to_parquet(src / "2026-10-06.parquet")
    (src / "note.txt").write_text("x")                      # 非 parquet 不收
    blob = rd.zip_pcf_dir(src)
    dst = tmp_path / "restore" / "00403A"
    assert rd.unzip_pcf(blob, dst) == 2
    assert sorted(p.name for p in dst.iterdir()) == ["2026-10-05.parquet", "2026-10-06.parquet"]
    assert pd.read_parquet(dst / "2026-10-06.parquet")["a"].iloc[0] == 2


def test_unzip_blocks_path_traversal(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.parquet", b"x")
        z.writestr("sub/x.parquet", b"x")
        z.writestr("ok.parquet", b"x")
        z.writestr("readme.txt", b"x")
    dst = tmp_path / "d"
    assert rd.unzip_pcf(buf.getvalue(), dst) == 1
    assert [p.name for p in dst.iterdir()] == ["ok.parquet"] and not (tmp_path / "evil.parquet").exists()


def test_token_is_stripped(monkeypatch):
    monkeypatch.delenv("DATA_REPO_PAT", raising=False)
    monkeypatch.setenv("DATA_READ_PAT", "tok" + chr(10))
    assert rd.read_token() == "tok"


def test_pull_without_token_is_noop(monkeypatch, tmp_path):
    for n in rd.TOKEN_NAMES:
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setattr(rd, "REPO", tmp_path)               # 沒有 .env
    assert rd.pull(root=tmp_path / "data") == {"_skipped": "no token"}
    assert not (tmp_path / "data").exists()


def test_push_without_token_fails_loudly(monkeypatch, tmp_path):
    for n in rd.TOKEN_NAMES:
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setattr(rd, "REPO", tmp_path)
    with pytest.raises(rd.RefdataError):
        rd.push([tmp_path / "x"])


def test_pull_restores_assets_and_survives_one_failure(monkeypatch, tmp_path):
    pcf_zip = io.BytesIO()
    with zipfile.ZipFile(pcf_zip, "w") as z:
        z.writestr("2026-10-06.parquet", b"p")
    blobs = {"u1": b"refbytes", "u2": pcf_zip.getvalue(), "u3": b'{"i":1}'}
    rel = {"assets": [{"name": "ref__a.parquet", "url": "u1"}, {"name": "pcf__X.zip", "url": "u2"},
                      {"name": "pcf___index.json", "url": "u3"}, {"name": "ref__bad.parquet", "url": "ubad"},
                      {"name": "other.txt", "url": "u9"}]}
    monkeypatch.setattr(rd, "_release", lambda tok, create=False: rel)

    def fake_req(url, tok, method="GET", data=None, ctype=None, accept=""):
        if url == "ubad":
            raise rd.RefdataError("boom")
        return blobs[url]
    monkeypatch.setattr(rd, "_req", fake_req)
    r = rd.pull(root=tmp_path, tok="t")
    assert (tmp_path / "reference" / "a.parquet").read_bytes() == b"refbytes"
    assert (tmp_path / "pcf" / "X" / "2026-10-06.parquet").exists()
    assert json.loads((tmp_path / "pcf" / "_index.json").read_text()) == {"i": 1}
    assert str(r["ref__bad.parquet"]).startswith("失敗") and "other.txt" not in r
    r2 = rd.pull(only="pcf", root=tmp_path / "only_pcf", tok="t")
    assert "ref__a.parquet" not in r2 and not (tmp_path / "only_pcf" / "reference").exists()


def test_push_builds_expected_assets(monkeypatch, tmp_path):
    ref = tmp_path / "data" / "reference"
    ref.mkdir(parents=True)
    (ref / "g.parquet").write_bytes(b"g")
    pcf = tmp_path / "data" / "pcf"
    (pcf / "A").mkdir(parents=True)
    pd.DataFrame({"a": [1]}).to_parquet(pcf / "A" / "2026-10-06.parquet")
    (pcf / "_index.json").write_text("{}")
    sent = {}
    monkeypatch.setattr(rd, "_release", lambda tok, create=False: {"id": 1, "assets": []})
    monkeypatch.setattr(rd, "_upload", lambda tok, rel, name, blob: sent.__setitem__(name, len(blob)))
    r = rd.push([ref / "g.parquet", pcf, tmp_path / "nope.txt"], tok="t")
    assert set(sent) == {"ref__g.parquet", "pcf__A.zip", "pcf___index.json"}
    assert "略過" in r[str(tmp_path / "nope.txt")]
