# PR Failure Analyzer

A CLI tool for the **Satellite QE** team that automates the investigation of GitHub pull request failures by correlating PR code changes with Jenkins PRT (Pull Request Testing) test failures, then feeding structured context to a Claude AI agent for root-cause analysis.

## How it works

1. Lists open PRs for a GitHub repository
2. Fetches the PR diff
3. Scans PR comments for the PRT trigger and result (job name + build number)
4. Hits the Jenkins API to fetch structured test failures and the console log
5. Builds a rich context document (PR metadata + diff + test error + stack trace + console excerpt)
6. Passes the context to the `test-failure-analyzer` Claude agent for analysis

## Project structure

```
pr_analyzer.py   # CLI entry point and main workflow
config.py        # Constants and credential loading/saving
ui.py            # Terminal colors, print helpers, interactive prompts
github.py        # GitHub API session and requests
jenkins.py       # Jenkins API session, test results, console log
prt.py           # PRT comment parsing and console snippet extraction
analysis.py      # Context builder and Claude agent invocation
```

## Requirements

- Python 3.9+
- `requests`, `urllib3` (see `requirements.txt`)
- The `claude` CLI (for AI analysis — optional, context is printed if absent)
- A GitHub personal access token
- Jenkins credentials (shared with `rocket_jenkins_agent.py` if already configured)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Credentials

### GitHub token (first-time setup)

```bash
python3 pr_analyzer.py --setup
# or non-interactively:
python3 pr_analyzer.py --setup --gh-token <token>
```

Token is saved to `~/conf/github.conf`.
Required scopes: `repo`, `read:org`, `read:user`.

### Jenkins credentials

Read from `~/conf/jenkins.conf` (shared with `rocket_jenkins_agent.py`) or from environment variables:

```bash
export JENKINS_USER=your-username
export JENKINS_TOKEN=your-api-token
```

## Usage

```bash
# Interactive wizard (prompts for repo and PR number):
python3 pr_analyzer.py

# List open PRs for a repository:
python3 pr_analyzer.py --repo SatelliteQE/robottelo --list-prs

# Analyze a specific PR:
python3 pr_analyzer.py --repo SatelliteQE/robottelo --pr 21046

# Analyze a specific failed test by index (1-based):
python3 pr_analyzer.py --repo SatelliteQE/robottelo --pr 21046 --test 2

# Analyze all failed tests:
python3 pr_analyzer.py --repo SatelliteQE/robottelo --pr 21046 --test all
```

### Inside a Claude Code session

```
/analyze-pr
```

Claude will guide you through the workflow interactively.

## Configuration reference

| Setting | Source                                                                                                                             |
|---------|------------------------------------------------------------------------------------------------------------------------------------|
| GitHub token | `~/conf/github.conf` → `[credentials] token` or `GITHUB_TOKEN` env var                                                             |
| Jenkins user | `~/conf/jenkins.conf` → `[credentials] user` or `JENKINS_USER` env var                                                             |
| Jenkins token | `~/conf/jenkins.conf` → `[credentials] token` or `JENKINS_TOKEN` env var                                                           |
| Jenkins base URL | Hardcoded in `config.py` (`JENKINS_BASE_URL`)                                                                                      |

## Known Jenkins job aliases

The tool automatically resolves short job names:

| Alias | Resolves to |
|-------|-------------|
| `test-robottelo` | `robottelo-pr-testing` |
| `robottelo` | `robottelo-pr-testing` |
| `robottelo-pr` | `robottelo-pr-testing` |
