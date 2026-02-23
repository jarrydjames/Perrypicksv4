#!/bin/bash
# Start PerryPicks Dashboard
#
# This script starts both the backend API and frontend dev server.
#
# Usage:
#   ./start_dashboard.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Check for backend venv
if [ ! -d "../.venv" ]; then
    echo "Error: Main project venv not found."
    exit 1
fi

# Start backend in background
echo "Starting backend API..."
source ../.venv/bin/activate
cd backend
pip install -q fastapi uvicorn sqlalchemy 2>/dev/null || true

# Run backend
uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

# Wait for backend to start
sleep 2

# Start frontend
echo "Starting frontend..."
cd frontend

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install
fi

# Run frontend
npm run dev

# Cleanup on exit
trap "kill $BACKEND_PID 2>/dev/null" EXIT
