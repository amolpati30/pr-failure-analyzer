# PR Failure Analyzer

Analyzes GitHub PRs with Jenkins PRT failures for the Satellite QE team.

## Credentials

| What | Source |
|------|--------|
| GitHub token | `~/.config/pr_analyzer.conf` or `GITHUB_TOKEN` env var |
| Jenkins user/token | `~/.config/rocket_jenkins.conf` or `JENKINS_USER`/`JENKINS_TOKEN` env vars |

Jenkins credentials are shared with `rocket_jenkins_agent.py` — no extra setup needed.

## First-time GitHub token setup

```bash
python3 ~/pr-analyzer/pr_analyzer.py --setup
# or non-interactively:
python3 ~/pr-analyzer/pr_analyzer.py --setup --gh-token <token>
```

## Usage

```bash
# Interactive wizard (asks for repo + PR number):
python3 ~/pr-analyzer/pr_analyzer.py

# List open PRs for a repo:
python3 ~/pr-analyzer/pr_analyzer.py --repo SatelliteQE/robottelo --list-prs

# Full analysis for a specific PR:
python3 ~/pr-analyzer/pr_analyzer.py --repo SatelliteQE/robottelo --pr 21046
```

## Slash command

Inside a Claude Code session in this directory, run:

```
/analyze-pr
```

Claude will guide you through the workflow interactively.

## What it does

1. Lists open PRs for the selected repository
2. Fetches the PR diff
3. Scans PR comments for the PRT trigger and result (job name + build number)
4. Hits Jenkins API to fetch structured test failures and console log
5. Outputs a structured analysis prompt for Claude to reason over
