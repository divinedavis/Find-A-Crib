# Sourced by run_tests.sh, smoke_test.sh and ship.sh: what makes a Debug
# simulator build cheap on this Mac (owner, 2026-10-18: "use hardware more
# effectively"). Not used for the Release archive.
#
# Ships run from fresh git worktrees, so each one used to start with an empty
# DerivedData: every package (supabase-swift, Google Mobile Ads) re-cloned and
# every file compiled from nothing. Two caches outlive the worktree:
#   - FAC_CACHE/spm: the cloned Swift packages (-clonedSourcePackagesDirPath);
#   - FAC_CACHE/cas: Xcode 26's compilation cache, keyed by file contents, so
#     a new worktree reuses what an older one already compiled.
# ARCHS=arm64: the generic simulator destination otherwise builds x86_64 too,
# twice the compiling for a slice this Apple-silicon Mac never runs.
# COMPILER_INDEX_STORE_ENABLE=NO: the index only feeds the Xcode editor;
# writing it during a command-line build is pure overhead.
# ENABLE_DEBUG_DYLIB=NO: `simctl launch` rejects the debug-dylib layout, so
# building tests this way lets smoke_test.sh launch the tests' own app
# instead of compiling a second copy.
FAC_CACHE="${FAC_CACHE:-$HOME/Library/Caches/findacrib-build}"
mkdir -p "$FAC_CACHE/spm" "$FAC_CACHE/cas"
FAST_FLAGS=(-clonedSourcePackagesDirPath "$FAC_CACHE/spm" -skipPackageUpdates
  COMPILATION_CACHE_ENABLE_CACHING=YES COMPILATION_CACHE_CAS_PATH="$FAC_CACHE/cas"
  COMPILER_INDEX_STORE_ENABLE=NO ENABLE_DEBUG_DYLIB=NO ARCHS=arm64)
