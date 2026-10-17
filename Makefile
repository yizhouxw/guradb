PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: help setup plan check check-docs check-bootstrap check-release

help:
	@echo "setup / plan / check / check-docs / check-bootstrap / check-release"

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements-dev.lock -r requirements-m0.lock
	.venv/bin/python scripts/harness.py install-git-hooks

plan:
	$(PYTHON) scripts/harness.py plan

check:
	$(PYTHON) scripts/harness.py check

check-docs:
	$(PYTHON) scripts/check_repository.py

check-bootstrap:
	$(PYTHON) scripts/harness.py check --scope bootstrap

check-release:
	$(PYTHON) scripts/harness.py check --scope release
