"""Optional trusted host adapter for complete current material page derivation.

No Docker socket or environment discovery enters the API, Worker or pure model
ports. The operator supplies a pinned FusionAssetRuntime. Receipts remain separate
from material authority and describe actual stopped named Compose sessions only.
"""

from deploy.fusion_asset_runtime import FusionAssetRuntime


class FusionMaterialPages:
    def __init__(self, runtime: FusionAssetRuntime):
        self.runtime = runtime
        self.profile = runtime.describe()
        self.receipts = [self.profile["execution_receipt"]]

    @property
    def render_method_digest(self):
        return self.profile["render_method_digest"]

    def __call__(self, data, document):
        result = self.runtime.render(
            data,
            document_version_id=document["document_version_id"],
            expected_source_digest=document["source_digest"],
            expected_source_size=document["source_byte_size"],
            expected_render_method_digest=self.render_method_digest,
            expected_crop_method_digest=self.profile["crop_method_digest"],
            regions=[],
        )
        self.receipts.append(result.execution_receipt)
        return result.bundle
