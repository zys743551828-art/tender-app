# Native Word/PDF smoke, 2026-11-12

## Scope

The existing synthetic PAGE and RICH producer fixtures were assembled to DOCX and
actually converted to PDF through the unchanged project prebuilt adapter. The
backend source baseline was cf95f26; concurrent pending edits were frontend only.
This is a narrow producer/converter/inspector smoke check, not a real bid document,
full Desktop installation, database/Worker transport or business acceptance.

The image was the locked official Gotenberg 8.39.0 LibreOffice image, manifest
`sha256:298c3989049baf530afe7137b64374c22810bb863ef1ed91d256e33f335af161`.
The adapter checked immutable identity, network-none/non-root/read-only operation
and run ownership. No custom image, model call or external original was used.
The host was Windows CPython 3.12.14, pypdfium2 5.14.0 and Pillow 12.3.0; this must
not be described as a Linux Python 3.12.16 Worker runtime certification.

## Observations

- PAGE: succeeded, fixture correspondence complete, no reported gaps, two actual
  PDF pages. Body digits and literal PAGE/DDEAUTO text remain normal body text.
- RICH: succeeded, fixture correspondence complete, no reported gaps, two actual
  PDF pages after two navigation passes. A native merged table, embedded synthetic
  image, caption digits and the measured chapter/TOC page were retained.
- All four final rendered page images were actually inspected. No clipped body,
  missing glyph, missing table/image or incorrect displayed page number was seen
  in these small fixtures. This is not an arbitrary-layout fidelity claim.
- The existing output-rendering helper emitted two bitmap-close warnings while
  saving preview images. The conversion receipts succeeded and all saved images
  were checked; the warnings were not silently treated as production acceptance.

Output SHA-256 identities:

| Fixture | DOCX | PDF |
| --- | --- | --- |
| PAGE | e2f4fe2797686f05e1c679bd68945ff5c9b7f12486006c9c925f6ef41a99cbb4 | 89371bef8f90999434f7202b33e5576a67cee367ec9521a99099659fc8ece3a8 |
| RICH | 37f30e0d067f484c48c79ef1c9b051fc3eae56037080e649837bb45500ebf3eb | abb1646b8dcdf431a2283d02b6dd7e43b7e6a73061ffc7f41f3d300eb4d4b0f0 |

## Exact cleanup

The profile check created no container; the PAGE pass and two RICH passes each
created one run-owned container. All four resource receipts are closed and all
three containers are recorded removed. The pre-run Docker image/container lists
were empty. After confirming there were no remaining container references, only
the exact image downloaded for this smoke was removed without force. No user
volume or data was deleted; no global Docker prune was used. Local synthetic
outputs and resource receipts remain outside Git for review.
