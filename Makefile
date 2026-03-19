SHELL := /bin/bash

.PHONY: up down logs ps config test lint

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

config:
	docker compose config

lint:
	python3 -m py_compile coupon_bot.py coupon_ui.py tests/*.py

test:
	python3 -m pytest -q -s
