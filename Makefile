.PHONY: dev backend frontend install clean help

# Default target
help:
	@echo "YT Summarizer - Available commands:"
	@echo ""
	@echo "  make dev        - Run backend + frontend together"
	@echo "  make backend    - Run backend only (FastAPI)"
	@echo "  make frontend   - Run frontend only (React)"
	@echo "  make install    - Install all dependencies"
	@echo "  make docker-up  - Start with Docker Compose (dev)"
	@echo "  make docker-down - Stop Docker containers"
	@echo "  make clean      - Remove generated files"
	@echo ""

# Run backend + frontend concurrently
dev:
	@echo "Starting YT Summarizer..."
	@$(MAKE) -j2 backend frontend

# Backend: FastAPI
backend:
	@echo "Starting backend on http://localhost:8000"
	cd backend && .venv/Scripts/python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Frontend: React
frontend:
	@echo "Starting frontend on http://localhost:3000"
	cd frontend && npm run dev

# Install all dependencies
install:
	@echo "Installing backend dependencies..."
	cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	cd frontend && npm install

# Docker
docker-up:
	docker compose -f docker-compose.dev.yml up --build

docker-down:
	docker compose -f docker-compose.dev.yml down

docker-prod:
	docker compose up --build

# Clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf frontend/node_modules frontend/dist frontend/build
	rm -rf backend/.venv
