# Convenience commands for developing and grading the backend.
# On Windows without make, run the underlying commands directly
# (see README.md, Phase 10, for the copy-paste versions).

PYTHON = .venv/Scripts/python.exe
RUFF = .venv/Scripts/ruff.exe

# All targets assume the venv exists (created once with:
#   py -3.11 -m venv .venv
# from backend/ - see README.md). Windows note: run make from Git Bash.

.PHONY: dev-install run seed seed-fresh test coverage lint format check

dev-install:    ## Install runtime + test/lint deps into .venv
	.venv/Scripts/pip.exe install -e ".[dev]"

run:            ## Start the API (selector loop, MQTT subscriber via lifespan)
	$(PYTHON) run.py

seed:           ## Idempotent demo data (python -m app.seed)
	$(PYTHON) -m app.seed

seed-fresh:     ## WARNING: wipe all tables, then reseed the demo
	$(PYTHON) -m app.seed --fresh

test:           ## Fast feedback: full suite, no coverage
	$(PYTHON) -m pytest -q

coverage:       ## Full suite with coverage report
	$(PYTHON) -m pytest -q --cov=app

lint:           ## Ruff, no fixes
	$(RUFF) check app tests

format:         ## Ruff, autofix imports + fixables
	$(RUFF) check app tests --fix

check: lint test  ## Everything CI would run
