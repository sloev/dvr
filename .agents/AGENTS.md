# Agent Rules for DVR Workspace

- **Task Management Routine**: Before undertaking any new implementation or debugging step, you MUST first add it to the `CHECKLIST.md` file as a `[ ]` TO-DO item. Once the task is completed, you MUST update the file to cross it off as `[x]`. This ensures strict traceability of all actions.
- **CI Validation Routine**: After pushing any changes to GitHub, agents MUST wait and monitor the GitHub Actions CI workflow to completion. You must meticulously check the CI logs for any errors, warnings, or annotations. If any are found, you must immediately spawn new tasks in `CHECKLIST.md` for fixing them.
