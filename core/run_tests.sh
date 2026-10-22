#!/usr/bin/env bash
# L7 · CI entry: run the full core suite; exit non-zero on any failure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m pytest core/ -q
