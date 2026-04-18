#!/usr/bin/env python3
"""
PR Failure Analyzer — Satellite QE
Fetches open PRs, identifies PRT Jenkins build, shows failed tests,
and feeds the selected test to the test-failure-analyzer agent.

USAGE:
  # Interactive wizard:
  python3 ~/pr-analyzer/pr_analyzer.py

  # Non-interactive:
  python3 ~/pr-analyzer/pr_analyzer.py --repo SatelliteQE/robottelo --pr 21046

  # Skip to specific test (1-based index, or 'all'):
  python3 ~/pr-analyzer/pr_analyzer.py --repo SatelliteQE/robottelo --pr 21046 --test 2

  # Just list PRs:
  python3 ~/pr-analyzer/pr_analyzer.py --repo SatelliteQE/robottelo --list-prs
"""

import argparse
import configparser
import os
import re
import sys
from datetime import datetime

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Config ─────────────────────────────────────────────────────────────────────

JENKINS_CREDS_FILE = os.path.expanduser("~/.config/rocket_jenkins.conf")
GH_CREDS_FILE      = os.path.expanduser("~/.config/pr_analyzer.conf")
JENKINS_BASE_URL   = "https://jenkins-csb-satellite-qe-satqe.dno.corp.redhat.com"

# ─── Colors ─────────────────────────────────────────────────────────────────────

BOLD   = "\033[1m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
RESET  = "\033[0m"
DIM    = "\033[2m"


def header(text):
    print(f"\n{CYAN}{'=' * 70}{RESET}")
    print(f"{CYAN}{BOLD}  {text}{RESET}")
    print(f"{CYAN}{'=' * 70}{RESET}\n")


def info(text):  print(f"  {BLUE}i{RESET}  {text}")
def ok(text):    print(f"  {GREEN}✓{RESET}  {text}")
def warn(text):  print(f"  {YELLOW}!{RESET}  {text}")
def err(text):   print(f"  {RED}✗{RESET}  {text}")
def dim(text):   print(f"  {DIM}{text}{RESET}")

# ─── TTY input ───────────────────────────────────────────────────────────────────

def _tty_input(prompt):
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        with open("/dev/tty", "r") as tty:
            return tty.readline().rstrip("\n")
    except OSError:
        return input()


def ask_text(prompt, default=None):
    hint = f" [{default}]" if default else ""
    while True:
        raw = _tty_input(f"  {YELLOW}>>{RESET} {prompt}{hint}: ").strip()
        if not raw and default:
            return default
        if raw:
            return raw
        print(f"  {RED}Value required.{RESET}")

# ─── Credentials ─────────────────────────────────────────────────────────────────

def load_github_token():
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    if os.path.exists(GH_CREDS_FILE):
        cfg = configparser.ConfigParser()
        cfg.read(GH_CREDS_FILE)
        token = cfg.get("credentials", "token", fallback="")
    return token


def save_github_token(token):
    os.makedirs(os.path.dirname(GH_CREDS_FILE), exist_ok=True)
    cfg = configparser.ConfigParser()
    cfg["credentials"] = {"token": token}
    with open(GH_CREDS_FILE, "w") as f:
        cfg.write(f)
    os.chmod(GH_CREDS_FILE, 0o600)
    ok(f"GitHub token saved to {GH_CREDS_FILE}")


def load_jenkins_creds():
    user  = os.environ.get("JENKINS_USER", "")
    token = os.environ.get("JENKINS_TOKEN", "")
    if user and token:
        return user, token
    if os.path.exists(JENKINS_CREDS_FILE):
        cfg = configparser.ConfigParser()
        cfg.read(JENKINS_CREDS_FILE)
        user  = cfg.get("credentials", "user",  fallback="")
        token = cfg.get("credentials", "token", fallback="")
    return user, token

# ─── GitHub session ──────────────────────────────────────────────────────────────

def gh_session(token):
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    return s


def gh_get(s, path, params=None):
    url = f"https://api.github.com{path}"
    try:
        r = s.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        err(f"GitHub API error {e.response.status_code}: {path}")
        return None
    except Exception as e:
        err(f"Request failed: {e}")
        return None

# ─── Jenkins session ─────────────────────────────────────────────────────────────

def jenkins_session():
    user, token = load_jenkins_creds()
    if not user or not token:
        err("Jenkins credentials not found.")
        err(f"Expected in {JENKINS_CREDS_FILE} or JENKINS_USER/JENKINS_TOKEN env vars.")
        sys.exit(1)
    s = requests.Session()
    s.auth   = (user, token)
    s.verify = False
    return s


def jenkins_get(s, path, params=None):
    url = f"{JENKINS_BASE_URL}/{path.lstrip('/')}"
    try:
        r = s.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        err(f"Jenkins API error {e.response.status_code}: {url}")
        return None
    except Exception as e:
        err(f"Jenkins request failed: {e}")
        return None


KNOWN_JOB_ALIASES = {
    "test-robottelo": "robottelo-pr-testing",
    "robottelo":      "robottelo-pr-testing",
    "robottelo-pr":   "robottelo-pr-testing",
}


def resolve_job_name(s, job_name):
    resolved = KNOWN_JOB_ALIASES.get(job_name, job_name)
    r = s.get(f"{JENKINS_BASE_URL}/job/{resolved}/api/json", params={"tree": "name"}, timeout=10)
    return resolved if r.ok else job_name


def jenkins_console(s, job_name, build_number):
    url = f"{JENKINS_BASE_URL}/job/{job_name}/{build_number}/consoleText"
    try:
        r = s.get(url, timeout=60)
        r.raise_for_status()
        return r.text
    except Exception as e:
        err(f"Could not fetch console log: {e}")
        return None


def jenkins_test_results(s, job_name, build_number):
    data = jenkins_get(
        s,
        f"job/{job_name}/{build_number}/testReport/api/json",
        params={"tree": "suites[cases[name,className,status,errorDetails,errorStackTrace,duration]]"},
    )
    if not data:
        return []
    failed = []
    for suite in data.get("suites", []):
        for case in suite.get("cases", []):
            if case.get("status") in ("FAILED", "REGRESSION"):
                failed.append({
                    "name":       case.get("name", ""),
                    "class_name": case.get("className", ""),
                    "status":     case.get("status", ""),
                    "error":      (case.get("errorDetails") or "").strip(),
                    "stacktrace": (case.get("errorStackTrace") or "").strip(),
                    "duration":   round(case.get("duration", 0), 2),
                })
    return failed

# ─── PRT parsing ─────────────────────────────────────────────────────────────────

def extract_prt_info(comments):
    info_map = {}
    for comment in comments:
        body = comment["body"]
        m = re.search(r"trigger:\s*(\S+)", body, re.IGNORECASE)
        if m:
            info_map["job_name"] = m.group(1).strip()
        if "PRT Result" in body or "Build Number:" in body:
            m = re.search(r"Build Number:\s*(\d+)", body)
            if m:
                info_map["build_number"] = int(m.group(1))
            m = re.search(r"Build Status:\s*(\S+)", body)
            if m:
                info_map["build_status"] = m.group(1).strip()
            m = re.search(r"PRT Comment:\s*(.+)", body)
            if m:
                info_map["pytest_args"] = m.group(1).strip()
            m = re.search(r"Test Result\s*:\s*(.+)", body)
            if m:
                info_map["test_result"] = m.group(1).strip()
    return info_map


def extract_test_console_section(console_text, test_name):
    """Extract the console log section relevant to a specific test name."""
    if not console_text:
        return ""
    lines = console_text.splitlines()
    # Find the block around FAILED <test_name>
    short_name = test_name.split("::")[-1] if "::" in test_name else test_name
    relevant, capturing, count = [], False, 0
    for i, line in enumerate(lines):
        if short_name in line or (capturing and count < 80):
            if not capturing:
                start = max(0, i - 5)
                relevant.extend(lines[start:i])
                capturing = True
            relevant.append(line)
            count += 1
        elif capturing and any(kw in line for kw in ("PASSED", "FAILED", "ERROR", "=====")):
            relevant.append(line)
            break
    # Also grab the short test summary section
    in_summary = False
    for line in lines:
        if "short test summary" in line:
            in_summary = True
        if in_summary:
            relevant.append(line)
        if in_summary and "===" in line and "short test summary" not in line:
            break
    return "\n".join(relevant[:150])

# ─── Display ─────────────────────────────────────────────────────────────────────

def print_prs(prs):
    print(f"\n  {BOLD}{'#':<8} {'Author':<20} {'Title'}{RESET}")
    print(f"  {'-'*8} {'-'*20} {'-'*50}")
    for pr in prs:
        num    = str(pr["number"])
        author = pr["user"]["login"]
        title  = pr["title"]
        if len(title) > 60:
            title = title[:57] + "..."
        color = CYAN if pr["user"]["login"] != "Satellite-QE" else DIM
        print(f"  {BOLD}{num:<8}{RESET} {color}{author:<20}{RESET} {title}")
    print()


def print_failed_tests_table(failed):
    """Print numbered table of failed tests for interactive selection."""
    layer_color = {"UI": CYAN, "API": BLUE, "CLI": GREEN}
    print(f"\n  {BOLD}{'#':<4}  {'Layer':<5}  {'Status':<10}  {'Dur':>6}  {'Test Name'}{RESET}")
    print(f"  {'─'*4}  {'─'*5}  {'─'*10}  {'─'*6}  {'─'*55}")
    for i, t in enumerate(failed, 1):
        parts  = t["class_name"].lower().split(".")
        layer  = next((p.upper() for p in parts if p in ("ui", "api", "cli")), "???")
        lcolor = layer_color.get(layer, DIM)
        scolor = RED if t["status"] == "FAILED" else YELLOW
        dur    = f"{t['duration']}s"
        name   = t["name"]
        if len(name) > 52:
            name = name[:49] + "..."
        print(f"  {BOLD}{i:<4}{RESET}  {lcolor}{layer:<5}{RESET}  {scolor}{t['status']:<10}{RESET}  {DIM}{dur:>6}{RESET}  {name}")
        module = t["class_name"].split(".")[-1] if t["class_name"] else ""
        if module:
            print(f"  {'':4}  {'':5}  {'':10}  {'':6}  {DIM}{module}{RESET}")
        if t["error"]:
            snippet = t["error"].splitlines()[0][:80] if t["error"] else ""
            print(f"  {'':4}  {'':5}  {'':10}  {'':6}  {RED}{snippet}{RESET}")
        print()
    print()


def ask_test_selection(failed):
    """Prompt user to pick one or more tests by index. Returns list of chosen tests."""
    n = len(failed)
    while True:
        raw = _tty_input(
            f"  {YELLOW}>>{RESET} Select test to analyze"
            f" (1-{n}, comma-separated, or 'all'): "
        ).strip().lower()
        if raw == "all":
            return failed
        parts = [p.strip() for p in raw.split(",")]
        indices = []
        valid = True
        for p in parts:
            if p.isdigit() and 1 <= int(p) <= n:
                indices.append(int(p) - 1)
            else:
                print(f"  {RED}Invalid choice '{p}'.{RESET} Enter numbers between 1 and {n}, or 'all'.")
                valid = False
                break
        if valid and indices:
            return [failed[i] for i in indices]

# ─── Per-test analysis context ───────────────────────────────────────────────────

def build_test_context(test, pr, pr_diff, prt, console_section):
    """Build the structured context string passed to the test-failure-analyzer agent."""
    lines = [
        "=" * 70,
        f"  TEST FAILURE CONTEXT",
        "=" * 70,
        "",
        f"PR             : #{pr['number']} — {pr['title']}",
        f"Repository     : {pr['base']['repo']['full_name']}",
        f"Author         : {pr['user']['login']}",
        f"Branch         : {pr['head']['ref']} → {pr['base']['ref']}",
        f"PR URL         : {pr['html_url']}",
        "",
        f"Jenkins Job    : {prt.get('job_name', 'unknown')}",
        f"Build #        : {prt.get('build_number', 'unknown')}",
        f"Build Status   : {prt.get('build_status', 'unknown')}",
        f"Pytest command : {prt.get('pytest_args', '')}",
        f"Overall result : {prt.get('test_result', '')}",
        f"Jenkins URL    : {JENKINS_BASE_URL}/job/{prt.get('job_name','???')}/{prt.get('build_number','???')}/",
        "",
        "─── Failing Test ───────────────────────────────────────────────────────",
        f"Name       : {test['name']}",
        f"Class      : {test['class_name']}",
        f"Status     : {test['status']}",
        f"Duration   : {test['duration']}s",
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
            "─── Console Log Excerpt (test-specific) ────────────────────────────────",
            console_section,
            "",
        ]

    lines += [
        "─── PR Code Changes (diff) ─────────────────────────────────────────────",
        pr_diff[:5000] if pr_diff else "(no diff available)",
        "",
        "=" * 70,
    ]

    return "\n".join(lines)

# ─── Setup ───────────────────────────────────────────────────────────────────────

def cmd_setup(args):
    print(f"\n{CYAN}{BOLD}  GitHub Token Setup{RESET}\n")
    print(f"  Get your token at: https://github.com/settings/tokens")
    print(f"  Required scopes: repo, read:org, read:user\n")
    token = args.gh_token or _tty_input(f"  {YELLOW}>>{RESET} GitHub personal access token: ").strip()
    if not token:
        err("Token cannot be empty.")
        sys.exit(1)
    save_github_token(token)

# ─── Main workflow ───────────────────────────────────────────────────────────────

def run(args):
    gh_token = load_github_token()
    if not gh_token:
        err("No GitHub token found.")
        err("Run: python3 ~/pr-analyzer/pr_analyzer.py --setup")
        sys.exit(1)

    gs = gh_session(gh_token)
    js = jenkins_session()

    # ── Step 1: Repo ─────────────────────────────────────────────────────────────
    header("PR Failure Analyzer — Satellite QE")
    repo = args.repo or ask_text("GitHub repo", default="SatelliteQE/robottelo")

    info(f"Fetching open PRs for {BOLD}{repo}{RESET} ...")
    prs = gh_get(gs, f"/repos/{repo}/pulls", params={"state": "open", "per_page": 50, "sort": "updated"})
    if not prs:
        err(f"No open PRs found or repo '{repo}' not accessible.")
        sys.exit(1)

    print_prs(prs)
    if args.list_prs:
        return

    # ── Step 2: PR number ────────────────────────────────────────────────────────
    if args.pr:
        pr_num = args.pr
    else:
        raw = ask_text("Enter PR number to analyze")
        try:
            pr_num = int(raw)
        except ValueError:
            err("Invalid PR number.")
            sys.exit(1)

    pr = gh_get(gs, f"/repos/{repo}/pulls/{pr_num}")
    if not pr:
        err(f"PR #{pr_num} not found.")
        sys.exit(1)
    ok(f"PR #{pr_num}: {pr['title']}")

    info("Fetching PR diff ...")
    try:
        r = gs.get(pr["diff_url"], timeout=20)
        r.raise_for_status()
        pr_diff = r.text
    except Exception:
        pr_diff = ""
        warn("Could not fetch diff.")

    # ── Step 3: PRT / Jenkins ────────────────────────────────────────────────────
    info("Scanning PR comments for PRT results ...")
    comments = gh_get(gs, f"/repos/{repo}/issues/{pr_num}/comments", params={"per_page": 100}) or []
    prt = extract_prt_info(comments)

    if not prt:
        warn("No PRT trigger/result comment found on this PR.")
        prt = {}
    else:
        job    = prt.get("job_name", "?")
        build  = prt.get("build_number", "?")
        status = prt.get("build_status", "?")
        ok(f"PRT — Job: {BOLD}{job}{RESET}  Build: {BOLD}#{build}{RESET}  Status: {BOLD}{status}{RESET}")

    failed_tests  = []
    console_text  = None

    if prt.get("job_name") and prt.get("build_number"):
        job   = resolve_job_name(js, prt["job_name"])
        build = prt["build_number"]
        prt["job_name"] = job

        info(f"Jenkins build: {JENKINS_BASE_URL}/job/{job}/{build}/")

        info("Fetching structured test results ...")
        failed_tests = jenkins_test_results(js, job, build)

        info("Fetching console log ...")
        console_text = jenkins_console(js, job, build)

        if not failed_tests and not console_text:
            warn("Build is too old — logs have been purged from Jenkins.")
            warn("Analysis will be based on PR diff and PRT summary only.")
    else:
        warn("Skipping Jenkins analysis (no build info in PR comments).")

    # ── Step 4: Test selection ───────────────────────────────────────────────────
    selected_tests = []

    if failed_tests:
        header(f"Failed Tests — Build #{prt.get('build_number', '?')}")
        print_failed_tests_table(failed_tests)

        if args.test:
            if str(args.test).lower() == "all":
                selected_tests = failed_tests
            else:
                try:
                    idx = int(args.test) - 1
                    if 0 <= idx < len(failed_tests):
                        selected_tests = [failed_tests[idx]]
                    else:
                        err(f"Test index {args.test} out of range (1–{len(failed_tests)}).")
                        sys.exit(1)
                except ValueError:
                    err(f"Invalid --test value: {args.test}")
                    sys.exit(1)
        else:
            selected_tests = ask_test_selection(failed_tests)
    else:
        # No structured results — use PRT summary + diff only
        warn("No structured test results available. Outputting PRT + diff context.")
        selected_tests = [None]

    # ── Step 5: Output context for each selected test ────────────────────────────
    header("Test Failure Context — for analysis agent")

    if selected_tests and selected_tests[0] is None:
        # Fallback: output what we have
        fallback_context = build_test_context(
            test={
                "name":       prt.get("pytest_args", "unknown"),
                "class_name": "",
                "status":     prt.get("build_status", "UNKNOWN"),
                "error":      prt.get("test_result", ""),
                "stacktrace": "",
                "duration":   0,
            },
            pr=pr, pr_diff=pr_diff, prt=prt,
            console_section="",
        )
        print(fallback_context)
        return

    for test in selected_tests:
        console_section = extract_test_console_section(console_text, test["name"]) if console_text else ""
        context = build_test_context(test, pr, pr_diff, prt, console_section)
        print(context)
        if len(selected_tests) > 1:
            print(f"\n{'─' * 70}\n")

# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="PR Failure Analyzer — GitHub + Jenkins",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--setup",    action="store_true",  help="Save GitHub token")
    parser.add_argument("--gh-token", metavar="TOKEN",      help="GitHub token (for --setup)")
    parser.add_argument("--repo",     metavar="OWNER/REPO", help="GitHub repository")
    parser.add_argument("--pr",       type=int,             help="PR number to analyze")
    parser.add_argument("--test",     metavar="N|all",      help="Test index to analyze (1-based) or 'all'")
    parser.add_argument("--list-prs", action="store_true",  help="List open PRs and exit")
    args = parser.parse_args()

    if args.setup:
        cmd_setup(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
