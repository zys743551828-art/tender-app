# Word image integrity, 2026-11-12

## Visibility must not depend on alt-text priority

Three failing counterexamples reproduced an inner `pic:cNvPr.hidden` flag being
ignored when outer `wp:docPr` supplied alt text. The old alt-text loop returned
early, so the normal visible-image path accepted hidden image content.

Visibility is now checked independently for both property containers, before
reading, normalizing or reusing image bytes. Existing explicit visible values
(`0`, `false`, `off`) and missing-value behavior remain unchanged. Alt-text source
priority and fallback are unchanged.

A further three counterexamples reproduced duplicate `docPr`, `nvPicPr` or
`cNvPr` containers being misread as missing properties. Such ambiguous drawing
properties are now blocked instead of choosing or ignoring a visibility flag.
A visible placement followed by a hidden placement of the same image cannot use
the resource cache to bypass this check. Hidden/ambiguous drawings do not acquire
permission to append, render or enter a model workflow.

These source changes advance the existing parser method identity. Old candidates
are not silently relabeled with the new parser; existing method/current-draft
checks and explicit regeneration behavior remain in force. No API schema, source
role, permissions, renderer profile or original document was changed.

## Declared placement, not natural pixels

Both candidate preview and the ProseMirror section editor previously displayed
image content using natural pixel proportions (`contain`), even though DOCX
export uses the declared full-rectangle placement. The candidate preview also
ignored placement height; the editor retained a fixed height when narrowing its
width. A legitimate 12 x 8 pixel image declared as 2400 x 2400 twips could therefore
appear non-square or letterboxed while its exported content was stretched square.

Both surfaces now use the declared width/height aspect ratio and full-rectangle
fill. Narrow screens scale the complete placement proportionally; they do not
reset it to the source pixel ratio. Bytes/digest/decoded-pixel checks, image-version
URLs, node identities, edit permissions and serialized document content remain
unchanged.

## Checks

- Seventeen new backend cases cover hidden/visible flags, no normalization of
  hidden drawings, all three duplicate-container paths, cached-resource reuse and
  actual synthetic DOCX import -> native drawing export extent preservation.
- The parser/API/import unit set passed 92 tests. Changed files pass Ruff and
  formatting; Linux-target mypy and Bandit pass. Static Linux targeting is not a
  Windows or production Linux runtime certification.
- Six new frontend placement cases cover original ratio, square stretching and
  wide placements in both preview and editor.
- Actual Chrome at 1440 and 390 pixels passed all twelve placement scenarios.
  Square placements rendered 160 x 160 CSS pixels. Wide placements retained 2:1
  proportions when narrowed; no horizontal page overflow or page error occurred.
  Selected mobile screenshots were actually inspected.
- Independent final source review found no blocker in the visibility or placement
  changes.

All fixtures are explicitly synthetic and local. This does not certify arbitrary
Word round-trip fidelity, page fit, real bid-document quality or business signoff.
No external model or original-file upload was used, and no Docker service was
needed for these parser/component checks.

Final frontend gates pass: 2,107 tests across 212 files, formatting, lint, types
and production build. Existing build warnings remain.

## Existing synthetic DOCX corpus

The fourteen frozen DOCX files in the datasets repository's two explicitly
synthetic fixture sets were parsed with isolated f66e276 source and current
source in separate processes. Their allowed/rejected states, full section
content, mappings and issue records are identical: thirteen are applicable, while
the intentional dynamic-field example remains blocked. Each source-file SHA-256
was rechecked after reading. This is a synthetic compatibility replay, not proof
that a real bid's structure, facts or layout is correct. Temporary baseline source
copies were reconstructed from Git and precisely removed after the comparison.

## Prior exact CI

Before committing this image correction, f66e276 completed all eleven jobs in
[Workbench CI 43241847387](https://github.com/zys743551828-art/tender-app/actions/runs/43241847387).
That result covers the prior recovery fixes, not the image changes above.
