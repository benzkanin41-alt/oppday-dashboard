from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception


ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "work" / "last_dashboard_update.json"

STEPS = [
    "work/build_bubble_dashboard.py",
    "work/enhance_dashboard_thailand_rates.py",
    "work/enhance_dashboard_interactive_v03.py",
    "work/enhance_dashboard_v04.py",
    "work/update_froth_components_fred.py",
    "work/update_current_market_indicators.py",
    "work/sync_latest_dashboard_summary.py",
    "work/rebuild_clean_macro.py",
    "work/patch_dashboard_full_price_universe.py",
    "work/rebuild_clean_interactive.py",
    "work/patch_thailand_heat_mai_treasury.py",
    "work/recalculate_eyg_latest_yields.py",
    "work/patch_mai_tradingview_history.py",
    "work/finalize_requested_dashboard_metrics.py",
    "work/refresh_ai_semiconductor_direct_data.py",
    "work/patch_meta_latest_release_capex.py",
    "work/fix_amzn_ai_direct.py",
    "work/rebuild_ai_direct_layout_v08.py",
    "work/fix_ai_spacing_and_manifest_order.py",
    "work/fix_ai_to_score_spacing.py",
    "work/clean_payload_user_text.py",
    "work/sync_latest_dashboard_summary.py",
    "work/validate_macro_v04_nonzero.py",
    "work/validate_froth_components_populated.py",
    "work/validate_current_market_indicators.py",
    "work/validate_current_summary_sync.py",
    "work/validate_thailand_heat_mai_treasury.py",
    "work/validate_mai_chart_history.py",
    "work/validate_ai_direct_v08.py",
    "work/validate_ai_direct_interactive.py",
    "work/validate_dashboard_v04.py",
    "work/validate_dashboard_v04b.py",
    "work/validate_requested_regressions.py",
    "work/validate_layout_manifest_order.py",
    "work/validate_final_dashboard.py",
    "work/validate_refresh_hard_guards.py",
]


STEP_TIMEOUTS = {
    "work/enhance_dashboard_v04.py": 720,
    "work/update_froth_components_fred.py": 180,
    "work/update_current_market_indicators.py": 180,
    "work/enhance_dashboard_interactive_v03.py": 420,
    "work/patch_dashboard_full_price_universe.py": 420,
    "work/patch_thailand_heat_mai_treasury.py": 180,
    "work/patch_mai_tradingview_history.py": 240,
}


def now_bangkok() -> str:
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d %H:%M:%S Bangkok")
        except ZoneInfoNotFoundError:
            pass
    return (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S Bangkok")


def run_step(script: str) -> dict[str, object]:
    cmd = [sys.executable, "-X", "utf8", script]
    env = os.environ.copy()
    env["BUBBLE_DASHBOARD_ROOT"] = str(ROOT)
    started = now_bangkok()
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=STEP_TIMEOUTS.get(script, 240),
    )
    output = proc.stdout[-6000:]
    result = {
        "script": script,
        "started_at": started,
        "returncode": proc.returncode,
        "output_tail": output,
    }
    if proc.returncode != 0:
        raise RuntimeError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    results = []
    status = {
        "status": "running",
        "started_at": now_bangkok(),
        "workspace": str(ROOT),
        "steps": results,
    }
    LOG.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        for step in STEPS:
            result = run_step(step)
            results.append(result)
            status["updated_at"] = now_bangkok()
            LOG.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        status["status"] = "ok"
        status["completed_at"] = now_bangkok()
    except Exception as exc:
        status["status"] = "failed"
        status["failed_at"] = now_bangkok()
        status["error"] = str(exc)
        LOG.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    LOG.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": status["status"], "completed_at": status["completed_at"], "steps": len(results)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
