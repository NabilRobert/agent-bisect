# The one command: `make check`, run locally before every commit and in CI.
#
#   make check   lint, format, types, tests, secrets, public-repo check
#   make fix     format and auto-fix lint
#
# gitleaks is skipped with a note when it isn't installed locally; CI sets
# REQUIRE_TOOLS=1 and installs it, so nothing is skipped there.

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := check

UV ?= uv

.PHONY: check lint types test secrets public fix

check: lint types test secrets public
	@echo "make check: all steps passed"

lint:
	$(UV) run --frozen ruff check .
	$(UV) run --frozen ruff format --check .

types:
	$(UV) run --frozen pyright

test:
	$(UV) run --frozen pytest -q

secrets:
	@if command -v gitleaks >/dev/null; then \
		gitleaks git --no-banner --redact .; \
	elif [ "$${REQUIRE_TOOLS:-0}" = "1" ]; then \
		echo "gitleaks is required here but not installed"; exit 1; \
	else \
		echo "secrets: gitleaks not installed, skipped (CI runs it)"; \
	fi

public:
	$(UV) run --frozen python scripts/check_public.py

fix:
	$(UV) run --frozen ruff format .
	$(UV) run --frozen ruff check --fix .
