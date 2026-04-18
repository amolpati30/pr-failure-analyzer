Analyze a GitHub PR's code changes and Jenkins PRT failures end-to-end.

## Workflow

1. **Ask the user which repository** they want to analyze (e.g. `SatelliteQE/robottelo`).

2. **List open PRs** for that repository using the GitHub MCP server or the `pr_analyzer.py` script:
   ```bash
   python3 ~/pr-analyzer/pr_analyzer.py --repo <REPO> --list-prs
   ```

3. **Ask the user for the PR number** they want to analyze.

4. **Run the full analysis** for that PR:
   ```bash
   python3 ~/pr-analyzer/pr_analyzer.py --repo <REPO> --pr <NUMBER>
   ```

5. **Read the analysis output** carefully. It contains:
   - The PR diff (code changes)
   - PRT result (build number, build status, test summary)
   - Jenkins job name and build number
   - Failed test names, error messages, and stack traces
   - Relevant console log excerpt

6. **Provide a thorough analysis**:
   - Identify each failing test and its root cause
   - Determine if the failure is caused by the PR changes or is pre-existing/flaky
   - Suggest a specific, actionable fix with code snippets
   - Flag any unrelated failures separately

## Notes
- Jenkins credentials are read from `~/.config/rocket_jenkins.conf`
- GitHub token is read from `~/.config/pr_analyzer.conf` or `GITHUB_TOKEN` env var
- If the PR has no PRT comment yet, only the diff analysis will be available
