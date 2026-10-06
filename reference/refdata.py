"""私有參考資料（PCF 快照、總經／期貨／法人／指數序列）的存放與取用。

為什麼：這些檔來自投信官網、Yahoo、期交所、證交所網站等，各家網站條款禁止再散布；tw-hold 是公開 repo，
所以**不進 git**，改存私有 repo（`tw-hold-data`）Release `refdata-latest` 的資產。程式公開、資料不公開。

資產命名（Release 一個資產＝一個檔，同名 clobber）：
- `ref__<檔名>`        ← `data/reference/<檔名>`（parquet／json，一檔一資產）
- `pcf__<基金代號>.zip`  ← `data/pcf/<基金代號>/*.parquet`（每檔基金一個 zip，累積型）
- `pcf___index.json`   ← `data/pcf/_index.json`

寫入端（CI）：job 開頭 `pull`，跑完抓取後 `push` 自己動過的檔（只推自己負責的，不整包覆蓋，避免多支 workflow 互蓋）。
讀取端（Streamlit app）：啟動時 `pull`（唯讀 PAT `DATA_READ_PAT`）→ 還原到 `data/`，讀檔程式路徑完全不用改。
沒有 token＝不動作（本機開發照讀 `data/`）。
"""
from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
GH_API = "https://api.github.com"
UPLOAD_API = "https://uploads.github.com"
TAG = "refdata-latest"
DEFAULT_REPO = "tongxiaooppo-boop/tw-hold-data"
TOKEN_NAMES = ("DATA_READ_PAT", "DATA_REPO_PAT")      # 先唯讀、再寫入（CI 用後者）


class RefdataError(RuntimeError):
    pass


def data_repo() -> str:
    return (os.environ.get("DATA_REPO") or DEFAULT_REPO).strip()


def read_token() -> str | None:
    """環境變數 → repo 根目錄 .env → Streamlit secrets。一律 strip（secret 貼上常帶結尾換行）。"""
    for n in TOKEN_NAMES:
        v = (os.environ.get(n) or "").strip()
        if v:
            return v
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() in TOKEN_NAMES and v.strip():
                return v.strip().strip('"').strip("'").strip()
    try:
        import streamlit as st  # noqa: PLC0415
        for n in TOKEN_NAMES:
            v = st.secrets.get(n)
            if v and str(v).strip():
                return str(v).strip()
    except Exception:
        pass
    return None


# ───────────────────────── 資產命名（純函式，可測） ─────────────────────────
def ref_asset(name: str) -> str:
    return f"ref__{name}"


def pcf_asset(code: str) -> str:
    return f"pcf__{code}.zip"


PCF_INDEX_ASSET = "pcf___index.json"
REF_EXPECTED = ("global_macro.parquet", "global_macro_meta.json", "tx_futures.parquet", "tx_futures_meta.json",
                "foreign_futures.parquet", "inst_flow.parquet", "index_0050.parquet", "index_006201.parquet")
SHRINK_MIN = 0.5      # 累積型參考檔推回去的大小不得低於 pull 時的這個比例（Opus 審查 2026-10-06）


def zip_pcf_dir(fund_dir: Path) -> bytes:
    """把 `data/pcf/<code>/*.parquet` 壓成一個 zip（內部只放檔名，不帶路徑）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(fund_dir.glob("*.parquet")):
            z.write(p, p.name)
    return buf.getvalue()


def unzip_pcf(blob: bytes, fund_dir: Path) -> int:
    """還原 zip 到 `fund_dir`；只收單純檔名、副檔名 parquet（防路徑穿越）。回傳檔數。"""
    fund_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for info in z.infolist():
            name = info.filename
            if "/" in name or "\\" in name or name.startswith(".") or not name.endswith(".parquet"):
                continue
            _atomic_write(fund_dir / name, z.read(info))
            n += 1
    return n


def _atomic_write(path: Path, blob: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(path)


# ───────────────────────── GitHub API ─────────────────────────
def _req(url: str, tok: str, method: str = "GET", data: bytes | None = None, ctype: str | None = None,
         accept: str = "application/vnd.github+json") -> bytes:
    h = {"Authorization": f"Bearer {tok}", "Accept": accept, "X-GitHub-Api-Version": "2022-11-28",
         "User-Agent": "tw-hold-refdata"}
    if ctype:
        h["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RefdataError(f"GitHub API {e.code} {method} {url.split('?')[0]}: {e.read().decode('utf-8', 'replace')[:200]}") from e


def _release(tok: str, create: bool = False) -> dict | None:
    repo = data_repo()
    try:
        return json.loads(_req(f"{GH_API}/repos/{repo}/releases/tags/{TAG}", tok))
    except RefdataError as e:
        if "404" in str(e) and create:
            body = json.dumps({"tag_name": TAG, "name": "私有參考資料", "body": "由 CI 維護；勿手動覆蓋。私有保存、不對外散布。"}).encode()
            return json.loads(_req(f"{GH_API}/repos/{repo}/releases", tok, "POST", body, "application/json"))
        if "404" in str(e):
            return None
        raise


# ───────────────────────── pull ／ push ─────────────────────────
def pull(only: str = "all", root: Path = DATA, tok: str | None = None) -> dict:
    """把 Release 資產還原到 `root/`（預設 data/）。沒 token 或沒 Release → 不動作。
    only：`all`｜`ref`｜`pcf`。回傳 {資產名: 檔數或 True}；失敗項是 "失敗：…" 字串；
    **預期有但 Release 上沒有的資產**（上傳中斷把它刪掉了）記在 `_missing`（--strict 會因此失敗，
    不然下一輪會從殘缺目錄續寫再推上去，把歷史永久截斷）。"""
    tok = tok or read_token()
    if not tok:
        return {"_skipped": "no token"}
    rel = _release(tok)
    if rel is None:
        return {"_skipped": "no release"}
    assets = {a["name"]: a for a in rel.get("assets", [])}
    for n in list(assets):          # 上傳到一半留下的 X.new：只在正式檔不存在時當後備（內容是完整的新版）
        if n.endswith(".new"):
            if n[:-4] not in assets:
                assets[n[:-4]] = assets[n]
            del assets[n]
    out: dict = {}
    for name, a in sorted(assets.items()):
        want = ((only in ("all", "ref") and name.startswith("ref__"))
                or (only in ("all", "pcf") and name.startswith("pcf__")))
        if not want:
            continue
        try:
            blob = _req(a["url"], tok, accept="application/octet-stream")
            if name.startswith("ref__"):
                _atomic_write(root / "reference" / name[len("ref__"):], blob)
                out[name] = True
            elif name == PCF_INDEX_ASSET:
                _atomic_write(root / "pcf" / "_index.json", blob)
                out[name] = True
            else:
                n = unzip_pcf(blob, root / "pcf" / name[len("pcf__"):-len(".zip")])
                out[name] = n if n > 0 else "失敗：zip 裡沒有任何快照檔"
        except Exception as e:      # noqa: BLE001
            out[name] = f"失敗：{str(e)[:120]}"
    missing: list[str] = []
    if only in ("all", "ref"):
        missing += [ref_asset(n) for n in REF_EXPECTED if ref_asset(n) not in assets]
    if only in ("all", "pcf"):
        if PCF_INDEX_ASSET not in assets:
            missing.append(PCF_INDEX_ASSET)
        else:
            try:
                funds = json.loads((root / "pcf" / "_index.json").read_text(encoding="utf-8")).get("funds", {})
                missing += [pcf_asset(c) for c in funds if pcf_asset(c) not in assets]
            except Exception as e:      # noqa: BLE001
                missing.append(f"{PCF_INDEX_ASSET}（讀不懂：{str(e)[:60]}）")
    if missing:
        out["_missing"] = missing
    _write_marker(root)
    return out


def _write_marker(root: Path) -> None:
    """記下 pull 當下各檔規模（PCF 每基金快照數、參考檔大小），push 前對照。"""
    try:
        m: dict = {"pcf": {}, "ref": {}}
        pcf = root / "pcf"
        if pcf.is_dir():
            for d in pcf.iterdir():
                if d.is_dir():
                    m["pcf"][d.name] = len(list(d.glob("*.parquet")))
        ref = root / "reference"
        if ref.is_dir():
            for f in ref.iterdir():
                if f.is_file() and f.suffix in (".parquet", ".json"):
                    m["ref"][f.name] = f.stat().st_size
        (root / ".refdata_pulled.json").write_text(json.dumps(m), encoding="utf-8")
    except OSError:
        pass


def _guard_against_shrink(jobs_meta: list, root: Path) -> None:
    """push 前的不倒退閘門：pull 時記下的規模 vs 現在要推的。jobs_meta＝[(kind, key, 現在規模)]，kind＝pcf／ref。"""
    mk = root / ".refdata_pulled.json"
    if not mk.exists():
        return
    try:
        m = json.loads(mk.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for kind, key, now in jobs_meta:
        before = (m.get(kind) or {}).get(key)
        if before is None:
            continue
        if kind == "pcf" and now < before:
            raise RefdataError(f"pcf/{key} 快照數 {now} < pull 時的 {before}：疑似殘缺目錄，拒絕覆蓋 Release")
        if kind == "ref" and before > 0 and now < before * SHRINK_MIN:
            raise RefdataError(f"reference/{key} 大小 {now} < pull 時 {before} 的 {int(SHRINK_MIN * 100)}%：疑似殘缺，拒絕覆蓋 Release")


def _upload(tok: str, rel: dict, name: str, blob: bytes) -> None:
    """先傳暫名 `<name>.new`，成功後才刪舊資產、再改名——任何一步失敗，Release 上都至少留著一份完整檔
    （舊版或 .new），不會像「先刪後傳」那樣 POST 失敗就讓歷史消失。pull 對孤兒 .new 有後備。"""
    repo = data_repo()
    tmp = name + ".new"
    for a in rel.get("assets", []):
        if a["name"] == tmp:                                  # 上次中斷留下的暫存，先清掉
            _req(f"{GH_API}/repos/{repo}/releases/assets/{a['id']}", tok, "DELETE")
    url = f"{UPLOAD_API}/repos/{repo}/releases/{rel['id']}/assets?name={urllib.request.quote(tmp)}"
    new = json.loads(_req(url, tok, "POST", blob, "application/octet-stream"))
    for a in rel.get("assets", []):
        if a["name"] == name:
            _req(f"{GH_API}/repos/{repo}/releases/assets/{a['id']}", tok, "DELETE")
    _req(f"{GH_API}/repos/{repo}/releases/assets/{new['id']}", tok, "PATCH",
         json.dumps({"name": name}).encode(), "application/json")


def push(paths: list[Path], tok: str | None = None, root: Path = DATA) -> dict:
    """上傳指定檔／目錄。檔在 `data/reference/` → `ref__`；目錄 `data/pcf` → 每檔基金一個 zip＋_index.json；
    `data/pcf/<code>` → 該基金 zip。缺檔略過並回報。沒 token → RefdataError（寫入端沒 token 是設定錯誤，要大聲）。"""
    tok = tok or read_token()
    if not tok:
        raise RefdataError("沒有 token（DATA_REPO_PAT／DATA_READ_PAT）")
    rel = _release(tok, create=True)
    out: dict = {}
    jobs: list[tuple[str, bytes]] = []
    for p in paths:
        p = Path(p)
        if p.is_dir() and p.name == "pcf":
            for d in sorted(x for x in p.iterdir() if x.is_dir()):
                jobs.append((pcf_asset(d.name), zip_pcf_dir(d)))
            if (p / "_index.json").exists():
                jobs.append((PCF_INDEX_ASSET, (p / "_index.json").read_bytes()))
        elif p.is_dir() and p.parent.name == "pcf":
            jobs.append((pcf_asset(p.name), zip_pcf_dir(p)))
        elif p.is_file() and p.parent.name == "reference":
            jobs.append((ref_asset(p.name), p.read_bytes()))
        elif p.is_file() and p.name == "_index.json" and p.parent.name == "pcf":
            jobs.append((PCF_INDEX_ASSET, p.read_bytes()))
        else:
            out[str(p)] = "略過（不存在或不是 data/reference 檔、data/pcf 目錄）"
    meta = []
    for name, blob in jobs:
        if name.startswith("pcf__") and name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                meta.append(("pcf", name[len("pcf__"):-len(".zip")], len(z.namelist())))
        elif name.startswith("ref__"):
            meta.append(("ref", name[len("ref__"):], len(blob)))
    _guard_against_shrink(meta, root)
    for name, blob in jobs:
        _upload(tok, rel, name, blob)
        out[name] = len(blob)
    return out
