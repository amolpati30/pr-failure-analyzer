#!/usr/bin/env python3
"""
PR Failure Analyzer — Satellite QE
Fetches open PRs, identifies PRT Jenkins build, analyzes failures.

USAGE:
  # Interactive wizard:
  python3 ~/pr-analyzer/pr_analyzer.py

  # Non-interactive:
  python3 ~/pr-analyzer/pr_analyzer.py --repo SatelliteQE/robottelo --pr 21046

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


def ask_choice(prompt, choices, labels=None):
    labels = labels or choices
    print()
    for i, label in enumerate(labels, 1):
        print(f"  {BOLD}{i}{RESET}. {label}")
    print()
    while True:
        raw = _tty_input(f"  {YELLOW}>>{RESET} {prompt} (1-{len(choices)}): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        print(f"  {RED}Invalid.{RESET} Enter 1–{len(choices)}.")

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
    s.auth    = (user, token)
    s.verify  = False
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
    "test-robottelo":      "robottelo-pr-testing",
    "robottelo":           "robottelo-pr-testing",
    "robottelo-pr":        "robottelo-pr-testing",
}


def resolve_job_name(s, job_name):
    """Resolve trigger alias to real Jenkins job name."""
    resolved = KNOWN_JOB_ALIASES.get(job_name, job_name)
    r = s.get(f"{JENKINS_BASE_URL}/job/{resolved}/api/json", params={"tree": "name"}, timeout=10)
    if r.ok:
        return resolved
    # Fall back to original if alias didn't work either
    return job_name


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
                    "name":        case.get("name", ""),
                    "class_name":  case.get("className", ""),
                    "status":      case.get("status", ""),
                    "error":       (case.get("errorDetails") or "").strip(),
                    "stacktrace":  (case.get("errorStackTrace") or "").strip(),
                    "duration":    round(case.get("duration", 0), 2),
                })
    return failed

# ─── PRT parsing ─────────────────────────────────────────────────────────────────

def extract_prt_info(comments):
    """
    Scan PR comments for trigger + PRT result blocks.
    Returns dict with keys: job_name, build_number, build_status, pytest_args, test_result
    """
    info_map = {}
    for comment in comments:
        body = comment["body"]

        # Trigger comment: "trigger: test-robottelo"
        m = re.search(r"trigger:\s*(\S+)", body, re.IGNORECASE)
        if m:
            info_map["job_name"] = m.group(1).strip()

        # PRT result block
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


def extract_console_failures(console_text, max_lines=120):
    """Pull the most relevant failure sections from the console log."""
    if not console_text:
        return ""
    lines = console_text.splitlines()
    relevant = []
    capture = False
    for line in lines:
        if any(kw in line for kw in ("FAILED", "ERROR", "AssertionError", "ERRORS", "short test summary")):
            capture = True
        if capture:
            relevant.append(line)
        if len(relevant) >= max_lines:
            break
    return "\n".join(relevant)

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


def print_failed_tests(failed):
    if not failed:
        warn("No failed tests found in test report.")
        return
    print(f"\n  {BOLD}{'#':<4} {'Status':<12} {'Duration':>8}  Test{RESET}")
    print(f"  {'-'*4} {'-'*12} {'-'*8}  {'-'*55}")
    for i, t in enumerate(failed, 1):
        color = RED if t["status"] == "FAILED" else YELLOW
        print(f"  {BOLD}{i:<4}{RESET} {color}{t['status']:<12}{RESET} {DIM}{t['duration']}s{RESET:>8}  {t['name']}")
        dim(f"       {t['class_name']}")
        if t["error"]:
            dim(f"       {t['error'][:120]}")
    print()

# ─── Analysis output ─────────────────────────────────────────────────────────────

def build_analysis_prompt(pr, pr_diff, prt, failed_tests, console_failures):
    lines = [
        "=" * 70,
        f"  PR FAILURE ANALYSIS — #{pr['number']}: {pr['title']}",
        "=" * 70,
        "",
        f"Repository : {pr['base']['repo']['full_name']}",
        f"Author     : {pr['user']['login']}",
        f"Branch     : {pr['head']['ref']} → {pr['base']['ref']}",
        f"PR URL     : {pr['html_url']}",
        "",
    ]

    if prt:
        lines += [
            "─── PRT / Jenkins ──────────────────────────────────────────────────────",
            f"Job Name   : {prt.get('job_name', 'unknown')}",
            f"Build #    : {prt.get('build_number', 'unknown')}",
            f"Status     : {prt.get('build_status', 'unknown')}",
            f"Pytest     : {prt.get('pytest_args', '')}",
            f"Result     : {prt.get('test_result', '')}",
            f"Jenkins URL: {JENKINS_BASE_URL}/job/{prt.get('job_name', '???')}/{prt.get('build_number', '???')}/",
            "",
        ]

    lines += [
        "─── Code Changes (diff) ────────────────────────────────────────────────",
        pr_diff[:4000] if pr_diff else "(no diff available)",
        "",
    ]

    if failed_tests:
        lines += ["─── Failed Tests ───────────────────────────────────────────────────────"]
        for i, t in enumerate(failed_tests, 1):
            lines.append(f"\n[{i}] {t['class_name']}::{t['name']}")
            lines.append(f"    Status   : {t['status']}")
            lines.append(f"    Error    : {t['error']}")
            if t["stacktrace"]:
                lines.append(f"    Traceback:\n{t['stacktrace'][:800]}")
        lines.append("")

    if console_failures:
        lines += [
            "─── Console Log (failure excerpt) ──────────────────────────────────────",
            console_failures,
            "",
        ]

    lines += [
        "─── Analysis Request ───────────────────────────────────────────────────",
        "Please analyze the above PR diff and test failures, then:",
        "1. Identify the root cause of each test failure.",
        "2. Determine whether the failure is caused by the PR changes or pre-existing.",
        "3. Suggest a specific, actionable fix with code examples where applicable.",
        "=" * 70,
    ]

    return "\n".join(lines)

# ─── Setup ───────────────────────────────────────────────────────────────────────

def cmd_setup(args):
    print(f"\n{CYAN}{BOLD}  GitHub Token Setup{RESET}\n")
    print(f"  Get your token at: https://github.com/settings/tokens")
    print(f"  Required scopes: repo, read:org, read:user\n")
    if args.gh_token:
        token = args.gh_token
    else:
        token = _tty_input(f"  {YELLOW}>>{RESET} GitHub personal access token: ").strip()
    if not token:
        err("Token cannot be empty.")
        sys.exit(1)
    save_github_token(token)

# ─── Main workflow ───────────────────────────────────────────────────────────────

def run(args):
    # Load GitHub token
    gh_token = load_github_token()
    if not gh_token:
        err("No GitHub token found.")
        err("Run: python3 ~/pr-analyzer/pr_analyzer.py --setup  (or --setup --gh-token <tok>)")
        sys.exit(1)

    gs = gh_session(gh_token)
    js = jenkins_session()

    # Step 1: Repo
    header("PR Failure Analyzer — Satellite QE")
    if args.repo:
        repo = args.repo
    else:
        repo = ask_text("GitHub repo (e.g. SatelliteQE/robottelo)", default="SatelliteQE/robottelo")

    info(f"Fetching open PRs for {BOLD}{repo}{RESET} ...")
    prs = gh_get(gs, f"/repos/{repo}/pulls", params={"state": "open", "per_page": 50, "sort": "updated"})
    if not prs:
        err(f"No open PRs found or repo '{repo}' not accessible.")
        sys.exit(1)

    print_prs(prs)

    if args.list_prs:
        return

    # Step 2: PR number
    if args.pr:
        pr_num = args.pr
    else:
        raw = ask_text("Enter PR number to analyze")
        try:
            pr_num = int(raw)
        except ValueError:
            err("Invalid PR number.")
            sys.exit(1)

    # Fetch PR detail
    pr = gh_get(gs, f"/repos/{repo}/pulls/{pr_num}")
    if not pr:
        err(f"PR #{pr_num} not found.")
        sys.exit(1)

    ok(f"PR #{pr_num}: {pr['title']}")

    # Fetch diff
    info("Fetching PR diff ...")
    try:
        r = gs.get(pr["diff_url"], timeout=20)
        r.raise_for_status()
        pr_diff = r.text
    except Exception:
        pr_diff = ""
        warn("Could not fetch diff.")

    # Fetch comments to find PRT info
    info("Scanning PR comments for PRT results ...")
    comments = gh_get(gs, f"/repos/{repo}/issues/{pr_num}/comments", params={"per_page": 100}) or []
    prt = extract_prt_info(comments)

    if not prt:
        warn("No PRT trigger/result comment found on this PR.")
    else:
        job   = prt.get("job_name", "?")
        build = prt.get("build_number", "?")
        status = prt.get("build_status", "?")
        ok(f"PRT — Job: {BOLD}{job}{RESET}  Build: {BOLD}#{build}{RESET}  Status: {BOLD}{status}{RESET}")

    # Step 3: Jenkins analysis
    failed_tests    = []
    console_failures = ""

    if prt.get("job_name") and prt.get("build_number"):
        job   = resolve_job_name(js, prt["job_name"])
        build = prt["build_number"]
        prt["job_name"] = job  # update for output
        jenkins_url = f"{JENKINS_BASE_URL}/job/{job}/{build}/"
        info(f"Jenkins build: {jenkins_url}")

        info("Fetching test results from Jenkins ...")
        failed_tests = jenkins_test_results(js, job, build)
        if failed_tests:
            ok(f"Found {len(failed_tests)} failed test(s).")
            print_failed_tests(failed_tests)
        else:
            warn("No structured test results — falling back to console log.")

        info("Fetching console log ...")
        console_text     = jenkins_console(js, job, build)
        console_failures = extract_console_failures(console_text)
    else:
        warn("Skipping Jenkins analysis (no build info found).")

    # Step 4: Print analysis prompt
    header("Analysis Output")
    prompt = build_analysis_prompt(pr, pr_diff, prt, failed_tests, console_failures)
    print(prompt)


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="PR Failure Analyzer — GitHub + Jenkins",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--setup",     action="store_true", help="Save GitHub token to config")
    parser.add_argument("--gh-token",  metavar="TOKEN",     help="GitHub token (for --setup)")
    parser.add_argument("--repo",      metavar="OWNER/REPO",help="GitHub repository")
    parser.add_argument("--pr",        type=int,            help="PR number to analyze")
    parser.add_argument("--list-prs",  action="store_true", help="List open PRs and exit")
    args = parser.parse_args()

    if args.setup:
        cmd_setup(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
