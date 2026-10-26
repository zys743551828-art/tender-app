"""Reviewed module registration; no dynamic plugins, consumers or provider startup."""

from fastapi.routing import APIRoute


def mount(app):
    from apps.api.authoring_generation_batches import router as authoring_generation_batches
    from apps.api.authoring_rich import router as authoring_rich
    from apps.api.authoring_structure import router as authoring_structure
    from apps.api.authoring_word_import import router as authoring_word_import
    from apps.api.bid_package_rule_correction_routes import router as package_rule_corrections
    from apps.api.bid_package_submission_routes import router as package_submissions
    from apps.api.historical_input_routes import router as historical_input
    from apps.api.historical_routes import router as historical_proof
    from apps.api.lifecycle_routes import router as lifecycle
    from apps.api.model_admission_routes import router as admission
    from apps.api.model_governance_routes import router as governance
    from apps.api.model_registry_routes import router as registry
    from apps.api.package_business_shadow_routes import router as business_shadow
    from apps.api.package_model_admission_routes import router as package_admission
    from apps.api.package_model_certification_routes import router as package_certification
    from apps.api.package_model_registry_routes import router as package_registry
    from apps.api.package_prediction_report_routes import router as prediction_report
    from apps.api.package_prediction_routes import router as package_prediction
    from apps.api.package_prediction_task_routes import router as prediction_tasks
    from apps.api.package_unified_report_routes import router as unified_report
    from apps.api.scoring_routes import router as scoring
    from apps.api.task_draft_routes import router as task_drafts
    from apps.api.technical_scale_routes import router as technical_scale

    routers = (
        authoring_generation_batches,
        authoring_structure,
        authoring_rich,
        authoring_word_import,
        package_rule_corrections,
        package_submissions,
        technical_scale,
        lifecycle,
        task_drafts,
        governance,
        admission,
        historical_proof,
        historical_input,
        registry,
        package_registry,
        package_admission,
        package_certification,
        package_prediction,
        prediction_tasks,
        prediction_report,
        unified_report,
        business_shadow,
        scoring,
    )
    seen = {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    for router in routers:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in route.methods:
                key = (route.path, method)
                if key in seen:
                    raise RuntimeError("Duplicate reviewed operation registration")
                seen.add(key)
    for router in routers:
        app.include_router(router)


def extend_openapi(actual):
    from apps.api.composition_contracts import extend_lifecycle
    from packages.assistant.generation_batch_contracts import extend_openapi as generation_batches
    from packages.authoring.docx_import_contracts import extend_openapi as word_import
    from packages.authoring.rich_contracts import extend_openapi as rich
    from packages.authoring.structure_contracts import extend_openapi as structure
    from packages.contracts.package_rule_corrections_api import (
        extend_openapi as package_rule_corrections,
    )
    from packages.contracts.package_submissions_api import extend_openapi as package_submissions
    from packages.model_governance.contracts import extend_openapi as governance
    from packages.model_governance.historical_contracts import extend_openapi as historical_proof
    from packages.model_governance.historical_input_contracts import (
        extend_openapi as historical_input,
    )
    from packages.model_governance.registry_contracts import extend_openapi as registry
    from packages.model_governance.scale_contracts import extend_openapi as scale
    from packages.model_governance.scoring_contracts import extend_openapi as scoring
    from packages.tasks.contracts import extend_openapi as tasks

    # Target mappings run first. These projections only replace registered actual operations.
    for extension in (
        generation_batches,
        structure,
        rich,
        word_import,
        package_rule_corrections,
        package_submissions,
        governance,
        historical_proof,
        historical_input,
        registry,
        scoring,
        tasks,
        scale,
    ):
        extension(actual)
    extend_lifecycle(actual)
