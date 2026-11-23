# Four models build the same iPad wall dashboard

**Evaluation date: November 22, 2026. Verdict: start the physical-iPad comparison with Opus 5.5.** It reproduced the approved layout closely, fetched weather for the intended place on the simulator, and retained the WeatherKit entitlement in the distribution build. MAI Code 2 reached upload, but its signed app lost that entitlement. Sol handled weather attribution and stale data well but stopped before upload. Qwen produced a convincing wall from fixtures; its first real install exposed a forecast location that was never set.

This is a comparison of **four implementations**, not a general model leaderboard. Three archives uploaded successfully. That is not three successful wall dashboards: nobody has completed the same physical-device acceptance pass across the four.

## What counted as success

The common starting commit in the Dash repository was `400571b` (no app). The contract was the **approved v6** in `docs/design-v0.md` and `mockups/dashboard-agenda-v6.{html,png}`, narrowed by the eight phase prompts in `docs/build-plan.md`. The earlier multi-view dashboard and groceries plan was superseded; the second screen was explicitly deferred. Neither is a missing feature here.

- **Read it from across a room:** one landscape screen on an iPad Air 3, 1112 × 834 points. Seven days starting today; a wide amber Today column; distinct weekends; equal-height agenda rows, compact times, past/NOW states, all-day items and whole-row overflow.
- **Show the right information:** EventKit events from the selected calendars. One designated calendar has a stricter privacy rule: show only events titled exactly `Work`, as small shift chips. Show today's WeatherKit forecast, retain last-known values on failure, and never leave a blank wall.
- **Leave it alone:** only two settings groups (units and calendars), applied live and persisted. Stay awake, refresh, roll past midnight, and show intelligible states when data or permission is missing.
- **Deliver in stages:** pass each phase's checks before committing. Finish with a signed TestFlight upload. Installation, wall-distance readability and sustained operation on the physical iPad are separate gates.

## Results at a glance

| Run · reviewed Dash commit | Layout and calendar | Forecast on the simulator | Release evidence · version 1.0 |
|---|---|---|---|
| **Qwen3.8 Flash Next FP4 Local** · `dash/qwen38` · `1dd3d7a` | Tuned geometry to the approved PNG; seeded UI and midnight tests. Real-device timed events remain in question. | No live result. The release has no default location or way to set one in its sheet. | **Uploaded build `202611221913`**, not `1` as the session reported. Separate Debug install tested briefly on hardware. |
| **Claude Opus 5.5** · `dash/opus-5.5` · `5545c67` | Closest documented match; wide and narrow image tests, seeded calendar and rollover captures. | Live for the intended location after team signing; cached and offline states captured. Attribution missing. | **Uploaded build `202611221912`**. Processing started; no verified device pass. |
| **MAI Code 2** · `dash/mai-code-2` · `fff34a7` | Core layout, selection, shift chip and overflow present. Less direct evidence for settings and error-state UI. | Live after the signing setup changed and the fixed location was corrected. | **Uploaded build `1`**, but the signed app lacks WeatherKit. No verified device pass. |
| **GPT-6.2 Sol** · `dash/gpt-6.2-sol` · `44bd5fa` | Strong EventKit and settings tests; small native text differences. Busy days can hide NOW. | Live, with Apple attribution and stale-data labeling, but for a test city rather than the intended place. | **No upload.** Phases 0–6 committed. Phase 7 assets and unsigned build `1` exist locally; no matching profile for the signed archive. |

**How I checked:** I compared each worktree with the common commit, read the phase conversations (31 top-level sessions; some carried two prompts), inspected the Swift code and tracked snapshots, and checked retained test and distribution artifacts. I did not rebuild, re-sign, contact App Store Connect or test a device for this review. “Uploaded” means a successful transfer, not a processed build available to testers. In particular, Qwen's archive has `ApplicationProperties.CFBundleVersion = 1` but `Distributions[0].uploadedBuildNumber = 202611221913`; its exported app agrees with the latter. MAI's archive records uploaded build `1`. These are not two uploads of the same build number.

## What each run did well, and where it fell short

### Qwen: good at measuring the fixture; missed the fresh install

Qwen could not inspect images visually in its session. Instead it sampled colors, row boundaries and column widths against the PNG. It discovered that the rendered Today column was nearer 2.0× than the nominal CSS 2.2× and changed the SwiftUI geometry to match the approved output. That was a useful judgment call. Its row tests checked measured heights, not just event counts. Verification also found a real midnight bug: a failed calendar fetch advanced the clock but left yesterday's headers. Qwen rebuilt the headers from cached data before fetching and added regression coverage. The phase-6 session reported 94 passing unit and UI tests.

The weather diagnosis was weaker. Qwen tried an unsigned simulator build and a post-signed one, then concluded the simulator was definitively blocked. Three peers subsequently showed live values on the same simulator class. That does not invalidate Qwen's failures; it does invalidate the platform-wide conclusion. More importantly, `app/Sources/WeatherKitForecastProvider.swift` obtains the fixed coordinate **only** from defaults or a launch argument. A seeded run can supply it; a fresh install cannot. The two-group settings sheet does not set it.

This was the only run with direct user feedback from hardware. After a separately authorized Debug install, the user reported no forecast and apparently only all-day events despite expecting timed entries. The missing coordinate explains the weather symptom without needing a signing hypothesis. The session did **not** establish the cause of the missing events or verify a fix. Its upload was real, but the data on that device mattered more than the upload or the green fixtures.

Two other Qwen findings matter before repeating that run. `AgendaBuilder.buildWeek` assigns events to their start date only, so an overnight event drops off after midnight. That is a code finding, not a diagnosis of the user's missing meetings. **Do not enable the Debug demo seeder on a device with real calendars:** `DemoSeeder.prepareIfNeeded()` reuses calendars by display name and deletes events in its seed window without checking who created them. It is opt-in and absent from Release; there is no evidence it ran on the user's calendars.

### Opus: best-supported starting point, not ready to declare shipped

Opus left evidence a second reviewer can use: `docs/verify/` contains 18 captures, including the v6 side-by-side, seeded calendar, live forecast, settings relaunch, midnight rollover and denied/offline states. Its phase-2 sample-week comparison reported a mean absolute pixel difference of 3.99/255. More tellingly, it kept separate five-event goldens for the wide **and** narrow columns, where title width had been a design problem. The final retained full-suite run shows 94 passes and one intentional skip; the permission-denied check passed separately. An earlier full run had three failures. The final result matters, but the rerun history explains why the raw test bundles are better evidence than a summary badge.

After the developer account and certificate were corrected, Opus verified that **team-signing the app** rather than merely rebuilding was necessary for its live simulator forecast. It also worked through distribution signing, checked the exported entitlement, and recorded the actual uploaded build. Its release notes explicitly leave Apple Weather attribution open; the top bar does not display a mark or legal link.

Two code details matter on a family wall. `BrandiRule.calendarID` in `app/Dash/CalendarModel.swift` falls back to the first calendar whose title contains the designated name. A rename or competing match can put the wrong calendar under the rule and expose ordinary entries from the intended one. `WeekBuilder` correctly repeats an overnight event across intersecting days, but `AgendaRow` evaluates NOW in each column, so an active overnight event can be highlighted twice. Also, scripts such as `tools/wall-verify.sh` suppress an `xcodebuild` pipeline failure with `|| true`. Use the `.xcresult`, not a zero script exit, as the pass gate.

### MAI: working simulator forecast, broken distribution entitlement

MAI advanced through the eight phases, corrected its initial forecast location, and demonstrated a live daily forecast after the account fix. Its seeded agenda covered the special shift, all-day item, past/NOW state and `+N more`. It got a signed export through Xcode's cloud-managed distribution path. The retained phase-7 test log contains **19 passing cases**. The conversation also says 20 at an intermediate point; the final report and retained log agree on 19. The phase-0 session needed a reminder to commit after verification, but subsequent phase commits are present.

The final upload check missed a functional regression: `Dash.entitlements` and the profile enable WeatherKit, but `codesign` on the exported app and the upload signing log both omit `com.apple.developer.weatherkit`. The upload succeeded because a valid distribution signature is not proof that the app preserved every capability. **Expect live weather to fail in this build**; that is a finding from the signature, not an observed TestFlight failure. Opus and Qwen both preserved the entitlement in their exports. In calendar handling, MAI also filters by event start date rather than day overlap, which loses overnight and multi-day items on subsequent days.

Its tests often prove the model behind the screen, not the screen itself. `DashSettingsStoreTests` recreates stores rather than tapping the sheet and relaunching. The midnight test passes two dates to the cadence logic rather than observing the running wall roll over. `AgendaSnapshotTests` compares actual pixels exactly, but renders the day in isolation. In its committed five-event PNG, the current and upcoming titles are dark against dark cards. The app root requests dark mode; the isolated snapshot does not. This is a defect in the visual test, **not proof that titles are black on the iPad**.

### Sol: strongest weather integration, incomplete release

Sol withheld its weather commit when the auth service failed even though all 11 tests passed. It committed only after a live fetch. `app/Dash/WeatherKitForecast.swift` uses the attribution returned by WeatherKit; the bar renders the mark with its legal link, and labels saved weather after a failed refresh. The retained capture shows a real high, low and condition. It was for **Chicago**, however: this proves the integration, not a correct local forecast. The live bar also drops the mockup's wind, precipitation chance and sync-age text. Those are fidelity gaps, not failures of the narrower phase-4 test.

The tests cover actual EventKit changes without waiting for the timer, settings across app relaunch, and midnight rollover inside a window shorter than the ordinary poll. The phase-7 bundle records 17/17 passes. There are still composition issues: `AgendaWeek.days(from:)` in `app/Dash/CalendarFeed.swift` selects the special calendar by exact display name while the normal filter uses IDs. A rename defeats the special rule. The view takes the earliest rows that fit; on a busy day, past rows can push the active event behind `+N more`. Tests for capacity and NOW each pass without exercising that combination.

At release, Sol built an unsigned archive, reported the missing profile, and left the release changes uncommitted under the verify-before-commit rule. That is an honest stop, not a successful phase 7. It also means checking out `44bd5fa` alone will not reproduce the icon, launch screen, privacy manifest or export configuration from the final local run.

## What the comparison supports

**Layout was not the main separator.** In the four committed five-event Today snapshots, all four preserve the shift chip, five equal rows and the NOW marker. The small text differences are instructive: Qwen truncates a current title that Opus wraps; Sol keeps that title on one line with shorter times; MAI's isolated renderer loses title contrast. These are useful simulator observations, not judgments about viewing distance. A perfect match to a static Tuesday also says nothing about what happens on a busy Sunday night with real calendars.

**A green test is only as strong as its inputs.** Qwen's missing default, Sol's working forecast for the wrong city, and MAI's isolated snapshot all pass plausible automated checks. Opus offers the most reviewable visual record, but even its strongest seeded-calendar test can't identify the right calendar on a new account. Prefer a cold launch without injected defaults, a real calendar edit, a denied-permission run and a cache-empty offline run over another raw test-count comparison.

**This was not a controlled speed or cost benchmark.** The runs shared a Mac, simulator tooling, a bundle identifier and changing Apple signing resources. The user corrected WeatherKit enablement and the development certificate during phase 4. Signing state, prompt continuations and follow-up opportunities differed; only Qwen got the physical-device bug report.

## Token usage: compare the working app before distribution

**Phases 0–6 are the fairest comparison:** all four built through wall behavior. Sol recorded the least token traffic (14.94M); Qwen the most (52.87M, or 3.54× Sol). Sol also used the fewest output and reasoning tokens. That is an efficiency result for this task, not a verdict on quality: Opus used more tokens but produced the strongest visual verification record.

| Run | Input outside cache counters | Cache read | Cache write | Output | Reasoning | Phases 0–6 total | All sessions, including phase 7 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen | 52,206,164 | 0 | 0 | 235,587 | 427,225 | **52,868,976** | 64,262,467 |
| Opus | 580 | 27,650,195 | 1,097,901 | 194,998 | 137,352 | **29,081,026** | 31,967,144 |
| MAI | 1,992,247 | 31,871,360 | 0 | 107,522 | 64,911 | **34,036,040** | 39,222,865 |
| Sol | 777 | 13,997,195 | 841,309 | 86,437 | 18,431 | **14,944,149** | 15,990,386 |

Source: OpenCode's local session API, keyed by Dash worktree. The five component columns are **phases 0–6 only**. Totals sum the five recorded counters across all model calls, including repeated context and delegated work. The all-session column covers 31 top-level sessions and 10 child sessions; the phase-limited column excludes each TestFlight session and its children. The counters do not measure unique prompt text, equivalent compute or dollars. In particular, Qwen's local provider reported no cache traffic separately; that does not prove caching was disabled. Most Copilot traffic was reported as cache reads.

**Later Qwen follow-up:** the all-session total includes physical-device debugging *after* the evaluated upload. In `8dc5040`, Qwen supplied a default forecast location and implemented a revised user-requested calendar rule. The session subsequently reported real weather and timed events on the iPad. That updates the hardware diagnosis above; it neither changes the original `1dd3d7a` binary nor establishes a four-way device comparison.

## The device pass that could change the recommendation

1. **Identify the binary first.** Match the TestFlight version and build to the table; label Qwen's prior Debug run separately. Sol needs a signed build before a like-for-like release comparison. Reset app data between candidates so one build's location or calendar choices cannot rescue another.
2. **Cold-launch online with no seed flags.** Check the place and today's forecast. Grant full calendar access. Compare timed and all-day entries with Calendar, verify the exact shift chip, and confirm no other entry from that calendar is visible. Toggle one calendar and the temperature unit; relaunch.
3. **Read it from the intended wall position.** Check the Today title beside NOW, the six narrow columns, notes, weekend headers and the overflow count with a busy day. Record the first item that needs a closer look, not just “looks good.”
4. **Leave it running across midnight.** Verify wake behavior, day labels, the moving NOW state and a changed calendar entry. Disconnect and reconnect the network; distinguish cached weather from current weather. Repeat a denied-calendar launch and make sure the wall remains useful.

Until that pass, **Opus is the best candidate to test first**, not a device-validated winner. Borrow Sol's attribution handling. Before spending a device run on MAI's weather, correct and verify its signed entitlement. Use Qwen's cold-start failure as a regression case for every branch.

### Evidence locator

Commit IDs and paths above refer to the **Dash source repository**, not this benchmark harness. To reproduce the documentary review, inspect `git show <commit>:<path>` there. In OpenCode, select the indicated `dash/*` worktree and its phase-titled sessions: **Static layout shell**, the phase-4 forecast session, the phase-6 wall session, and the phase-7 TestFlight session. The Qwen device conversation follows its upload in the same session; the Opus EventKit prompt follows phase 2. For release identity, inspect the archive's `Info.plist → Distributions → uploadedBuildNumber`, not just the project build setting. Raw simulator captures, local account details, signing records and private calendar data are intentionally not copied here.
