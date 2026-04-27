import sys

import requests

from config import JENKINS_BASE_URL, JENKINS_CREDS_FILE, load_jenkins_creds
from ui import err, warn, ok

KNOWN_JOB_ALIASES = {
    "test-robottelo": "robottelo-pr-testing",
    "robottelo":      "robottelo-pr-testing",
    "robottelo-pr":   "robottelo-pr-testing",
}


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


def resolve_job_name(s, job_name):
    resolved = KNOWN_JOB_ALIASES.get(job_name, job_name)
    r = s.get(f"{JENKINS_BASE_URL}/job/{resolved}/api/json", params={"tree": "name"}, timeout=10)
    return resolved if r.ok else job_name


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


def jenkins_build_info(s, job_name, build_number):
    return jenkins_get(s, f"job/{job_name}/{build_number}/api/json")


def jenkins_console_text(s, job_name, build_number):
    url = f"{JENKINS_BASE_URL}/job/{job_name}/{build_number}/consoleText"
    try:
        r = s.get(url, timeout=60)
        r.raise_for_status()
        return r.text
    except Exception as e:
        warn(f"Could not fetch console log: {e}")
        return None
