# case01 local extraction review, 2026-11-12

## Verified scope

The desktop Docker Linux engine is working. This supersedes the earlier startup blocker in `resume-desktop-20261112.md`; no reset, socket deletion, or security-setting change was needed for this review.

The private original qualification document was visually reviewed on physical pages 65-93 (29 pages). It contains substantive maintenance/service, safeguards, emergency, and training content. Filename-based exclusion would be incorrect. The body is predominantly single-column text; decorative headers/footers and a cover image remain visual-layout limitations.

The tender reference was visually checked at physical pages 23, 65, 66, 68, 156-158, 188, 191, and 192. Pages 23/188 specify a maintenance/service submission of at most 30 pages. Pages 65-66 separately specify a five-point construction-organization assessment, eight content categories, formatting, and a 50-page limit; pages 191-192 identify its technical-file placement and text/diagram expectations. Page 68 states missing subjective items score zero and AI does not replace the evaluation body's judgment. The 29-page maintenance section must not be certified as a complete construction-organization submission merely because it has technical content. The earlier 156-158 reference scope does not cover all relevant scoring requirements.

## Narrow product correction

Chinese chapter-prefix recognition now tolerates OCR-inserted horizontal whitespace (for example, spaces within an ordinal). Original evidence text is not normalized or rewritten. Chapter metadata remains inferred, not verified structure. New parser source identity intentionally invalidates the old parser digest.

A fresh production-settings local run of all 29 selected pages produced 959 blocks in 63.11 seconds. Compared with the previous output, page text and every block's text, bounding box, confidence, and kind were identical; quality and gap flags were unchanged. The heading heuristic matched 78 rather than 51 candidates. This is an inferred-candidate count, not a measured precision or claim of 27 correct chapters.

31 focused tests passed, including synthetic scanned Chinese-heading recovery, original-text retention, and 14 prefix boundary cases. Ruff, formatting, Linux-target mypy, and Bandit passed. Independent final-diff review found no blocker. This is not a fresh complete application/UI regression or an AI-generation evaluation.

## Measured limits and rejected experiments

A private visual baseline records three anchors per page (87 selected anchors). Production OCR matched 9 literally and 82 after whitespace-insensitive comparison. This is selected-anchor recall, not character accuracy or complete document validation. The five unmatched anchors still require individual review. Low-confidence lines remained present; partial status is intentional.

A 300-dpi pixel experiment reduced normalized anchor hits to 71 and increased low-confidence lines from 41 to 92; it was not adopted. A geometry-aware spacing experiment did not improve the anchor results and was also rejected. Neither experiment changed the final product code.

## Remaining work

- Expand comparison scope to the confirmed scoring and technical-file pages, separating maintenance/service from construction-organization requirements.
- Review the five unmatched anchors and heading candidate precision before broader OCR/layout changes.
- Validate cross-page continuity, diagrams and tables beyond these selected body pages; do not claim full visual parsing.
- Obtain explicit provider, data-transfer, and cost authorization before external model evaluation.

Original documents, renders, anchors, and extracted text remain local and outside Git. No external model was called; no deployment or merge was performed.
