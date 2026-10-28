# OPPDAY Dashboard

The main Opportunity Day reader and publication pipeline. Local and GitHub Pages
serve the same approved release; source scans prepare candidates without changing
the live reader dataset.

Online: https://benzkanin41-alt.github.io/oppday-dashboard/

## Local Startup

Resolve stable ID `oppday-dashboard` with the central `dashboard_ports.py` registry,
then invoke its registered `Start Oppday Dashboard.ps1` launcher. Keep the existing
Desktop shortcut. Never choose an alternate port or stop another dashboard.

Local retains the established summary/PDF experience and Light/Dark preferences.
Approved file copies are stored privately on E:, so later source changes do not
change an accepted release.

## Source And Run Ownership

Canonical delivered documents remain in OneDrive under
`OPPDAY/<QUARTER>/Oppday`, including the `PAST` archive. All supported quarter
folders are discovered rather than hard-coding a current quarter. Production run
artifacts, configuration, QA and private snapshots are kept in `.oppday-work`.
They must never be committed or uploaded to Pages.

New Dashboard records contain only `<TICKER>-Earning call-<QUARTER>.md` summaries.
Do not add PDFs to new reader records, including after full production or current
requalification. Their required report/PDF QA remains separate private acceptance
evidence, not reader attachments. Transcript and Presentation remain source
material, not new reader records. Preserve all accepted historical attachments.

For production, use the installed `multiagent-oppday` Skill with this project's
profile. The project entrypoint injects it automatically:

```powershell
python -B -X utf8 scripts/oppday.py --help
python -B -X utf8 scripts/oppday.py prepare --quarter 3Q69 --date-from YYYY-MM-DD --date-to YYYY-MM-DD --stage all
python -B -X utf8 scripts/oppday.py verify --resume RUN_ID
python -B -X utf8 scripts/oppday.py finalize-dashboard --resume RUN_ID
```

The deterministic CLI coordinates stages and verification; Codex dispatches the
source/report agents required by the Skill. Preserve independent semantic/Q&A
review and source/hash gates. A successful document copy alone is not release
eligibility. Intelligence is managed separately from this Project.

## Publication

The profile-aware finalizer freshly verifies the selected run, creates an immutable
candidate and publishes only the exact eligible registration set. It waits for
GitHub Pages, compares live index and item bytes, activates Local atomically, then
records success. Files-only and dry-run work stay outside the live dataset.

`scripts/publish_release.py` supports resumable publication of prepared releases.
`scripts/release_snapshot.py verify --release-id RELEASE_ID --verify-blobs` audits
a private snapshot. Retain recovery evidence and the preceding snapshot.

An explicitly authorized current requalification can accept unchanged existing
documents when historical producer evidence is unavailable. It requires new
independent, hash-bound semantic/Q&A review and current PDF/source checks; it
does not reconstruct or claim old jobs, author identity, rendering history, or
audio-recognition QA. No failed or unreviewed record may use that path. D:
originals and their historical status rows remain unchanged; the new publication
receipt records the separate current authorization and actual outcome privately.

### Existing Markdown Imports

An explicit dashboard-only request can import existing Earning call MD without
producing, opening, validating or copying its accompanying PDF. It is a separate additive path,
not a successful Agent 6 review or a fallback after failed production QA. Source
UTF-8/heading/identity/hash checks, an exact complete quarter inventory, current
authorization, immutable copies, historical payload preservation and the usual
online-before-Local release checks remain mandatory. Source reports and historical
CSV statuses are read-only. Existing semantic findings remain findings; this path
does not claim to correct or recertify report contents. An already accepted item
is retained byte-for-byte; changed existing text requires a separate decision.

Keep an authorization JSON on E: containing `action` equal to
`import_existing_earning_call_markdown`, `importId`, `quarter`, the actual
`userRequest`, `preserveOriginals: true`, and `preserveHistory: true`. Then:

```powershell
python -B -X utf8 scripts/markdown_import.py --import-id IMPORT_ID --quarter 3Q69 --authorization-file PRIVATE_AUTHORIZATION_JSON
python -B -X utf8 scripts/publish_release.py --markdown-import-id IMPORT_ID --release-id RELEASE_ID
```

Requests and proofs stay in `.oppday-work/markdown-imports/IMPORT_ID`. This mode
does not waive PDF or independent semantic/Q&A gates for creating new reports,
does not invoke Intelligence, and never schedules a scan or publication.

GitHub Pages receives only the public output under `docs`. Preserve the co-hosted
`docs/bubble-risk-dashboard`, reconcile remote changes, and never force-push.
Internal handoff, glossary and runbooks are local Project documents excluded from
the public repository and Pages.

## Tests

```powershell
python -B -X utf8 -m unittest discover -s tests -v
```

The tests cover multiple quarters/year boundaries, historical continuity,
files-only isolation, snapshot integrity, failed-publication guards and private
file copies. Browser and exact shortcut tests are also required before accepting
a live release.
