# AGENTS.md

## Objective
Investigate why the scheduled run did not trigger, even though the code works when run manually.

## Context
The project runs successfully in a manual execution, but it failed to execute at the scheduled time.

## What to check
- Identify how scheduling is implemented
- Check the scheduler entry point
- Check cron / task scheduler / GitHub Actions / cloud scheduler configuration
- Verify timezone assumptions
- Check environment variables and secrets available during scheduled runs
- Check working directory / file path differences between manual and scheduled execution
- Check logs, error handling, and whether failures are silently swallowed
- Check dependency availability in the scheduled environment
- Check whether the scheduled command points to the correct Python file / function
- Check whether the process exits before the scheduler starts
- Check whether market-hours / date / holiday logic is blocking execution

## Rules
- Do NOT modify code unless explicitly asked
- First diagnose and explain the root cause
- If the root cause is unclear, list the top likely causes with evidence from the repo
- Suggest the smallest safe fix

## Output
Provide:
1. How scheduling is currently implemented
2. Why manual run works but scheduled run failed
3. Most likely root cause
4. Exact files/lines involved
5. Recommended fix
6. Any logging improvements needed
