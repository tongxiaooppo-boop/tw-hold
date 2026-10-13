"""總經導航頁尾「立即重新整理資料」按鈕（app/streamlit_app.py::_refresh_all／_REFRESH_WORKFLOWS）。

2026-10-13：按鈕從兩條（重算側）擴到五條（加收集側：GitHub 排程常晚數小時，卡片過期時要能直接叫收集）。
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import streamlit_app as app  # noqa: E402

WF = [("a.yml", "甲"), ("b.yml", "乙"), ("c.yml", "丙")]


def _run(status_by_file, ok_by_file=None):
    ok_by_file = ok_by_file or {}
    calls = []

    def latest(wf, token):
        s = status_by_file.get(wf)
        return {"status": s} if s else None

    def trigger(wf, token):
        calls.append(wf)
        return ok_by_file.get(wf, (True, ""))
    res = app._refresh_all("tok", WF, latest, trigger)
    return res, calls


def test_triggers_every_workflow_when_none_is_running():
    res, calls = _run({})
    assert calls == ["a.yml", "b.yml", "c.yml"]
    assert res == {"busy": [], "ok": ["甲", "乙", "丙"], "failed": []}


def test_a_running_workflow_is_skipped_but_the_others_still_trigger():
    res, calls = _run({"b.yml": "in_progress", "c.yml": "completed"})
    assert calls == ["a.yml", "c.yml"]                                   # 以前一條在跑就整個不動；現在只略過那一條
    assert res["busy"] == ["乙"] and res["ok"] == ["甲", "丙"]
    res2, calls2 = _run({"a.yml": "queued"})
    assert calls2 == ["b.yml", "c.yml"] and res2["busy"] == ["甲"]


def test_failures_are_reported_per_workflow_without_stopping_the_rest():
    res, calls = _run({}, {"b.yml": (False, "HTTP 403：Resource not accessible")})
    assert calls == ["a.yml", "b.yml", "c.yml"]
    assert res["ok"] == ["甲", "丙"] and res["failed"] == [("乙", "HTTP 403：Resource not accessible")]


def test_all_running_triggers_nothing():
    res, calls = _run({"a.yml": "in_progress", "b.yml": "queued", "c.yml": "in_progress"})
    assert calls == [] and res["ok"] == [] and res["busy"] == ["甲", "乙", "丙"]


def test_real_refresh_list_points_at_existing_dispatchable_workflows():
    # 打錯檔名或該 workflow 沒有 workflow_dispatch → 按下去 GitHub 回 404／422，使用者只會看到「觸發失敗」
    files = [f for f, _ in app._REFRESH_WORKFLOWS]
    assert len(files) == len(set(files)) and "openapi_daily.yml" in files and "rebuild.yml" in files
    for f in files:
        p = ROOT / ".github" / "workflows" / f
        assert p.exists(), f
        on = yaml.safe_load(p.read_text(encoding="utf-8")).get(True) or yaml.safe_load(p.read_text(encoding="utf-8")).get("on")
        assert "workflow_dispatch" in on, f


def test_no_concurrency_group_holds_more_than_two_of_the_refresh_workflows():
    # 同群組 cancel-in-progress=false 時只能有「一個執行中＋一個等待中」；第三條進來會把等待中的取消。五條一次觸發不能超過兩條同組
    groups = Counter()
    for f, _ in app._REFRESH_WORKFLOWS:
        text = (ROOT / ".github" / "workflows" / f).read_text(encoding="utf-8")
        m = re.search(r"^concurrency:\s*\n(?:[ \t]+#[^\n]*\n)*[ \t]+group:\s*(\S+)", text, re.M)
        groups[m.group(1) if m else f] += 1
    assert max(groups.values()) <= 2, groups


def test_button_end_to_end_with_fake_github_api(monkeypatch):
    """用 AppTest 真的按一次按鈕（GitHub API 用假的）：沒有 PAT 不顯示；有 PAT 按下去五條都觸發、畫面講得出來。"""
    import io
    import json
    import urllib.request

    pytest = __import__("pytest")
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    posted = []

    class _Resp:
        def __init__(self, body=b"", status=200):
            self._b, self.status = body, status

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        if "/dispatches" in url:
            posted.append(url.split("/workflows/")[1].split("/")[0])
            return _Resp(status=204)
        if "/runs?" in url:                                    # 每條都「沒有進行中的 run」
            return _Resp(json.dumps({"workflow_runs": []}).encode())
        raise OSError("不該打到的網址：" + url)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    app._refresh_gate()["until"] = 0.0                         # 冷卻是行程級、會跨測試殘留

    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=60)
    at.run()
    assert not at.exception and not [b for b in at.button if b.key == "macro_refresh_btn"]      # 沒 PAT：不顯示按鈕

    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=60)
    at.secrets["GH_DISPATCH_PAT"] = "t"
    at.run()
    btn = [b for b in at.button if b.key == "macro_refresh_btn"]
    assert btn, "有 PAT 應該顯示按鈕"
    btn[0].click().run()
    assert not at.exception
    assert sorted(posted) == sorted(f for f, _ in app._REFRESH_WORKFLOWS)
    assert any("已觸發雲端重跑" in s.value and "官方日線／融資收集" in s.value for s in at.success)
    app._refresh_gate()["until"] = 0.0
