# Oh Sheet — top-level orchestrator.
# Backend lives under backend/ (FastAPI + pytest).
# Frontend lives under frontend/ (Flutter cross-platform client).

BACKEND  := backend
FRONTEND := frontend

# Override on the command line, e.g.:
#   make frontend DEVICE=ios
#   make frontend API_BASE_URL=http://192.168.1.42:8000
DEVICE       ?= chrome
API_BASE_URL ?=
HOST         ?= 0.0.0.0
PORT         ?= 8000

DART_DEFINE := $(if $(API_BASE_URL),--dart-define=API_BASE_URL=$(API_BASE_URL),)

.PHONY: help install install-backend install-frontend backend frontend test test-backend lint clean

help:
	@echo "Oh Sheet — make targets"
	@echo ""
	@echo "  make install            install backend (editable) + flutter pub get"
	@echo "  make install-backend    pip install -e backend[dev]"
	@echo "  make install-frontend   flutter pub get inside frontend/"
	@echo ""
	@echo "  make backend            run uvicorn dev server on $(HOST):$(PORT)"
	@echo "  make frontend           flutter run -d $(DEVICE) (override DEVICE=ios|android|macos|...)"
	@echo "                          set API_BASE_URL=http://host:port to point at a non-default backend"
	@echo ""
	@echo "  make test               run backend pytest suite"
	@echo "  make lint               flutter analyze"
	@echo "  make clean              remove build artifacts and the local blob store"

# ---- install ----------------------------------------------------------------

install: install-backend install-frontend

install-backend:
	pip install -e "$(BACKEND)[dev]"

install-frontend:
	cd $(FRONTEND) && flutter pub get

# ---- run --------------------------------------------------------------------

backend:
	cd $(BACKEND) && uvicorn ohsheet.main:app --reload --host $(HOST) --port $(PORT)

frontend:
	cd $(FRONTEND) && flutter run -d $(DEVICE) $(DART_DEFINE)

# ---- quality ----------------------------------------------------------------

test: test-backend

test-backend:
	cd $(BACKEND) && pytest

lint:
	cd $(FRONTEND) && flutter analyze

# ---- housekeeping -----------------------------------------------------------

clean:
	rm -rf $(BACKEND)/blob $(BACKEND)/.pytest_cache $(BACKEND)/**/__pycache__
	cd $(FRONTEND) && flutter clean || true
