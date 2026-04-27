import re


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


def extract_console_snippet(console_text, test_name, context_lines=60):
    """Extract console lines around the specific test failure (FAILED/ERROR line)."""
    if not console_text:
        return ""
    lines = console_text.splitlines()
    short_name = test_name.split("::")[-1] if "::" in test_name else test_name
    idx = None
    for i, line in enumerate(lines):
        if short_name in line and any(kw in line for kw in ("FAILED", "ERROR", "error")):
            idx = i
            break
    if idx is None:
        return "\n".join(lines[-context_lines:])
    start = max(0, idx - context_lines // 2)
    end   = min(len(lines), idx + context_lines // 2)
    return "\n".join(lines[start:end])
