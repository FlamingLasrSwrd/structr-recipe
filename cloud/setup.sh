#!/bin/bash
# Setup script for a Claude Code cloud environment. Paste this whole file into the
# "Setup script" field of the environment dialog at claude.ai/code (see CLOUD.md).
#
# It runs as root before Claude starts, and its result is cached, so it does only what the VM
# needs and is quick: it must finish in about five minutes and must exit 0 (a non-zero exit
# stops the session from starting, so every step is best-effort).
#
# What it provides: the Python packages the project imports (the solver in its own
# virtualenv) and the two Docker images, so a session does not pay for pulling them. It does
# NOT start the stack (a cache keeps files, not running containers) and does not build any
# data: a session runs cloud/bootstrap.sh for that.
#
# Keep the image names and the pin below in step with docker-compose.yml and
# requirements-solver.txt.

# requests: everything needs it, and it is small, so it goes into the system Python.
python3 -m pip install -q --break-system-packages requests || true

# ortools: OPTIONAL (the CP-SAT solver behind mealplanner/planning/cpsat.py; without it those
# tests skip and everything else works). It pulls in numpy 2, which conflicts with packages the
# VM already has, so it goes into its own virtualenv, never the system Python. The venv is made
# without pip if python3-venv is missing (as on the maintainer's laptop) and filled with the
# system pip. Solver tests then run with /opt/solver-venv/bin/python.
python3 -m venv /opt/solver-venv 2>/dev/null || python3 -m venv --without-pip /opt/solver-venv || true
python3 -m pip --python /opt/solver-venv/bin/python install -q "ortools==9.15.6755" "requests>=2.31" || true

# Docker images (the daemon may need starting in a fresh VM).
if command -v docker >/dev/null 2>&1; then
  docker info >/dev/null 2>&1 || { service docker start >/dev/null 2>&1 || true; sleep 5; }
  docker pull neo4j:2025.12.1 || true
  docker pull structr/structr:6.0.0 || true
fi

exit 0
