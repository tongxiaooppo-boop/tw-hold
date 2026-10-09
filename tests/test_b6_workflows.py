"""B6：workflow 接線——事件資產的下載／上傳／來源戳記，且每個 run 區塊的 bash 語法正確、沒有新增排程。"""
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _load(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def test_openapi_daily_uploads_events_assets_and_outputs_exist():
    text = (WF / "openapi_daily.yml").read_text(encoding="utf-8")
    assert "openapi_events.parquet" in text and "openapi_events_meta.json" in text
    assert "steps.collect.outputs.events_changed" in text and "steps.collect.outputs.events_meta_changed" in text
    # 腳本真的有寫這兩個 output（名稱對得上，不然 workflow 永遠不上傳）
    py = (WF.parent.parent / "scripts" / "selfhost_openapi_daily.py").read_text(encoding="utf-8")
    assert "events_changed=" in py and "events_meta_changed=" in py


def test_upload_of_events_failure_is_warning_only():
    y = _load("openapi_daily.yml")
    up = next(s for s in y["jobs"]["collect"]["steps"] if s.get("name") == "上傳累積檔")["run"]
    for line in up.splitlines():
        if "openapi_events" in line and "gh release upload" in line:
            assert "||" in line and "warning" in line                  # 事件上傳失敗不擋日線／融資／法人


def test_datapack_stamp_covers_events_and_download_is_optional():
    text = (WF / "selfhost_datapack.yml").read_text(encoding="utf-8")
    assert "events" in text.split("source_stamp.txt")[0]                # 來源戳記納入事件資產
    assert "openapi_events.parquet openapi_events_meta.json" in text    # 下載是選配迴圈
    assert "grep -qx" in text


def test_no_cron_added_to_datapack():
    y = _load("selfhost_datapack.yml")
    on = y.get(True) or y.get("on")
    assert "schedule" not in on


bash = shutil.which("bash")


@pytest.mark.skipif(bash is None, reason="需要 bash")
@pytest.mark.parametrize("wf", ["openapi_daily.yml", "selfhost_datapack.yml"])
def test_every_run_block_has_valid_bash_syntax(wf, tmp_path):
    y = _load(wf)
    for job in y["jobs"].values():
        for st in job["steps"]:
            run = st.get("run")
            if not run:
                continue
            f = tmp_path / "s.sh"
            f.write_text(run.replace("${{", "$ {{"), encoding="utf-8")        # 表達式不是 bash，先打散避免干擾語法檢查
            r = subprocess.run([bash, "-n", str(f)], capture_output=True, text=True)
            assert r.returncode == 0, f"{wf} 步驟「{st.get('name')}」bash 語法錯誤：{r.stderr}"
