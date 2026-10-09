"""B10：selfhost_datapack.yml 發佈後觸發 tw-swing 的步驟——預設關閉、只在完整日前進時打 API、失敗不擋資料包。

做法：把 workflow 裡該步驟的 bash 取出，用假的 `curl` 放在 PATH 前面實際跑一遍（不碰網路）。
"""
import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "selfhost_datapack.yml"
STEP_NAME = "觸發 tw-swing daily"


def _step():
    y = yaml.safe_load(WF.read_text(encoding="utf-8"))
    steps = y["jobs"]["build"]["steps"]
    hits = [s for s in steps if STEP_NAME in s.get("name", "")]
    assert len(hits) == 1
    return y, steps, hits[0]


def test_step_is_guarded_and_after_publish():
    y, steps, st = _step()
    names = [s.get("name", "") for s in steps]
    assert names.index(st["name"]) > next(i for i, n in enumerate(names) if n.startswith("發佈（zip"))
    cond = st["if"]
    assert "vars.TRIGGER_SWING == 'true'" in cond                      # 預設關閉
    assert "steps.same.outputs.skip == 'false'" in cond                # 內容沒變不觸發
    assert st.get("continue-on-error") is True                         # 失敗不擋資料包
    assert st["env"]["SWING_PAT"] == "${{ secrets.TWSWING_DISPATCH_PAT }}"


def test_no_new_schedule_added():
    y, _, _ = _step()
    on = y.get(True) or y.get("on")                                    # PyYAML 把 on 解析成 True
    assert "schedule" not in on                                        # 使用者原則：不自行改頻率


bash = shutil.which("bash")


@pytest.mark.skipif(bash is None, reason="需要 bash")
@pytest.mark.parametrize("old,new,expect_call", [
    (None, "2026-10-08", True),            # 已發佈沒有 manifest → 視為前進
    ("2026-10-07", "2026-10-08", True),    # 前進
    ("2026-10-08", "2026-10-08", False),   # 同日更正重發 → 不觸發
    ("2026-10-09", "2026-10-08", False),   # 倒退 → 不觸發
])
def test_trigger_only_when_complete_day_advances(tmp_path, old, new, expect_call):
    _, _, st = _step()
    M, P = tmp_path / "M", tmp_path / "P"
    M.mkdir(); P.mkdir()
    (M / "merge_manifest.json").write_text(json.dumps({"complete_day": new}), encoding="utf-8")
    if old:
        (P / "merge_manifest.json").write_text(json.dumps({"complete_day": old}), encoding="utf-8")
    log = tmp_path / "curl.log"
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "curl").write_text(textwrap.dedent(f"""\
        #!/bin/bash
        echo "$@" >> "{log.as_posix()}"
        out=""
        while [ $# -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done
        [ -n "$out" ] && echo '{{}}' > "$out"
        printf 204
        """), encoding="utf-8")
    script = st["run"].replace("/tmp/d.json", (tmp_path / "d.json").as_posix())
    env = {**os.environ, "PATH": fake.as_posix() + os.pathsep + os.environ["PATH"],
           "M": M.as_posix(), "P": P.as_posix(), "SWING_PAT": "dummy"}
    r = subprocess.run([bash, "-ec", script], env=env, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    called = log.exists() and "actions/workflows/daily.yml/dispatches" in log.read_text(encoding="utf-8")
    assert called == expect_call


@pytest.mark.skipif(bash is None, reason="需要 bash")
def test_missing_pat_is_warning_not_failure(tmp_path):
    _, _, st = _step()
    M, P = tmp_path / "M", tmp_path / "P"
    M.mkdir(); P.mkdir()
    (M / "merge_manifest.json").write_text(json.dumps({"complete_day": "2026-10-08"}), encoding="utf-8")
    env = {**os.environ, "M": M.as_posix(), "P": P.as_posix(), "SWING_PAT": ""}
    r = subprocess.run([bash, "-ec", st["run"]], env=env, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and "沒設" in r.stdout
