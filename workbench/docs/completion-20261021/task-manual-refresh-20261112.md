# Manual task activation during background refresh

## Observed failure and bounded diagnosis

The pricing/native browser job in
[Workbench CI 43245913022](https://github.com/zys743551828-art/tender-app/actions/runs/43245913022)
for `861d85f` timed out waiting for the POST to an ordinary template's `/runs`
endpoint. The previously created run remained visible. Other jobs passing on
that commit do not turn this failing journey into a successful result.

A deterministic, actual-Chrome component replay reproduces a matching mechanism:
a server-snapshot event arriving between pointer down and up makes the ordinary
manual-run button disabled during its background GET, and the user's click is
lost. This proves the mechanism, not every original CI runner timing detail.

## Corrected interaction boundary

A loaded, valid ordinary template and its strong ETag remain usable during a
background read. All existing pause, unavailable capability, fee reconciliation,
error, missing-ETag, pending-command and busy-command guards remain in place.
The edit, pause, exact-package and package-authoring controls are not relaxed.
The POST remains `{rerun: false}` with the explicitly selected version's
`If-Match`; a 412 is not automatically retried or reported as a successful run.

The version/digest/ETag tuple also replaces the manual-run button when the
selection changes. DOM replacement alone is insufficient for mobile Chrome:
a touch can begin on the old button and synthesize its click on the new one.
That counterexample was reproduced with separate CDP touch-start and touch-end
events and a completed newer GET between them. The interaction therefore also
binds physical activation to the version selected at its start. A changed
selection needs a fresh explicit activation, rather than silently running the
new version under an old gesture.

## Verification scope

The browser replay uses the real component in installed Chrome with explicitly
synthetic HTTP responses. It does not execute a model, create a paid task, upload
a business original, or exercise the full PostgreSQL/Worker transport. Final
local gates and exact-commit CI are recorded below only after they finish.

The focused task-card/panel set passes 31 tests, including missing/cancelled
physical activation, mismatched pointer identity, keyboard, auxiliary activation,
three independently changing identity fields and the original fee/qualification
boundaries. Chrome passed 16 scenarios: ten refresh/guard cases at 1440/390px,
four same/changed-version mouse cases, and two CDP mobile-touch cases. The
changed-version cases additionally require a successful new explicit activation.
The 390px screenshot was inspected and the controls remain visible and readable.

The first aggregate run exposed an unrelated timing gap in the prior editor
recovery test: handing its deferred native Response to fetch did not prove that
Response.json and readHead had finished. The production latest-choice guard was
reviewed; there is no await between its final choice check and removal/ACK.
That narrowly scoped fixture now parses its controlled responses as deterministic
microtasks. It explicitly establishes the newer choice's ACK and removal before
releasing the stale response, while preserving all stale-read, unmount and
no-save assertions. The three affected frontend test files pass 39 tests.

Exact CI for `861d85f` completed with ten successful jobs and this one failed
pricing/native journey. Its fixed-source editing/Word-export PostgreSQL/S3 job
passed, but neither that nor any earlier green run certifies the fixes here.

Final local frontend gates pass: TypeScript, Prettier, ESLint, all 2,129 tests
across 213 files, and production build. Existing bundle-size warnings remain.
The image-geometry parser/API/import set passes 98 tests, with changed-file
Ruff/format, Linux-target mypy and Bandit checks passing. No Docker image was
pulled or container created for this correction. This commit needs its own CI.
