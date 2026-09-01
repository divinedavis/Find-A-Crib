#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v xcodegen >/dev/null 2>&1 || { echo "xcodegen not found. brew install xcodegen"; exit 1; }
xcodegen generate
echo "Regenerated FindACrib.xcodeproj"
