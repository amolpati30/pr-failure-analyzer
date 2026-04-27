import shutil
import subprocess
from datetime import datetime

from config import JENKINS_BASE_URL, CLAUDE_AGENT_NAME
from ui import header, warn, err


def build_test_context(test, pr, pr_diff, prt, build_info, console_section):
    build_detail = ""
    if build_info:
        ts  = build_info.get("timestamp", 0)
        dur = build_info.get("duration", 0)
        ts_s  = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts else "unknown"
        dur_s = f"{round(dur / 60000, 1)} min" if dur else "unknown"
        build_detail = f" | Started: {ts_s} | Duration: {dur_s}"

    lines = [
        "=" * 70,
        "  TEST FAILURE CONTEXT",
        "=" * 70,
        "",
        f"PR             : #{pr['number']} — {pr['title']}",
        f"Repository     : {pr['base']['repo']['full_name']}",
        f"Author         : {pr['user']['login']}",
        f"Branch         : {pr['head']['ref']} → {pr['base']['ref']}",
        f"PR URL         : {pr['html_url']}",
        "",
        f"Jenkins Job    : {prt.get('job_name', 'unknown')}",
        f"Build #        : {prt.get('build_number', 'unknown')}{build_detail}",
        f"Build Status   : {prt.get('build_status', 'unknown')}",
        f"Pytest command : {prt.get('pytest_args', '')}",
        f"Overall result : {prt.get('test_result', '')}",
        f"Jenkins URL    : {JENKINS_BASE_URL}/job/{prt.get('job_name','???')}/{prt.get('build_number','???')}/",
        "",
        "─── Failing Test ───────────────────────────────────────────────────────",
        f"Name       : {test['name']}",
        f"Class      : {test['class_name']}",
        f"Status     : {test['status']}",
        f"Duration   : {test.get('duration', 0)}s",
        "",
        "─── Error Message ──────────────────────────────────────────────────────",
        test["error"] or "(no error message captured)",
        "",
    ]

    if test["stacktrace"]:
        lines += [
            "─── Stack Trace ────────────────────────────────────────────────────────",
            test["stacktrace"],
            "",
        ]

    if console_section:
        lines += [
            "─── Console Log Excerpt (around test failure) ──────────────────────────",
            console_section,
            "",
        ]

    lines += [
        "─── PR Code Changes (diff) ─────────────────────────────────────────────",
        pr_diff[:6000] if pr_diff else "(no diff available)",
        "",
        "=" * 70,
    ]

    return "\n".join(lines)


def run_failure_analysis(context):
    if not shutil.which("claude"):
        warn("claude CLI not found — printing context only.")
        print(context)
        return

    header("Failure Analysis — test-failure-analyzer")
    proc = subprocess.Popen(
        ["claude", "-p", "--agent", CLAUDE_AGENT_NAME],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr_out = proc.communicate(input=context)
    print(stdout, end="", flush=True)
    if proc.returncode != 0 and stderr_out:
        err(stderr_out.strip())
    print()
