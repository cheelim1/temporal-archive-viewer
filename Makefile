VENV := .venv
STREAMLIT := $(VENV)/bin/streamlit
PYTEST := $(VENV)/bin/pytest
PORT ?= 8501
PID_FILE := .streamlit.pid
LOG_FILE := .streamlit.log

# Checks the PID file points at a *live streamlit process*, not just a live
# PID — a dead PID can be recycled by an unrelated process by the OS, which
# would otherwise make `kill -0` alone falsely report "already running".
IS_RUNNING = test -f $(PID_FILE) && ps -p "$$(cat $(PID_FILE))" -o command= 2>/dev/null | grep -q streamlit

.PHONY: setup run start stop restart status logs test clean clean-cache

$(STREAMLIT): requirements.txt
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip -q
	$(VENV)/bin/pip install -r requirements.txt -q
	touch $(STREAMLIT)

setup: $(STREAMLIT)
	@echo "Environment ready. Run 'make run' (foreground) or 'make start' (background)."

run: $(STREAMLIT)
	$(STREAMLIT) run Home.py --server.port=$(PORT)

start: $(STREAMLIT)
	@if $(IS_RUNNING); then \
		echo "Already running (PID $$(cat $(PID_FILE))) — http://localhost:$(PORT)"; \
	else \
		rm -f $(PID_FILE); \
		nohup $(STREAMLIT) run Home.py --server.port=$(PORT) --server.headless=true > $(LOG_FILE) 2>&1 & \
		echo $$! > $(PID_FILE); \
		sleep 1; \
		echo "Started (PID $$(cat $(PID_FILE))) — http://localhost:$(PORT)  (logs: make logs)"; \
	fi

stop:
	@if $(IS_RUNNING); then \
		kill $$(cat $(PID_FILE)); \
		echo "Stopped (PID $$(cat $(PID_FILE)))."; \
	else \
		echo "Not running."; \
	fi; \
	rm -f $(PID_FILE)

restart: stop start

status:
	@if $(IS_RUNNING); then \
		echo "Running (PID $$(cat $(PID_FILE))) — http://localhost:$(PORT)"; \
	else \
		echo "Not running."; \
	fi

logs:
	@touch $(LOG_FILE)
	tail -f $(LOG_FILE)

test: $(STREAMLIT)
	@$(VENV)/bin/pip show pytest > /dev/null 2>&1 || $(VENV)/bin/pip install -q pytest
	$(PYTEST) -q

clean: stop
	rm -rf $(VENV) $(LOG_FILE)
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

clean-cache:
	rm -rf ~/.cache/temporal-archive-viewer
