# Local chapter-candidate review, 2026-11-12

## Deliverable

`python -m qa.chapter_candidate_review PARSE.json NEW_PRIVATE_REPORT.json`
creates a local review report for candidates already present in a parser result.
It includes original candidate text/coordinates/confidence, preceding and following
same-page blocks, and explicit review prompts. It does not discover or certify
headings, change the parser, rewrite evidence, alter `partial`, or amend formal
eligibility. This is a developer/reviewer CLI, not a new end-user UI.

The report contains private document text. Store it under `.local`, outside Git.
An existing output is never overwritten, including when it is the input itself.
Context follows parser block order, not verified reading order. Cross-page and
multi-column continuity are not assessed.

## Conservative prompts

Every candidate requires human review. Numeric prefixes are ambiguous between
headings and body content. Two nearby wide lines with similar right edges receive
an additional continuation-review prompt. This is a geometric triage signal,
not an automatic rejection or confidence score. A lack of this prompt is not
proof that a heading is correct. Missing/invalid geometry does not infer continuity.

## Recorded real-sample replay

Replayed the existing 29-page/959-block case01 extraction with the current heading
pattern. All 78 candidates are retained; 51 numeric candidates receive the numeric
review prompt. Two receive the additional geometric prompt, on physical pages 73
and 84, matching the two visually confirmed continuation false positives in the
prior review. This is a small recorded-sample check, not independent accuracy,
fresh OCR, or a full application regression. Original extraction stays unchanged.
The private contextual report and numeric-only summary remain in
`.local/case01-quality-20261112/structure-review-private.json` and
`structure-review-summary.json`.

## Checks and remaining limits

11 focused tests cover context, immutable evidence, invalid/missing geometry,
reference validation, no inferred new headings, output collision and no stdout
source leakage. Ruff, formatting, Linux-target mypy and Bandit pass.
No Docker images, services, external model calls, or original-document changes
were needed. General automatic heading disambiguation remains unvalidated;
reviewers must inspect the rendered original before accepting structure.
