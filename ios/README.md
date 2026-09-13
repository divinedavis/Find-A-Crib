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

## Launch animation
`Design/LaunchPresentation.swift` adds a one-shot teal circle expansion and
logo-to-home fade (about one second). It reuses `BrandMark`, mounts the real
screen once underneath, and never waits for network requests. Only scale and
opacity animate; navigation and the inline Look Around panorama are unchanged.
Reduce Motion uses a short fade instead. Backgrounding cancels the intro without
replaying it on return, and animation completions cannot restart a finished intro.

Regression checks: `scripts/run_tests.sh FindACribTests/LaunchSequenceTests` and
`scripts/run_tests.sh FindACribUITests/LaunchAnimationTests`. Debug builds accept
`--reduce-launch-motion` to exercise the reduced-motion path. Verify cold launch
and interrupted launch on a physical iPhone too; simulator tests do not establish
device frame pacing.

## Sign-in
Profile and the results-list Alerts sign-in sheet share Apple and Google
buttons backed by the existing `AuthService` flows. The Alerts sheet also
keeps email/password, account creation, and password reset on the same screen;
it does not open the keyboard until the user selects an email field.
After successful authentication, alert preferences open only after sign-in
has dismissed. Cancelling returns to results without opening preferences.

Ship with `scripts/ship.sh` (tests, simulator smoke launch, archive, TestFlight).
