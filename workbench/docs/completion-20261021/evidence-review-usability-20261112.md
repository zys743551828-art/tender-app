# Evidence review usability, 2026-11-12

## Product changes

- The original-document evidence surface now searches its already-loaded text.
  Matching tolerates whitespace between Han characters and letter case, but does
  not repair numbers, punctuation, OCR characters, or join separate blocks.
  Withdrawn sources are excluded. Counts include all matching blocks; the display
  is capped at 30 and asks the reviewer to narrow the query. Search results only
  navigate to a physical page, not to a certified bounding-box highlight.
- Construction-organization/construction-plan clues and maintenance/service clues
  are shown separately. Both can occur on one page. Neither assigns a document
  role or proves that the relevant requirement is satisfied.
- Search state is scoped to the document and parse run. A new version starts with
  an empty query; narrow-screen navigation opens the extracted-text pane.

## Recorded-data check

The existing case01 29-page/959-block record was replayed, without rerunning OCR
or changing a quotation. Maintenance, safeguard, emergency and training search
terms produced 2, 23, 33 and 61 matching blocks respectively. Display is capped at
30, as stated in the UI. These counts measure navigation matches, not recall,
accuracy, compliance or completeness. Source text remains in ignored local files.

## Browser scope

Actual Evidence/SourceSurface components were exercised in local Chrome at 1440
and 390 pixels, using explicitly synthetic HTTP responses: spaced-Chinese search,
page navigation, mobile text visibility, clear/no-match and close/reopen query
reset passed without horizontal overflow. This test did not certify PDF rendering,
backend permissions, actual downloads or new full-system case01 acceptance.

## Boundaries

Both source PDFs remain partial. Numeric, symbol and character errors still need
comparison with the original. A missing navigation match is not evidence that a
requirement or technical section is absent. No external model, new OCR, Docker
service or original-file changes were needed for these navigation checks.

## Interrupted artifact retrieval

Two regressions were reproduced before fixing: an unmounted output action still
requested a download grant when late metadata arrived, and changing the document
retained the old preview. Output actions now reset by document/project/expected
qualification and ignore late metadata, authorization, byte and blob responses.
The original-evidence download action likewise invalidates on close, unmount and
scope change. A synchronous lock suppresses accidental simultaneous starts while
allowing a subsequent deliberate retrieval or retry. Existing in-flight network
requests and downloads already handed to the browser are not cancelled.

18 new interrupted-retrieval checks plus existing relevant flows passed (33
focused checks total). An independent source/component review found no blocker.
These are synthetic race-condition checks, not new real-document export acceptance.

Actual Chrome also passed the delayed-metadata version-switch and leave-page cases
using the real ArtifactActions component with synthetic HTTP. No late grant was
requested after either invalidation. This is not a real artifact download test.

## Interrupted scope comparison

An additional race was reproduced with two failing regression cases: selecting a
new counterpart while an earlier comparison was loading allowed the old success
or error to replace the current view. The old comparison could also be passed to
the new pair's observation editor. Scope comparison now invalidates pending
responses synchronously when the counterpart changes and resets by project path,
selection identity, proof digest and current-material state. A synchronous lock
suppresses duplicate starts; an invalidated request cannot unlock or overwrite a
newer request. Existing network requests are not cancelled.

Eight new regression cases cover late success/error, newer-before-older completion,
scope changes, duplicate clicks in StrictMode and unmount. The comparison test
file's ten checks pass. An independent source review found no blocker. Actual
Chrome at 1440 and 390 pixels exercised the real comparison and observation
components against local synthetic HTTP: the new comparison and evidence options
remained aligned after old success and error responses. This is not a new
real-document, persistence, model or business acceptance result.

The final frontend suite passed 2,076 tests in 210 files. Formatting, lint, type
checks and the production build passed; existing chunk-size warnings remain.

## Interrupted history navigation

Three more failures were reproduced before fixing the selected-page panel: old
scope evidence or an old error could arrive after a different history record was
opened, and an unmounted save continued into a follow-up verification GET. The
panel now resets by project, document, file digest and parse identity, guards each
async stage, and lets a different history navigation supersede pending work. The
same in-flight action cannot be started twice synchronously. Historical record
identity is checked as well as document and parse identity.

Navigating away does not cancel a POST already sent to the server or undo a saved
record; it suppresses stale UI and unnecessary follow-up reads. History can be
reloaded to inspect saved records. No backend authorization or eligibility boundary
was relaxed.

Actual Chrome at 1440 and 390 pixels passed old-evidence success/error after
history navigation and save-after-unmount with zero late verification GETs. These
were local synthetic HTTP checks with the real panel, not real-document or
persistence acceptance. Independent source review found no blocker.

Eleven new history/identity regressions pass. Final frontend checks passed 2,087
tests in 210 files, formatting, lint, types and production build; existing build
chunk-size warnings remain.

## Lifecycle confirmation during snapshot refresh

CI run 43234648709 on d3a8eed failed its native pricing/workspace journey while
waiting for a reopen response: the diagnostic recorded no POST, a valid reason
and an enabled button after the timeout. Run 43235738155 on a7fd35c passed that
same job before the lifecycle correction below. The exact original runner timing
is not recovered, so this is not proof of every condition behind that CI failure.

A matching failure mechanism was independently identified in source and then
reproduced in local Chrome at 1440 and 390 pixels: dispatching a background
snapshot refresh between real mouse-down and mouse-up temporarily disabled the
confirmation button, emitted no POST, then left the button enabled again after
refresh. This check retained real pointer events rather than forcing form submit.

Lifecycle confirmation now remains usable during a background refresh only when
a valid existing project snapshot and ETag are present and no read error exists.
The explicit intent and its captured ETag still bind the request; a changed ETag,
conflict, wrong project or initial missing snapshot still blocks acceptance. A
successful write starts a fresh read instead of joining a read initiated before
the write. Old read success and failure cannot replace this newer state. During
that post-write read, a separate settling lock prevents a second action from the
old snapshot. Default shared read coalescing remains unchanged for other callers.

The same interrupted mouse gesture then sent exactly one POST at both sizes and
retained the post-write state after the older read arrived. Focused regressions
also retain CAS conflict rejection and the explicit reason, check fresh/old read
errors, and prevent a success notice before the post-write refresh settles. These
are actual-component synthetic HTTP checks, not a new full native-system or
real-document acceptance result. No external model or Docker service was used.

Final lifecycle checks passed 2,092 frontend tests in 210 files, formatting, lint,
types and production build. Eighteen focused lifecycle/resource/recorded-command
checks passed, including five new regressions; existing build warnings remain.
