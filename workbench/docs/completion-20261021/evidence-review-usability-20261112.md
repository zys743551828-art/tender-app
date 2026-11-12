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
