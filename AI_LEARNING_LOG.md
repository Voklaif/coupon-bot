# AI Learning Log

Use one entry per development session.

## Template

- Date:
- Goal:
- Prompt(s) used:
- What AI got wrong:
- How you verified it:
- Fix applied:
- Reusable rule:
- Time spent:

## Entry 1 (seed)

- Date: 2026-03-06
- Goal: introduce dev/prod compose separation + reliability baseline
- Prompt(s) used: high-level implementation plan with concrete deliverables
- What AI got wrong: attempted fragile UI HTML string escaping during refactor
- How you verified it: syntax check using `python3 -m py_compile`
- Fix applied: corrected rendering code and validated modules compile
- Reusable rule: always run syntax + targeted tests immediately after broad AI-generated refactors
- Time spent: ~1 session
