# Active Tasks

## Immediate setup

- [ ] Copy `.env.dev.example` -> `.env.dev` and set `UI_PASSWORD`
- [ ] Copy `config.example.dev.json` -> `config/config.json` and set API tokens
- [ ] Start dev stack: `make dev-up`
- [ ] Verify dashboard auth and bot `/status`

## Homelab preparation

- [ ] Create `.env.prod` from `.env.prod.example`
- [ ] Place production config at `config/config.json` on server
- [ ] Wire SWAG route to `coupon-ui:8080`
- [ ] Run first manual deployment with `DEPLOY_CHECKLIST.md`

## Learning loop (weekly)

- [ ] Run one feature with AI assistance
- [ ] Log prompt/failure/fix in `AI_LEARNING_LOG.md`
- [ ] Add one reusable rule to `PLAYBOOK_AI_WORKFLOW.md`
