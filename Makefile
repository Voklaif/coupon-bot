SHELL := /bin/bash

ENV_DEV := .env.dev
ENV_PROD := .env.prod

compose-dev = docker compose --env-file $(ENV_DEV) -f compose.yml -f compose.dev.yml
compose-prod = docker compose --env-file $(ENV_PROD) -f compose.yml -f compose.prod.yml

.PHONY: dev-up dev-down dev-logs prod-plan prod-up prod-down test lint

dev-up:
	$(compose-dev) up -d --build

dev-down:
	$(compose-dev) down

dev-logs:
	$(compose-dev) logs -f --tail=200

prod-plan:
	$(compose-prod) config

prod-up:
	$(compose-prod) up -d --build

prod-down:
	$(compose-prod) down

lint:
	python3 -m py_compile coupon_bot.py coupon_ui.py tests/*.py

test:
	python3 -m pytest -q -s
