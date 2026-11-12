# Desktop continuation, 2026-11-12

> Historical checkpoint, superseded later on 2026-11-12: the user successfully
> started Docker Desktop and the Linux engine was verified healthy. The startup
> failure below was specific to the attempted automation context, not proof of a
> broken installation. Real case01 no-model upload, selected-page comparison and
> history workflows subsequently passed. Both documents retain partial parsing;
> see `case01-extraction-quality-20261112.md` and
> `case01-structure-review-20261112.md` for the later quality boundaries.

## Scope and baseline

Work resumed on the Windows desktop from `dev` at `5ff120a`, one commit ahead of `origin/dev` (`c75178b`). The older D-drive `fusion/bid-workbench` checkout was not reset or overwritten. Existing docs changes and private originals remain untouched.

## Upload correction

The case01 dual-document helper selected both documents as `body`. The API rejects more than one body with `409 BODY_SELECTION_REQUIRED`; the helper waited for success without preserving that response. This is a code-based diagnosis, not a recovered historical HTTP response.

The product now rejects multiple selected bodies before creating a batch or requesting upload authorization. It preserves the user's selections and asks them to choose the actual purpose from content. It does not classify by filename, reinterpret qualifications as lacking construction organization content, or weaken the backend constraint.

A separate local helper copy selects the known tender reference as `tender`, keeps the qualification document containing the technical section as `body`, and records the commit status plus a restricted error code. No private document content enters this record or Git.

## Verification

- API contracts: 10 tests passed with socket operations and child processes blocked.
- OpenAPI composition and package schemas: 23 tests passed under the same offline guard.
- Frontend upload regressions: 8 tests passed, including zero authorization/transfer for multiple bodies and successful body+tender flow.
- Full frontend lint/formatting and TypeScript checks passed.
- Frontend production build passed with existing chunk-size and mixed-import warnings.
- Changed backend Ruff/format and Bandit passed.
- Native Windows mypy reported 20 POSIX attribute errors in 3 imported modules; Linux-targeted mypy passed; this is static Linux-target validation, not a Windows runtime certification.
- Full frontend suite: 2038 tests passed; no failures, errors or skipped tests.
- Full backend suite: not completed; the initial broad run was blocked by an execution review concerning possible telemetry. Focused offline checks do not replace it.

## Remaining runtime blocker

Docker Desktop cannot start its Linux engine. Its Secrets Engine reports that `engine.sock` cannot be renamed to `engine.sock.stale` because the system cannot access the file. No socket deletion, permission change, factory reset, or Docker resource cleanup was performed. The startup CLI wait was cancelled after the failure was confirmed.

The real case01 two-document upload/parsing/comparison remains unverified. No model was invoked, no originals were sent to an external model, and no deployment or merge was performed. No test containers or images were created in this continuation.
