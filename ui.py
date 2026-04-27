import sys

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
    layer_color = {"UI": CYAN, "API": BLUE, "CLI": GREEN}
    print(f"\n  {BOLD}{'#':<4}  {'Layer':<5}  {'Status':<10}  {'Dur':>7}  {'Test Name'}{RESET}")
    print(f"  {'─'*4}  {'─'*5}  {'─'*10}  {'─'*7}  {'─'*52}")
    for i, t in enumerate(failed, 1):
        parts  = t["class_name"].lower().split(".")
        layer  = next((p.upper() for p in parts if p in ("ui", "api", "cli")), "???")
        lcolor = layer_color.get(layer, DIM)
        scolor = RED if t["status"] == "FAILED" else YELLOW
        dur    = f"{t.get('duration', 0)}s"
        name   = t["name"]
        if len(name) > 49:
            name = name[:46] + "..."
        print(f"  {BOLD}{i:<4}{RESET}  {lcolor}{layer:<5}{RESET}  {scolor}{t['status']:<10}{RESET}  {DIM}{dur:>7}{RESET}  {name}")
        module = t["class_name"].split(".")[-1] if t["class_name"] else ""
        if module:
            print(f"  {'':4}  {'':5}  {'':10}  {'':7}  {DIM}{module}{RESET}")
        if t["error"]:
            snippet = t["error"].splitlines()[0][:78]
            print(f"  {'':4}  {'':5}  {'':10}  {'':7}  {RED}{snippet}{RESET}")
        print()
    print()


def ask_test_selection(failed):
    n = len(failed)
    while True:
        raw = _tty_input(
            f"  {YELLOW}>>{RESET} Select test to analyze"
            f" (1-{n}, comma-separated, or 'all'): "
        ).strip().lower()
        if raw == "all":
            return failed
        parts = [p.strip() for p in raw.split(",")]
        indices, valid = [], True
        for p in parts:
            if p.isdigit() and 1 <= int(p) <= n:
                indices.append(int(p) - 1)
            else:
                print(f"  {RED}Invalid choice '{p}'.{RESET} Enter numbers between 1 and {n}, or 'all'.")
                valid = False
                break
        if valid and indices:
            return [failed[i] for i in indices]
