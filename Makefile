# Oh Sheet — top-level orchestrator.
# Backend (Python): pyproject.toml + tests/ at the repo root, package at backend/.
# Frontend (Flutter): everything under frontend/.

FRONTEND := frontend

# Override on the command line, e.g.:
#   make frontend DEVICE=ios
#   make frontend API_BASE_URL=http://192.168.1.42:8000
#   make frontend FLUTTER=/opt/flutter/bin/flutter
DEVICE       ?= chrome
API_BASE_URL ?=
HOST         ?= 0.0.0.0
PORT         ?= 8000
FLUTTER      ?= flutter

DART_DEFINE := $(if $(API_BASE_URL),--dart-define=API_BASE_URL=$(API_BASE_URL),)

.PHONY: help install install-backend install-mt3 install-frontend backend frontend test test-backend lint typecheck clean require-flutter require-port-free

help:
	@echo "Oh Sheet — make targets"
	@echo ""
	@echo "  make install            full install: backend + MT3 deps + flutter pub get"
	@echo "  make install-backend    pip install -e .[dev]  (API only — TranscribeService"
	@echo "                          will fall back to a 4-note stub without MT3)"
	@echo "  make install-mt3        pip install -e .[mt3]  (torch + note-seq, ~2 GB)"
	@echo "  make install-frontend   $(FLUTTER) pub get inside frontend/"
	@echo ""
	@echo "  make backend            run uvicorn dev server on $(HOST):$(PORT)"
	@echo "  make frontend           $(FLUTTER) run -d $(DEVICE) (override DEVICE=ios|android|macos|...)"
	@echo "                          set API_BASE_URL=http://host:port to point at a non-default backend"
	@echo "                          set FLUTTER=/path/to/flutter if the SDK is not on your PATH"
	@echo ""
	@echo "  make test               run backend pytest suite"
	@echo "  make lint               $(FLUTTER) analyze"
	@echo "  make clean              remove build artifacts and the local blob store"

# ---- install ----------------------------------------------------------------

install: install-backend install-mt3 install-frontend

require-flutter:
	@if [ -x "$(FLUTTER)" ] || command -v "$(FLUTTER)" >/dev/null 2>&1; then \
		:; \
	else \
		echo "Flutter SDK not found."; \
		echo "Install Flutter and make sure its bin directory is on your PATH."; \
		echo "Or rerun make with FLUTTER=/absolute/path/to/flutter."; \
		echo "Example: make frontend FLUTTER=\$$HOME/flutter/bin/flutter"; \
		exit 127; \
	fi

install-backend:
	pip install -e ".[dev]"

install-mt3:
	pip install -e ".[mt3]"

install-frontend: require-flutter
	cd $(FRONTEND) && $(FLUTTER) pub get

# ---- run --------------------------------------------------------------------

require-port-free:
	@if command -v lsof >/dev/null 2>&1 && lsof -tiTCP:$(PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "Port $(PORT) is already in use."; \
		echo "Stop the existing process or rerun with a different port, e.g. make backend PORT=8001"; \
		lsof -nP -iTCP:$(PORT) -sTCP:LISTEN; \
		exit 1; \
	fi

backend: require-port-free
	uvicorn backend.main:app --reload --host $(HOST) --port $(PORT)

frontend: require-flutter
	cd $(FRONTEND) && $(FLUTTER) run -d $(DEVICE) $(DART_DEFINE)

# ---- quality ----------------------------------------------------------------

test: test-backend

test-backend:
	pytest

lint:
	ruff check backend tests
	@$(MAKE) require-flutter
	cd $(FRONTEND) && $(FLUTTER) analyze

typecheck:
	mypy

# ---- housekeeping -----------------------------------------------------------

clean:
	rm -rf blob .pytest_cache backend/__pycache__ backend/**/__pycache__
	@if [ -x "$(FLUTTER)" ] || command -v "$(FLUTTER)" >/dev/null 2>&1; then \
		cd $(FRONTEND) && $(FLUTTER) clean; \
	fi
