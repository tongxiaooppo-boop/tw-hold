"""以指定舊版引擎及現行輸入產生乾跑對照，不改動正式模組。"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reference import corporate_actions as ca


def old_engine():
    folder = ROOT / "_old"
    folder.mkdir(exist_ok=True)
    for name in ("detect", "val_card"):
        source = subprocess.check_output(
            ["git", "show", f"97e31b7:screener/{name}.py"], cwd=ROOT
        ).decode("utf-8")
        if name == "val_card":
            original = "from screener import detect as dt"
            if source.count(original) != 1:
                raise RuntimeError("舊版 detect import 與預期不同")
            source = source.replace(original, "import old_detect as dt")
        path = folder / f"old_{name}.py"
        path.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(f"old_{name}", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


def run(data):
    from val2_dryrun_cards import dump, timestamp
    started, clock = timestamp(), time.perf_counter()
    engine = old_engine()
    cards, errors = {}, []
    for cls in data["stocks"]:
        code = str(cls["ticker"])
        try:
            card = engine.build_card(
                data["q"].get(code), data["rev"].get(code),
                data["px"].get(code), data["per"].get(code), cls,
                share_events=ca._events(code),
            )
            prices = card.get("prices") or {}
            cards[code] = dict(position=card.get("position"), fair=prices.get("fair"),
                               method=card.get("method"), source=prices.get("source"),
                               no_price=card.get("no_price"))
        except Exception as exc:
            errors.append(dict(ticker=code, error=f"{type(exc).__name__}: {exc}"))
    meta = dict(started=started, ended=timestamp(), seconds=time.perf_counter()-clock,
                n_stocks=len(data["stocks"]), errors=errors)
    dump(ROOT / "_old/old_cards.json", cards)
    dump(ROOT / "_old/old_run.json", meta)
    return cards, meta


if __name__ == "__main__":
    from val2_dryrun_cards import load_inputs
    run(load_inputs(with_history=False))
