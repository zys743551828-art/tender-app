"""Generate only schema types consumed by this UI, without inventing API routes."""

import argparse
import gzip
import json
from pathlib import Path

root = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser()
parser.add_argument(
    "--openapi", type=Path, default=root / "packages/contracts/fusion-implemented.openapi.json.gz"
)
parser.add_argument("--output", type=Path, default=root / "apps/web/src/contracts.ts")
parser.add_argument(
    "--schemas", help="Generate only these comma-separated schema roots, without capability flags"
)
args = parser.parse_args()
if args.openapi.suffix == ".gz":
    with gzip.open(args.openapi, "rt", encoding="utf-8") as source_file:
        contract = json.load(source_file)
else:
    contract = json.loads(args.openapi.read_text(encoding="utf-8"))
schemas = contract["components"]["schemas"]
history_schemas = [
    "PackageHistoricalAdmissionContext",
    "PackageHistoricalAdmission",
    "PackageHistoricalAdmissionView",
    "PackageHistoricalProtocol",
    "PackageHistoricalProtocolTemplate",
    "PackageHistoricalCohort",
    "PackageHistoricalCohortView",
    "PackageHistoricalJob",
    "PackageHistoricalJobView",
    "PackageHistoryAdmissionRequest",
    "PackageHistoryProtocolRequest",
    "PackageHistoryCohortRequest",
    "PackageHistoryJobRequest",
    "PackageHistoryJobControl",
    "PackageHistoryAdmissionDirectory",
    "PackageHistoryProtocolDirectory",
    "PackageHistoryCohortDirectory",
    "PackageHistoryJobDirectory",
]
wanted = [
    "PackageNextActions",
    "ProjectWorkSummary",
    "ProjectWorkSummaryBatch",
    *history_schemas,
    "AuthoringHistoricalSectionView",
    "AuthoringExactRevisionCapabilities",
    "AuthoringExactDraftStatus",
    "AuthoringExactRevisionView",
    "AuthoringExactManualRevisionView",
    "AuthoringExactTextEditCapabilities",
    "AuthoringExactTextEditRequest",
    "AuthoringExactTextEditResult",
    "AuthoringExactSectionBinding",
    "PackageAuthoringNodeCatalog",
    "PackageAuthoringFactSetPage",
    "PackageAuthoringFactCatalog",
    "PackageAuthoringSelection",
    "ExactPackageAuthoringSelection",
    "TaskPackageAuthoringResult",
    "PackageTaskAuthoringCapabilities",
    "PackageAuthoringInputRequest",
    "PackageAuthoringInputCapabilities",
    "PackageAuthoringInputView",
    "PackageAuthoringInputPage",
    "PackageAuthoringInputContext",
    "PackageAuthoringInputCheck",
    "PackageAuthoringInputStatus",
    "PackageAuthoringFactWithdrawal",
    "PackageAuthoringFactScopeView",
    "AuthoringWorkContext",
    "WorkContextChoicePage",
    "WorkContextAnySelection",
    "WorkContextDraftSelection",
    "WorkContextBuildSelection",
    "PackageWorkContext",
    "WorkContextRelationPage",
    "PricingRegisterPackageFormula",
    "PricingPackagePricingBinding",
    "PricingPackageSnapshot",
    "PricingPackageContext",
    "PackageTechnicalScopeRequest",
    "FreezePackageTechnicalScope",
    "PackageTechnicalScopePreview",
    "PackageTechnicalScopeView",
    "PackageTechnicalScopeApplied",
    "PackageTechnicalScopeContext",
    "PackageTechnicalScopePage",
    "PackageTechnicalScoringContext",
    "PackageTechnicalSampleContext",
    "PackageTechnicalExecutionContext",
    "CreatePackageTechnicalExecution",
    "KnowledgePackageReviewTargetPage",
    "HistoricalImportRequest",
    "HistoricalImportBatch",
    "HistoricalImportReceipt",
    "HistoricalImportPage",
    "HistoricalImportSource",
    "PackageRuleCorrectionRequest",
    "ApplyPackageRuleCorrection",
    "PackageRuleCorrectionPreviewView",
    "PackageRuleCorrectionView",
    "PackageRuleCorrectionAppliedView",
    "PackageRuleCorrectionHistoryPage",
    "PackageRuleCorrectionDetail",
    "PackageRuleCorrectionEvidencePage",
    "PackageRuleCorrectionEvidenceDetail",
    "AuthoringGenerationBatchCreateRequest",
    "AuthoringGenerationBatchRetryRequest",
    "AuthoringGenerationBatchResolveRequest",
    "AuthoringGenerationBatchReceipt",
    "AuthoringGenerationBatch",
    "AuthoringGenerationBatchPage",
    "AuthoringGenerationBatchCandidate",
    "AuthoringGenerationBatchCapabilities",
    "AuthoringWordImportPrepareRequest",
    "AuthoringWordImportResolveRequest",
    "AuthoringWordImportCandidate",
    "AuthoringWordImportResult",
    "AuthoringWordImportPage",
    "AuthoringWordImportCapabilities",
    "DocumentParseContext",
    "StartDocumentParse",
    "DocumentParseView",
    "DocumentParseStarted",
    "DocumentParsePage",
    "AdoptAuthoringOutput",
    "AuthoringOutputAdopted",
    "AuthoringOutputQualification",
    "PackageReviewReportContext",
    "StartPackageReviewReport",
    "PackageReviewReportView",
    "PackageReviewReportPage",
    "PackageReviewComparisonPage",
    "PackageReviewComparisonRun",
    "PackageReviewComparisonRow",
    "PackageReviewComparisonRowSide",
    "StartPackageReviewRun",
    "PackageReviewRunInput",
    "PackageReviewRunInputView",
    "PackageReviewRunView",
    "PackageReviewRunSummary",
    "SavePackageReviewHumanDecision",
    "PackageReviewHumanDecision",
    "PackageReviewHumanDecisionView",
    "PackageReviewHumanDecisionCurrent",
    "PackageReviewHumanDecisionPage",
    "AuthoringRichCapabilities",
    "AuthoringRichBuildRequest",
    "AuthoringRichDocument",
    "AuthoringImageUpload",
    "AuthoringImageCreated",
    "AuthoringImageView",
    "AuthoringImagePage",
    "AuthoringImageUploadStatus",
    "AuthoringBuildLayout",
    "PackageReviewRunPage",
    "PackageReviewResult",
    "SavePackageDependencyPlan",
    "PackageDependencyPlanView",
    "PackageDependencyPlanPage",
    "CheckPackageInputDependencies",
    "PackageInputDependencyAssessment",
    "ConfirmPackageFact",
    "WithdrawPackageFact",
    "PackageFactChangeView",
    "PackageCurrentFactPage",
    "PackageCurrentFactDetail",
    "PackagePreparedFactPage",
    "ChangePackageFactScope",
    "PackageFactScopeView",
    "PackageFactScopeObservation",
    "CheckPackageExecutionFacts",
    "PackageExecutionFactCheck",
    "SavePackageExecutionInput",
    "PackageExecutionInputView",
    "CheckPackageReviewEligibility",
    "PackageReviewEligibilityObservation",
    "PackageReviewFrozenInputPage",
    "FreezePackageReviewInput",
    "PackageReviewFrozenInputView",
    "PackageReviewOriginalVerification",
    "PackageReviewOriginalVerificationRequest",
    "PackageReviewInputPreviewRequest",
    "PackageReviewInputManifest",
    "PackageReviewInputPreview",
    "CreatePackageRequirementInventory",
    "CreatePackageCoverageAttempt",
    "PackageRequirementInventoryManifest",
    "PackageCoverageAttemptManifest",
    "PackageRequirementInventoryView",
    "PackageCoverageAttemptView",
    "PackageRequirementInventoryPage",
    "PackageRequirementHistoryPage",
    "CreateBidPackage",
    "AppendBidPackage",
    "BidPackageStoredView",
    "BidPackageManifest",
    "BidPackageHeadPage",
    "BidPackageRevisionSummaryPage",
    "BidPackageDocumentPage",
    "BidPackageParsePage",
    "PackageEvidencePage",
    "AuthoringTemplateCreate",
    "AuthoringTemplateVersion",
    "WordOriginalView",
    "WordOriginalPage",
    "WordMaterialAdoptionView",
    "AuthoringTreeView",
    "AuthoringTreeChangeRequest",
    "AuthoringStructurePreview",
    "AuthoringStructureResult",
    "AuthoringStructureHistory",
    "AuthoringStructureRestorePreview",
    "AuthoringPlanSave",
    "AuthoringPlanSaved",
    "AuthoringTemplateCatalog",
    "AuthoringTemplateVersionView",
    "AuthoringDirectoryApplyPreview",
    "AuthoringStyleApplyPreview",
    "AuthoringStylePreview",
    "WorkConversationView",
    "WorkConversationStateRequest",
    "WorkMessageRequest",
    "WorkMessageView",
    "WorkMessagePage",
    "AssistantTurnRequest",
    "AssistantJob",
    "AssistantJobPage",
    "AssistantGlobalConversation",
    "AssistantGlobalMessagePage",
    "AssistantGlobalEventPage",
    "AssistantSourcePage",
    "AssistantAction",
    "AssistantActionResolveRequest",
    "AssistantSourceRef",
    "AssistantAnswerPart",
    "TemplateRequest",
    "ExactPackageTriggerSelection",
    "PackageTaskTriggerCapabilities",
    "PackageTriggerIntentView",
    "PackageTriggerIntentPage",
    "TemplateView",
    "TemplatePage",
    "TemplateVersionView",
    "RunRequest",
    "TaskAuthoringResult",
    "RunView",
    "RunPage",
    "PauseRequest",
    "TaskKindPage",
    "TaskNotificationPage",
    "TaskScheduleRecoveryPage",
    "TaskDraftRequest",
    "TaskDraftView",
    "TaskDraftPage",
    "KnowledgeRetrievalRequest",
    "KnowledgeRetrievalResult",
    "KnowledgeRetrievalHistory",
    "KnowledgeUnitReferenceRequest",
    "KnowledgeUnitReference",
    "KnowledgeUnitReferenceHistory",
    "KnowledgeIndexRequest",
    "KnowledgeIndexAccepted",
    "KnowledgeIndexPage",
    "BusinessResultRequest",
    "BusinessResultCorrectionRequest",
    "BusinessResultVerificationRequest",
    "BusinessResultView",
    "BusinessResultPage",
    "BusinessMetricsView",
    "UploadBatchPage",
    "GateView",
    "SubmissionRequest",
    "OfflineSubmissionRequest",
    "SubmissionView",
    "SingleBodySubmissionView",
    "PackageSubmissionSelection",
    "PackageSubmissionRequest",
    "PackageSubmissionPreview",
    "PackageSubmissionBindingView",
    "PackageSubmissionView",
    "PackageSubmissionAppliedView",
    "PackageSubmissionGateView",
    "PackageOutcomeContext",
    "PackageOutcomeVerificationRequest",
    "PackageOutcomeVerificationDetails",
    "OutcomeRequest",
    "SubmissionPage",
    "SubmissionDocumentPage",
    "SubmissionCorrectionRequest",
    "ReportContextView",
    "ReportRequest",
    "ReportExportPage",
    "ReportExportView",
    "PricingContext",
    "PricingFormulaSourcePage",
    "PricingRegisterFormula",
    "PricingFormulaPage",
    "PricingFormulaView",
    "PricingRequest",
    "PricingSimulationView",
    "PricingSavePlan",
    "PricingPlanView",
    "PricingPlanPage",
    "PricePoint",
    "UploadLayoutView",
    "KnowledgeCandidate",
    "KnowledgeView",
    "KnowledgePage",
    "KnowledgeVersionRequest",
    "KnowledgeVersionPage",
    "KnowledgeReferenceRequest",
    "KnowledgeReferenceHistory",
    "KnowledgeImpact",
    "KnowledgeSourcePositions",
    "BiddingCompanyPage",
    "DefaultBiddingCompanyView",
    "EngineeringIdentityPage",
    "EngineeringRoundPage",
    "BidIdentityView",
    "BidIdentityCorrection",
    "CorrectBidIdentity",
    "RegisterBidder",
    "RegisteredBiddingCompanyView",
    "SelectDefaultBidder",
    "ResearchCapabilities",
    "ResearchHistoryPage",
    "ResearchOutcomePage",
    "ResearchOutcomeDetail",
    "ResearchSamplePage",
    "ResearchGroupingView",
    "ResearchGroupingRequest",
    "AuthoringDocument",
    "AuthoringNode",
    "AuthoringCapabilities",
    "AuthoringDraftPage",
    "AuthoringRevisionPage",
    "AuthoringPreviewRequest",
    "AuthoringPreview",
    "AuthoringSnapshot",
    "AuthoringSectionAdded",
    "EvidenceAuthoringReferenceView",
    "CreateDraftRequest",
    "DraftView",
    "SectionView",
    "SaveDraft",
    "DraftSaved",
    "BuildRequest",
    "BuildView",
    "BuildPage",
    "BatchRuleConfirmation",
    "RuleDecisionRequest",
    "FactDecisionRequest",
    "FindingDecisionRequest",
    "RestoreAuthoringSection",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievalHit",
    "ReviewStateView",
    "ReviewPage",
    "ReviewManifest",
    "ReviewView",
    "RuleSetView",
    "FactSetView",
    "FindingPage",
    "MatrixView",
    "SettingsView",
    "DecisionRequest",
    "BatchRuleConfirmationRequest",
    "BatchRuleConfirmationView",
    "FactChangeRequest",
    "Cancellation",
    "DiagnosticPage",
    "ReviewRequest",
    "RuleSetCorrectionRequest",
    "DocumentEvidenceView",
    "DownloadGrant",
    "EvidenceView",
    "AuthView",
    "Bid",
    "BidPage",
    "CreateBid",
    "UploadGrant",
    "UploadPartsView",
    "RefreshUploadRequest",
    "UploadRequest",
    "UploadView",
    "UploadBatchView",
    "UploadBindingView",
    "UploadBindingRequest",
    "BatchCommit",
    "MaterialView",
    "DocumentView",
    "Accepted",
    "Operation",
    "UploadComplete",
    "UploadTarget",
]
if args.schemas:
    wanted = args.schemas.split(",")
seen = set()


def render(s):
    if "$ref" in s:
        name = s["$ref"].split("/")[-1]
        if name not in wanted:
            wanted.append(name)
        return name
    if "const" in s:
        return json.dumps(s["const"], ensure_ascii=False)
    if "enum" in s:
        return " | ".join(json.dumps(x, ensure_ascii=False) for x in s["enum"])
    for union in ["oneOf", "anyOf"]:
        if union in s:
            return "(" + " | ".join(render(x) for x in s[union]) + ")"
    typ = s.get("type")
    if isinstance(typ, list):
        return " | ".join(render(dict(s, type=x)) for x in typ)
    if typ == "object" and not s.get("properties"):
        if s.get("additionalProperties") is False:
            return "Record<string, never>"
        value_type = (
            render(s["additionalProperties"])
            if isinstance(s.get("additionalProperties"), dict)
            else "unknown"
        )
        return "{ [key: string]: " + value_type + " }"
    if typ == "object":
        req = s.get("required", [])
        return (
            "{\n"
            + "".join(
                f"  {json.dumps(k)}" + ("" if k in req else "?") + ": " + render(v) + ";\n"
                for k, v in s.get("properties", {}).items()
            )
            + "}"
        )
    if typ == "array":
        if s.get("maxItems") == 0:
            return "[]"
        return "(" + render(s.get("items", {})) + ")[]"
    return {
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
        "string": "string",
    }.get(typ, "unknown")


source = (
    "packages/contracts/fusion-implemented.openapi.json.gz"
    if args.openapi == root / "packages/contracts/fusion-implemented.openapi.json.gz"
    else str(args.openapi)
)
lines = [f"// Generated from {source}. Run python scripts/generate-contracts.py.\n"]
for name in wanted:
    if name not in seen:
        seen.add(name)
        lines.append(f"export type {name} = {render(schemas[name])};\n")
args.output.write_text("\n".join(lines), encoding="utf-8")
if args.schemas:
    raise SystemExit(0)

# These closed runtime schemas come from the same actual API as the TypeScript
# types. Keep the research result's null/decimal/count and no-qualification
# constants intact instead of maintaining a second hand-written shape.
history_runtime = {}


def collect_history_schema(name):
    if name in history_runtime:
        return
    history_runtime[name] = schemas[name]

    def visit(value):
        if isinstance(value, dict):
            if "$ref" in value:
                collect_history_schema(value["$ref"].rsplit("/", 1)[-1])
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(schemas[name])


for name in history_schemas:
    collect_history_schema(name)
args.output.with_name("packageHistoricalResearchSchemas.ts").write_text(
    f"// Generated from {source}. Run python scripts/generate-contracts.py.\n"
    "export const historySchemas: Record<string, unknown> = "
    + json.dumps(history_runtime, ensure_ascii=False, indent=2)
    + ";\n",
    encoding="utf-8",
)

operations = [
    f"{method.upper()} {path}"
    for path, methods in contract["paths"].items()
    for method in methods
    if method in {"get", "post", "patch", "put", "delete"}
]
with args.output.open("a", encoding="utf-8") as output:
    output.write(
        "\nexport const implementedOperations: readonly string[] = "
        + json.dumps(operations, ensure_ascii=False)
        + ";\n"
    )

with args.output.open("a", encoding="utf-8") as output:
    batch_limit = schemas["BatchRuleConfirmation"]["properties"]["rule_ids"]["maxItems"]
    output.write(f"\nexport const ruleConfirmationLimit: number = {batch_limit};\n")

with args.output.open("a", encoding="utf-8") as output:
    task_create = (
        contract["paths"].get("/api/v1/bids/{bid_id}/task-definitions", {}).get("post", {})
    )
    task_request = (
        task_create.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
        .get("$ref")
    )
    output.write(
        "\nexport const taskTemplatesContractReady: boolean = "
        + str(task_request == "#/components/schemas/TemplateRequest").lower()
        + ";\n"
    )
