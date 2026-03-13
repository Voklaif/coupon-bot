# AI Workflow Playbook

## 1) Feature framing prompt

Use this structure before implementation:

1. Objective and user impact.
2. Current state summary from repo.
3. Required outputs (code, tests, docs, scripts).
4. Constraints (non-breaking, homelab deploy, security).
5. Done criteria with exact checks.

## 2) Verification checklist (must pass)

- Syntax/compile checks pass.
- Tests relevant to changed behavior pass.
- Config and secrets are not committed.
- Docs/runbooks updated for operational changes.
- Healthchecks and observability updated when runtime behavior changes.

## 3) Trust vs verify rules

- Trust AI for scaffolding and repetitive edits.
- Verify AI for:
  - auth/security code
  - date/time logic
  - shell scripts affecting data
  - deployment steps
- Require at least one executable validation command for every major AI-generated change.

## 4) Failure patterns to watch

- Hidden assumptions about env vars and file paths.
- Silent error handling that masks production failures.
- Incomplete rollback/backups around DB changes.
- Missing tests for edge-case date parsing and auth paths.

## 5) Manual vs CI/CD (learning track)

Manual first (now):
- better for understanding compose, logs, health, and recovery.

CI/CD next:
- add tag-triggered pipeline that runs tests then deploy script with manual approval gate.
- keep rollback path documented and tested.
