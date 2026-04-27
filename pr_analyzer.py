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
import sys

import urllib3

from analysis import build_test_context, run_failure_analysis
from config import (
    GH_CREDS_FILE,
    JENKINS_BASE_URL,
    load_github_token,
    save_github_token,
)
from github import gh_get, gh_session
from jenkins import (
    jenkins_build_info,
    jenkins_console_text,
    jenkins_session,
    jenkins_test_results,
    resolve_job_name,
)
from prt import extract_console_snippet, extract_prt_info
from ui import (
    _tty_input,
    ask_text,
    err,
    header,
    info,
    ok,
    print_failed_tests_table,
    print_prs,
    warn,
    ask_test_selection,
    BOLD,
    RESET,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def cmd_setup(args):
    print(f"\n  GitHub Token Setup\n")
    print(f"  Get your token at: https://github.com/settings/tokens")
    print(f"  Required scopes: repo, read:org, read:user\n")
    gh_token = args.gh_token or _tty_input(f"  >> GitHub personal access token: ").strip()
    if not gh_token:
        err("GitHub token cannot be empty.")
        sys.exit(1)
    save_github_token(gh_token)
    ok(f"GitHub token saved to {GH_CREDS_FILE}")


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
        ok(f"PRT — Job: {BOLD}{prt.get('job_name','?')}{RESET}  "
           f"Build: {BOLD}#{prt.get('build_number','?')}{RESET}  "
           f"Status: {BOLD}{prt.get('build_status','?')}{RESET}")

    failed_tests = []
    console_text = None
    build_info   = None

    if prt.get("job_name") and prt.get("build_number"):
        job   = resolve_job_name(js, prt["job_name"])
        build = prt["build_number"]
        prt["job_name"] = job

        info(f"Jenkins build: {JENKINS_BASE_URL}/job/{job}/{build}/")

        info("Fetching structured test results ...")
        failed_tests = jenkins_test_results(js, job, build)

        info("Fetching build info ...")
        build_info = jenkins_build_info(js, job, build)

        info("Fetching console log ...")
        console_text = jenkins_console_text(js, job, build)
        if console_text:
            ok(f"Console log fetched ({len(console_text):,} chars).")
        else:
            warn("Console log unavailable (build may be too old).")

        if not failed_tests and not console_text:
            warn("No test results or console log — analysis based on PR diff and PRT summary only.")
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
        warn("No structured test results available. Outputting PRT + diff context.")
        selected_tests = [None]

    # ── Step 5: Analyze each selected test ───────────────────────────────────────
    if selected_tests and selected_tests[0] is None:
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
            build_info=build_info,
            console_section=console_text[-4000:] if console_text else "",
        )
        run_failure_analysis(fallback_context)
        return

    for test in selected_tests:
        console_section = extract_console_snippet(console_text, test["name"]) if console_text else ""
        context = build_test_context(test, pr, pr_diff, prt, build_info, console_section)
        run_failure_analysis(context)
        if len(selected_tests) > 1:
            print(f"\n{'─' * 70}\n")


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
