.PHONY: bootstrap quality test clean dev api web web-build status services-start services-restart services-stop services-status services-logs services-log-policy services-doctor

API_HOST ?= 127.0.0.1
API_PORT ?= 18500
VENV_DIR ?= $(if $(POLYMONITOR_VENV_DIR),$(POLYMONITOR_VENV_DIR),$(CURDIR)/.venv)
PYTHON ?= $(VENV_DIR)/bin/python
SERVICE ?= polydata-api.service
PYTEST_ARGS ?=

bootstrap:
	POLYMONITOR_VENV_DIR="$(VENV_DIR)" bash scripts/dev/bootstrap.sh

quality:
	POLYMONITOR_VENV_DIR="$(VENV_DIR)" bash scripts/qa/verify_clean_checkout.sh

test:
	PYTHONDONTWRITEBYTECODE=1 "$(PYTHON)" -m pytest -q $(PYTEST_ARGS)

clean:
	rm -rf -- artifacts test-results webpage/artifacts webpage/test-results webpage/playwright-report webpage/dist webpage/.next webpage/.vite webpage/node_modules/.vite .pytest_cache .ruff_cache __pycache__
	find agent scripts telegram tests -type d -name __pycache__ -prune -exec rm -rf -- {} +

dev:
	POLYDATA_PYTHON_BIN="$(PYTHON)" bash scripts/start_dashboard.sh

api:
	POLYDATA_PYTHON_BIN="$(PYTHON)" bash scripts/start_dashboard.sh

web:
	npm --prefix webpage run dev

web-build:
	cd webpage && npm run build

status:
	@echo "API health:"
	@curl -fsS "http://$(API_HOST):$(API_PORT)/health"
	@echo
	@echo "System health:"
	@curl -fsS "http://$(API_HOST):$(API_PORT)/system/health"
	@echo

services-start:
	systemctl --user start "$(SERVICE)"

services-restart:
	systemctl --user restart "$(SERVICE)"

services-stop:
	systemctl --user stop "$(SERVICE)"

services-status:
	systemctl --user --no-pager status "$(SERVICE)"

services-logs:
	journalctl --user-unit="$(SERVICE)" --since today -n 200 -f

# Host-wide journal policy; run explicitly on the production host.
services-log-policy:
	sudo install -D -m 644 deploy/journald/60-polymonitor.conf /etc/systemd/journald.conf.d/60-polymonitor.conf
	sudo systemctl restart systemd-journald.service

services-doctor:
	"$(PYTHON)" scripts/qa/check_systemd_units.py
	bash scripts/qa/verify_systemd_units.sh
