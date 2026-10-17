#!/usr/bin/env bash
# Build and run scripts/l10n/translate.swift (Apple Translation, on this Mac).
# Needs macOS 26.4+ for TranslationSession(installedSource:target:preferredStrategy:).
#   scripts/l10n/translate.sh [--langs de,ja]
#   scripts/l10n/translate.sh texts IN.json OUT.json --langs de,fr-CA
#   scripts/l10n/translate.sh status
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p build/l10n
src=scripts/l10n/translate.swift bin=build/l10n/translate
if [[ ! -x $bin || $src -nt $bin ]]; then
    xcrun swiftc -O -target arm64-apple-macos26.4 "$src" -o "$bin"
fi
exec "$bin" "$@"
