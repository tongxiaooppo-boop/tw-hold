"""事件接力（scripts/swing_trigger.py）：資料包發佈後通知 tw-swing 跑每日掃描——何時觸發、失敗怎麼辦。"""
from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "st", Path(__file__).resolve().parents[1] / "scripts" / "swing_trigger.py")
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)


def _m(day, gaps=None):
    return {"complete_day": day, "events_gap_days": gaps or []}


# ── 何時觸發 ──
def test_complete_day_advance_triggers():
    go, why = st.should_trigger(_m("2026-10-13"), _m("2026-10-12"))
    assert go and "2026-10-12 → 2026-10-13" in why


def test_first_publish_without_published_manifest_triggers():
    assert st.should_trigger(_m("2026-10-13"), None)[0]
    assert st.should_trigger(_m("2026-10-13"), {})[0]


def test_same_day_republish_or_older_day_does_not_trigger():
    assert not st.should_trigger(_m("2026-10-12"), _m("2026-10-12"))[0]          # 同日內容更正的重發：不空跑
    assert not st.should_trigger(_m("2026-10-09"), _m("2026-10-12"))[0]          # 倒退（閘門會擋，這裡也不觸發）


def test_event_gap_blocks_trigger_so_the_daily_list_is_not_frozen_on_wrong_adjusted_prices():
    go, why = st.should_trigger(_m("2026-10-13", ["2026-10-13"]), _m("2026-10-12"))
    assert not go and "事件還沒涵蓋" in why and "2026-10-13" in why


def test_gap_cleared_later_same_day_triggers_once():
    # 先前那班因事件缺口沒觸發（已發佈的 manifest 帶著缺口）；事件補齊後補觸發；觸發之後（已發佈無缺口）就不再觸發
    assert st.should_trigger(_m("2026-10-13"), _m("2026-10-13", ["2026-10-13"]))[0]
    assert not st.should_trigger(_m("2026-10-13"), _m("2026-10-13"))[0]


def test_missing_complete_day_never_triggers():
    assert not st.should_trigger({}, _m("2026-10-12"))[0]
    assert not st.should_trigger({"complete_day": ""}, None)[0]


# ── 呼叫 workflow_dispatch ──
class _Resp:
    def __init__(self, body=b"{}", status=200):
        self._b, self.status = body, status

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(branch_body=b'{"default_branch": "master"}', post=None, record=None):
    def op(url, pat, method="GET", data=None):
        if record is not None:
            record.append((method, url, data))
        if method == "GET":
            if isinstance(branch_body, Exception):
                raise branch_body
            return _Resp(branch_body)
        if isinstance(post, Exception):
            raise post
        return post or _Resp(status=204)
    return op


def test_dispatch_success_uses_default_branch_from_api():
    rec = []
    ok, msg = st.dispatch("pat", _opener(b'{"default_branch": "trunk"}', record=rec))
    assert ok and "trunk" in msg
    method, url, data = rec[-1]
    assert method == "POST" and url.endswith("/actions/workflows/daily.yml/dispatches") and json.loads(data) == {"ref": "trunk"}


def test_default_branch_falls_back_to_master_when_api_fails():
    assert st.default_branch("pat", _opener(OSError("boom"))) == "master"
    assert st.default_branch("pat", _opener(b"{}")) == "master"


def test_dispatch_failures_return_false_and_never_raise():
    err = urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b'{"message":"Not Found"}'))
    ok, msg = st.dispatch("pat", _opener(post=err))
    assert not ok and "404" in msg and "Not Found" in msg                         # workflow 改名／權限不足
    ok, msg = st.dispatch("pat", _opener(post=OSError("timeout")))
    assert not ok and "OSError" in msg
    ok, _ = st.dispatch("pat", _opener(post=_Resp(status=200)))
    assert not ok                                                                   # 非 204 不算成功


# ── CLI ──
def _write(tmp_path, name, d):
    p = tmp_path / name
    p.write_text(json.dumps(d), encoding="utf-8")
    return str(p)


def test_main_default_only_prints_decision_and_never_dispatches(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(st, "dispatch", lambda *a, **k: pytest.fail("預設不該呼叫"))
    new, old = _write(tmp_path, "n.json", _m("2026-10-13")), _write(tmp_path, "o.json", _m("2026-10-12"))
    assert st.main(["--new", new, "--old", old]) == 0
    assert "觸發" in capsys.readouterr().out


def test_main_dispatch_calls_only_when_decision_is_go_and_pat_present(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(st, "dispatch", lambda pat: calls.append(pat) or (True, "HTTP 204"))
    new, old = _write(tmp_path, "n.json", _m("2026-10-13")), _write(tmp_path, "o.json", _m("2026-10-12"))
    monkeypatch.delenv("SWING_PAT", raising=False)
    assert st.main(["--new", new, "--old", old, "--dispatch"]) == 0 and calls == []            # 沒 PAT：警告、不呼叫、結束碼 0
    assert "TWSWING_DISPATCH_PAT 沒設" in capsys.readouterr().out
    monkeypatch.setenv("SWING_PAT", " tok \n")
    assert st.main(["--new", new, "--old", old, "--dispatch"]) == 0 and calls == ["tok"]
    same = _write(tmp_path, "s.json", _m("2026-10-13"))
    assert st.main(["--new", new, "--old", same, "--dispatch"]) == 0 and calls == ["tok"]      # 完整日沒前進：不再呼叫


def test_main_failure_and_unreadable_manifest_never_fail_the_workflow(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SWING_PAT", "tok")
    monkeypatch.setattr(st, "dispatch", lambda pat: (False, "HTTP 403：Resource not accessible"))
    new = _write(tmp_path, "n.json", _m("2026-10-13"))
    assert st.main(["--new", new, "--dispatch"]) == 0
    assert "觸發 tw-swing 失敗" in capsys.readouterr().out
    assert st.main(["--new", str(tmp_path / "nope.json"), "--dispatch"]) == 0                  # 讀不到 manifest 也是 0
    assert "讀不到新 manifest" in capsys.readouterr().out
