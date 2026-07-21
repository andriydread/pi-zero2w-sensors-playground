# Air Monitor — deploy and service management.
#
# Override the target Pi like:  make deploy PI=pi@192.168.1.50
PI      ?= pi@pizero.local
APP_DIR ?= ~/air_station
SSH      = ssh $(PI)

.PHONY: help deploy deploy-full install restart start stop status logs logs-web pull-data venv

help: ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

venv: ## Create a local virtualenv and install dependencies
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

deploy: ## Sync code to the Pi and restart both services
	rsync -avz --delete --filter="merge .rsync-filter" ./ $(PI):$(APP_DIR)
	$(SSH) "cd $(APP_DIR) && .venv/bin/pip install -q -r requirements.txt"
	$(SSH) "sudo systemctl restart airmonitor.service airmonitor-web.service"
	@echo "Deployed and restarted."

deploy-full: deploy ## Deploy + install updated systemd service files
	$(SSH) "sudo cp $(APP_DIR)/systemd/airmonitor.service $(APP_DIR)/systemd/airmonitor-web.service /etc/systemd/system/ \
		&& sudo systemctl daemon-reload \
		&& sudo systemctl restart airmonitor.service airmonitor-web.service"

install: ## First-time setup on the Pi (venv, deps, systemd units)
	rsync -avz --filter="merge .rsync-filter" ./ $(PI):$(APP_DIR)
	$(SSH) "cd $(APP_DIR) && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
	$(SSH) "sudo cp $(APP_DIR)/systemd/airmonitor.service $(APP_DIR)/systemd/airmonitor-web.service /etc/systemd/system/ \
		&& sudo systemctl daemon-reload \
		&& sudo systemctl enable --now airmonitor.service airmonitor-web.service"

restart: ## Restart collector + dashboard on the Pi
	$(SSH) "sudo systemctl restart airmonitor.service airmonitor-web.service"

start: ## Start collector + dashboard on the Pi
	$(SSH) "sudo systemctl start airmonitor.service airmonitor-web.service"

stop: ## Stop collector + dashboard on the Pi
	$(SSH) "sudo systemctl stop airmonitor.service airmonitor-web.service"

status: ## Show service status on the Pi
	$(SSH) "systemctl status airmonitor.service airmonitor-web.service --no-pager" || true

logs: ## Tail the collector log on the Pi
	$(SSH) "tail -n 100 -f $(APP_DIR)/data/logs/collector.log"

logs-web: ## Tail the dashboard log on the Pi
	$(SSH) "tail -n 100 -f $(APP_DIR)/data/logs/dashboard.log"

pull-data: ## Copy database + logs from the Pi into ./from_pi/data
	mkdir -p from_pi/data
	rsync -avz $(PI):$(APP_DIR)/data/ from_pi/data/
