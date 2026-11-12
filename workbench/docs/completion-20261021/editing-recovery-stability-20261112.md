# Editing recovery stability, 2026-11-12

## Local recovery choices

A deterministic counterexample reproduced loss of a local recovery draft: select
"ignore local/use server", delay its head read, then choose "restore local".
Before the 800ms save debounce, the older read could overwrite the restored
editor, discard its queued save and remove the local recovery copy. A second
counterexample removed the copy after the editor had unmounted.

The editor now invalidates older remote-choice reads on a newer recovery choice,
editing, merge choice, action refresh or unmount. It checks the current choice
before discarding a queue or changing the editor, head or recovery storage. A
failed newer local restore also does not revive an older discard intent. A user
who keeps the latest explicit server choice can still discard the local copy;
normal saves, exact request recovery and server CAS are unchanged.

Six new regressions cover late success/error, unmount, both orders of competing
remote choices and invalid local recovery. The 15 relevant editor/read-only/save
queue checks pass. The restored local title is subsequently saved through the
real component's ordinary save path, and its recovery copy is removed only after
that acknowledgement. An independent source review found no blocker.

Actual Chrome at 1440 and 390 pixels passed late success, error and unmount with
the real SectionEditor and explicitly synthetic async fetch responses. These
checks do not establish real-document editing, persistence or export quality.

## Word candidate navigation

A separate regression reproduced an old candidate GET arriving after a newer
prepare command succeeded. It replaced the candidate view with the old candidate,
so the newer candidate's preview disappeared while the recovery record still
pointed to the new candidate. Accepting a validated candidate now invalidates
older reads and ends its loading state; unmount also invalidates read tickets.

Three new regressions cover late success, late error and unmount; all 18 Word
import component tests pass. They preserve the new candidate identity and do not
resolve or append any candidate automatically. Source/draft/receipt validation,
warning acknowledgement and image checks remain unchanged.

Chrome at 1440 and 390 pixels also passed all six Word-candidate cases (late
success, late error and unmount), retaining the newer preview and leaving append
disabled until its own confirmations. No resolve or changed-draft callback ran.

## Final frontend gates

All 2,101 frontend tests in 210 files pass. Formatting, lint, types and production
build pass; existing build warnings remain. This includes the six new editor
recovery cases and three new Word-candidate cases.

## Boundaries

All new fixtures are synthetic and local. No original files, external provider,
paid service or Docker service were needed. This does not certify arbitrary Word
round-trip fidelity, real OCR accuracy or user/business acceptance.

## Baseline CI

Before this editing fix was committed, exact baseline cf95f26 completed
[Workbench CI 43237843933](https://github.com/zys743551828-art/tender-app/actions/runs/43237843933)
with all eleven jobs successful, including native PostgreSQL/S3 editing and Word
export. That result belongs to cf95f26, not to subsequent commits.
