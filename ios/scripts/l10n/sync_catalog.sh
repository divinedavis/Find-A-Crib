#!/usr/bin/env bash
# Merge the strings the compiler extracted on the last build (.stringsdata,
# written because SWIFT_EMIT_LOC_STRINGS=YES) into Shared/Localizable.xcstrings.
# Xcode's IDE does this on every build; xcodebuild does not, so the
# command-line flow is: build, then this, then scripts/l10n/translate.sh.
#
#   scripts/l10n/sync_catalog.sh [derived-data-path]   (default build/smoke)
#
# Apple: "Localizing and varying text with a string catalog"
#   https://developer.apple.com/documentation/xcode/localizing-and-varying-text-with-a-string-catalog
set -euo pipefail
cd "$(dirname "$0")/../.."
DD="${1:-build.nosync/smoke}"
# Only this build's app + widget targets (not the test bundles, not packages).
files=()
while IFS= read -r f; do files+=("$f"); done < <(
    find "$DD/Build/Intermediates.noindex/FindACrib.build" -name '*.stringsdata' \
        \( -path '*-iphone*/FindACrib.build/*' -o -path '*-iphone*/FindACribWidgets.build/*' \) 2>/dev/null)
# A source file that was deleted leaves its .stringsdata behind in derived
# data (and an older build may have left another architecture's copy): its
# strings would stay in the catalog forever. Keep only files whose Swift
# source still exists.
sources=$(find FindACrib Shared FindACribWidgets -name '*.swift' -exec basename {} .swift \; 2>/dev/null | sort -u)
kept=()
for f in "${files[@]}"; do
    grep -qxF "$(basename "$f" .stringsdata)" <<<"$sources" && kept+=("$f")
done
files=("${kept[@]}")
if [[ ${#files[@]} -eq 0 ]]; then
    echo "error: no .stringsdata under $DD — build the FindACrib scheme first" >&2
    exit 1
fi
xcrun xcstringstool sync Shared/Localizable.xcstrings --stringsdata "${files[@]}"
# English plural forms the source can't express (scripts/l10n/source_plurals.json:
# key -> {one, other}); the catalog then picks "1 result" / "2 results".
python3 - <<'PY'
import json
cat = json.load(open("Shared/Localizable.xcstrings"))
# Strings the code no longer has: gone from every language with them.
for key in [k for k, v in cat["strings"].items() if v.get("extractionState") == "stale"]:
    del cat["strings"][key]
for key, forms in json.load(open("scripts/l10n/source_plurals.json")).items():
    entry = cat["strings"].get(key)
    if entry is None:
        raise SystemExit(f"error: plural key no longer in the source: {key}")
    entry.setdefault("localizations", {})["en"] = {"variations": {"plural": {
        c: {"stringUnit": {"state": "translated", "value": v}} for c, v in forms.items()}}}
with open("Shared/Localizable.xcstrings", "w") as f:
    json.dump(cat, f, ensure_ascii=False, indent=2, sort_keys=True, separators=(",", " : "))
    f.write("\n")
PY
echo "synced $(python3 -c 'import json;print(len(json.load(open("Shared/Localizable.xcstrings"))["strings"]))') keys from ${#files[@]} stringsdata files"
