"""Current section authority, including imported text and reused embedded images.

The returned manifest uses the existing source-head protocol. Workers can fence
model calls against it without reading API-owned import candidates or draft trees.
"""

from packages.authoring import rich_assets, rich_snapshots, snapshot_structure
from packages.authoring.repository import source_authority_manifest

_CURRENT = object()


def authority(c, bid, draft, section, content, *, additional_refs=(), extension=_CURRENT):
    if extension is _CURRENT:
        extension = snapshot_structure.assert_active(c, bid, draft, section)
    identities = {ref["source_id"] for ref in [*content["attrs"]["source_refs"], *additional_refs]}
    if extension is not None and "word_import_sources" in extension["metadata"]:
        from packages.authoring.docx_import_sources import assert_import_sources

        imported = assert_import_sources(c, bid, extension["metadata"], section_ids=[str(section)])
        identities.update(imported["direct_source_ids"])
    images = rich_snapshots.identities([content])
    if images:
        from packages.authoring.docx_import_sources import image_import_source_ids

        for image in rich_assets.freeze_assets(c, bid, images):
            identities.update(ref["source_id"] for ref in image["source_refs"])
            identities.update(image_import_source_ids(image["normalization_proof"]))
    return source_authority_manifest(c, [{"source_id": value} for value in sorted(identities)])
