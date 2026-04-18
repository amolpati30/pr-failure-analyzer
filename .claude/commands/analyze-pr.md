Analyze a GitHub PR's code changes and Jenkins PRT test failures end-to-end,
using the test-failure-analyzer agent to diagnose selected failures.

## Workflow

1. **Ask the user which repository** to analyze (e.g. `SatelliteQE/robottelo`).

2. **List open PRs** for that repo:
   ```bash
   python3 ~/pr-analyzer/pr_analyzer.py --repo <REPO> --list-prs
   ```

3. **Ask the user for the PR number** they want to analyze.

4. **Run the analyzer** to fetch PRT build info and display the failed tests table:
   ```bash
   python3 ~/pr-analyzer/pr_analyzer.py --repo <REPO> --pr <NUMBER>
   ```
   The script will interactively prompt for test selection. When running via Claude,
   use `--test <N>` or `--test all` to select non-interactively after confirming
   with the user which test(s) to analyze:
   ```bash
   python3 ~/pr-analyzer/pr_analyzer.py --repo <REPO> --pr <NUMBER> --test <N>
   ```

5. **Read the "TEST FAILURE CONTEXT" block** printed by the script. It contains:
   - PR metadata (repo, branch, author, diff)
   - PRT/Jenkins build details (job name, build number, status, pytest command)
   - Failing test name, class, error message, and full stack trace
   - Console log excerpt scoped to that specific test

6. **Invoke the test-failure-analyzer agent** with the full context block as the
   prompt. Pass all details: test name, error, stack trace, PR diff, and pytest
   command. Ask the agent to:
   - Identify the root cause
   - Determine if it's caused by the PR change or pre-existing
   - Suggest a specific, actionable fix with code examples

7. **Present the agent's analysis** to the user clearly.

## Notes
- Jenkins credentials: `~/.config/rocket_jenkins.conf`
- GitHub token: `~/.config/pr_analyzer.conf` or `GITHUB_TOKEN` env var
- If the build is too old and logs are purged, only the diff + PRT summary is available
- Always show the failed tests table to the user before asking for selection
