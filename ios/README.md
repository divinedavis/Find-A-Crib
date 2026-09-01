# Find A Crib — iOS

SwiftUI app (iOS 17+) over the same public dataset findacrib.com serves. The
UI follows StreetEasy's mobile app screen-for-screen: hero collage + search
form, results cards, map with price bubbles, building detail, My Activity,
Profile, floating pill tab bar.

## Layout
- `project.yml` — XcodeGen spec. Run `scripts/generate.sh` after adding files.
- `FindACrib/Design` — StreetEasy palette (`SE.*`), Source Sans 3 type, shared components.
- `FindACrib/Data` — `DataStore` (bundled seed + ETag refresh from findacrib.com), `Gunzip`, `SearchEngine`.
- `FindACrib/Services` — `Activity` (saves/searches/recents on disk), `ImageService` (Look Around snapshots, cached).
- `FindACrib/Features` — Search, Results (list + map + filters), Detail, Activity, Profile.
- `FindACrib/Resources/Data` — seed copies of `buildings.slim.json.gz`, `listings.json`, `s8.json`, `fmr.json`. Refresh with `scripts/refresh_data.sh` before a ship.

## Data
No API key anywhere in the app. It reads the four JSON files nginx already
serves to the web app, conditionally (`If-None-Match`), and caches them in
Application Support. Photos are Apple Look Around snapshots (no Google key).

## Loop
```
scripts/generate.sh
scripts/smoke_test.sh        # build + cold simctl launch (ENABLE_DEBUG_DYLIB=NO)
scripts/run_tests.sh         # unit + UI tests
```
Launch arguments for screenshots / tests: `--route results|map|detail[:bbl]`, `--tab activity|profile`.

## Not yet
- Sign-in + sync with the web app's `saved_buildings` (Supabase project `dbaifotzwlxjvsxjohjt`).
- App Store Connect record, TestFlight ship script.
