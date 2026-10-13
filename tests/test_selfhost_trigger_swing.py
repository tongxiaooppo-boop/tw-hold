"""B10：selfhost_datapack.yml 發佈後觸發 tw-swing 的步驟——預設關閉、只在完整日前進時打 API、失敗不擋資料包。

判斷邏輯已搬進 scripts/swing_trigger.py（見 test_swing_trigger.py）；這裡驗 workflow 步驟的守門條件與接線。
"""
import json
import os
import shutil
import subprocess
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
@pytest.mark.parametrize("old,new,expect_decision", [
    (None, "2026-10-08", "觸發"),          # 已發佈沒有 manifest → 視為前進
    ("2026-10-07", "2026-10-08", "觸發"),  # 前進
    ("2026-10-08", "2026-10-08", "不觸發"),  # 同日更正重發
])
def test_workflow_command_is_wired_to_swing_trigger_script(tmp_path, old, new, expect_decision):
    """判斷邏輯在 scripts/swing_trigger.py（test_swing_trigger.py 逐案測過）；這裡只驗 workflow 那一行的接線——
    用 workflow 裡真正的 run 指令跑一遍（不給 PAT，所以絕不會碰網路）：參數名稱對、路徑變數對、沒 PAT 也不會讓步驟變紅。"""
    _, _, st = _step()
    assert st["run"].startswith("python scripts/swing_trigger.py") and "--dispatch" in st["run"]
    M, P = tmp_path / "M", tmp_path / "P"
    M.mkdir(); P.mkdir()
    (M / "merge_manifest.json").write_text(json.dumps({"complete_day": new, "events_gap_days": []}), encoding="utf-8")
    if old:
        (P / "merge_manifest.json").write_text(json.dumps({"complete_day": old, "events_gap_days": []}), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "SWING_PAT"}
    env.update({"M": M.as_posix(), "P": P.as_posix(), "PYTHONIOENCODING": "utf-8"})
    r = subprocess.run([bash, "-ec", st["run"]], env=env, capture_output=True, text=True, encoding="utf-8",
                       cwd=Path(__file__).resolve().parents[1])
    assert r.returncode == 0, r.stderr
    assert f"[swing_trigger] {expect_decision}" in r.stdout
    if expect_decision == "觸發":
        assert "TWSWING_DISPATCH_PAT 沒設" in r.stdout                # 有決定要觸發、但沒給 PAT：只警告
