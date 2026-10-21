from pathlib import Path

from dbxmigrator.config import MigrationConfig
from dbxmigrator.engine import MigrationEngine
from dbxmigrator.handlers import default_registry
from dbxmigrator.models import ArtifactMigrationStatus, ReadinessStatus
from dbxmigrator.store import MigrationStore


def make_context(**inventory):
    return {"inventory": inventory, **inventory}


def test_dry_run_is_non_mutating_and_separates_notebook_from_readiness(tmp_path):
    context = make_context(
        notebooks=[
            {
                "path": "/Shared/ETL/customer_processing",
                "object_id": 101,
                "language": "PYTHON",
                "content": "spark.table('raw.customer')",
            }
        ],
        secret_scopes=[],
    )
    engine = MigrationEngine(
        default_registry(),
        MigrationStore(tmp_path),
    )
    config = MigrationConfig(
        dry_run=True,
        unity_catalog_mode="NONE",
        source_workspace={"workspace": "source"},
        target_workspace={"workspace": "target"},
    )

    plan = engine.create_dry_run(context, config.to_dict())

    notebook = plan.artifacts[0]
    assert notebook.migration_status == ArtifactMigrationStatus.PLANNED
    assert notebook.readiness_status == ReadinessStatus.BLOCKED
    assert notebook.blockers
    assert plan.lifecycle_state == "DRY_RUN"
    assert "NO CHANGES" not in plan.to_dict().get("lifecycle_state", "")


def test_uc_none_does_not_mutate_or_require_uc_registration(tmp_path):
    context = {
        "inventory": {
            "notebooks": [{"path": "/Shared/test", "object_id": 1}],
            "hive_tables": [
                {"name": "raw.customer", "table_type": "MANAGED"}
            ],
        }
    }
    engine = MigrationEngine(default_registry(), MigrationStore(tmp_path))
    config = MigrationConfig(
        dry_run=True,
        unity_catalog_mode="NONE",
    )

    plan = engine.create_dry_run(context, config.to_dict())
    uc_artifacts = [
        artifact
        for artifact in plan.artifacts
        if artifact.metadata.get("dimension") == "GOVERNANCE"
    ]

    assert uc_artifacts
    assert all(
        artifact.metadata["no_automatic_uc_change"]
        for artifact in uc_artifacts
    )
    assert all(
        artifact.migration_status != ArtifactMigrationStatus.MIGRATED
        for artifact in uc_artifacts
    )


def test_execution_requires_approval(tmp_path):
    context = make_context(notebooks=[{"path": "/Shared/test", "object_id": 1}])
    engine = MigrationEngine(default_registry(), MigrationStore(tmp_path))
    plan = engine.create_dry_run(
        context,
        MigrationConfig(dry_run=False).to_dict(),
    )

    try:
        engine.execute(plan.migration_plan_id, context)
        assert False, "Execution should require approval"
    except PermissionError:
        pass


def test_assessment_only_discovers_without_target(tmp_path):
    context = make_context(
        notebooks=[{"path": "/Shared/test", "object_id": 1}],
        jobs=[{"job_id": 42, "settings": {"name": "nightly"}}],
        hive_tables=[{"name": "raw.customer", "table_type": "MANAGED"}],
    )
    engine = MigrationEngine(default_registry(), MigrationStore(tmp_path))
    config = MigrationConfig.from_dict(
        {
            "migration": {
                "scope": "ALL",
                "workspace_artifacts": True,
                "data": {"enabled": True},
                "unity_catalog": {"mode": "ASSESS"},
                "assessment_only": True,
                "dry_run": True,
            },
            "source": {
                "workspace": "source-workspace",
                "region": "eastus",
            },
        }
    )

    plan = engine.create_dry_run(context, config.to_dict())

    assert len(plan.artifacts) == 3
    assert all(
        artifact.metadata["assessment_only"]
        for artifact in plan.artifacts
    )
    assert all(
        artifact.metadata["target_required"] is False
        for artifact in plan.artifacts
    )
    assert plan.configuration["target"] == {}

    try:
        engine.execute(plan.migration_plan_id, context)
        assert False, "Assessment-only execution should be rejected"
    except PermissionError:
        pass


def test_assess_mode_without_target_infers_assessment_only(tmp_path):
    config = MigrationConfig.from_dict(
        {
            "migration": {
                "unity_catalog": {"mode": "ASSESS"},
                "dry_run": True,
            },
            "source": {"workspace": "source-workspace"},
        }
    )

    assert config.assessment_only is True
    assert config.target_workspace == {}


def test_approval_blocks_missing_and_new_source_artifacts(tmp_path):
    context = make_context(notebooks=[{"path": "/Shared/old", "object_id": 1}])
    engine = MigrationEngine(default_registry(), MigrationStore(tmp_path))
    config = MigrationConfig(
        dry_run=True,
        source_workspace={"workspace": "source"},
        target_workspace={"workspace": "target"},
    )
    plan = engine.create_dry_run(
        make_context(notebooks=[{"path": "/Shared/old", "object_id": 1}]),
        config.to_dict(),
    )
    changed_context = make_context(
        notebooks=[
            {"path": "/Shared/old", "object_id": 1},
            {"path": "/Shared/new", "object_id": 2},
        ]
    )

    approved = engine.approve_plan(
        plan.migration_plan_id,
        "operator",
        context=changed_context,
    )

    assert approved.lifecycle_state == "DRIFT_BLOCKED"
    assert any("new source artifact" in blocker.lower() for blocker in approved.blockers)


def test_execution_records_blocked_artifact_without_mutation(tmp_path):
    context = make_context(notebooks=[{"path": "/Shared/test", "object_id": 1}])
    engine = MigrationEngine(default_registry(), MigrationStore(tmp_path))
    plan = engine.create_dry_run(
        context,
        MigrationConfig(dry_run=False, target_workspace={"workspace": "target"}).to_dict(),
    )
    notebook = plan.artifacts[0]
    notebook.blockers = ["Unresolved target dependency"]
    plan.lifecycle_state = "APPROVED"
    engine.store.save_plan(plan)

    executed = engine.execute(plan.migration_plan_id, context)

    assert executed.lifecycle_state == "VALIDATED"
    executed_notebook = executed.artifacts[0]
    assert executed_notebook.migration_status == ArtifactMigrationStatus.BLOCKED
    assert executed_notebook.readiness_status == ReadinessStatus.BLOCKED


def test_cluster_discovery_and_migration_handler_are_available(tmp_path):
    context = make_context(
        clusters=[
            {
                "cluster_id": "source-cluster-1",
                "cluster_name": "analytics-cluster",
                "spark_version": "15.4.x-scala2.12",
                "node_type_id": "Standard_D4s_v5",
                "num_workers": 2,
            }
        ]
    )
    engine = MigrationEngine(default_registry(), MigrationStore(tmp_path))
    plan = engine.create_dry_run(
        context,
        MigrationConfig(
            dry_run=True,
            unity_catalog_mode="NONE",
            source_workspace={"workspace": "source"},
            target_workspace={"workspace": "target"},
        ).to_dict(),
    )

    cluster = next(
        artifact for artifact in plan.artifacts
        if artifact.artifact_type.value == "CLUSTER"
    )
    assert cluster.identity.source_id == "source-cluster-1"
    assert cluster.migration_strategy == "CREATE_CLUSTER_WITH_TARGET_CONFIGURATION"
    assert cluster.migration_provider == "Databricks SDK"


def test_menu_artifact_types_are_registered_for_assessment():
    context = make_context(
        clusters=[{"cluster_id": "cluster-1", "cluster_name": "cluster"}],
        pipelines=[{"pipeline_id": "pipeline-1", "name": "dlt"}],
        runs=[{"run_id": 101, "run_name": "historical-run"}],
        dashboards=[{"id": "dashboard-1", "name": "Sales"}],
        warehouses=[{"id": "warehouse-1", "name": "Analytics"}],
        queries=[{"id": "query-1", "name": "Revenue"}],
        alerts=[{"id": "alert-1", "name": "Threshold"}],
        experiments=[{"experiment_id": "exp-1", "name": "Experiment"}],
        models=[{"name": "customer-model", "model_id": "model-1"}],
        features=[{"name": "customer_features"}],
        agents=[{"id": "agent-1", "name": "Support"}],
        serving_endpoints=[{"name": "model-endpoint"}],
        catalogs=[{"name": "main"}],
        schemas=[{"catalog_name": "main", "name": "default"}],
        uc_functions=[{"catalog_name": "main", "name": "fn"}],
    )
    engine = MigrationEngine(default_registry(), MigrationStore("/tmp/dbxmigrator-menu-test"))
    plan = engine.create_dry_run(
        context,
        MigrationConfig(
            dry_run=True,
            assessment_only=True,
            unity_catalog_mode="ASSESS",
        ).to_dict(),
    )

    discovered_types = {artifact.artifact_type.value for artifact in plan.artifacts}
    expected = {
        "CLUSTER",
        "PIPELINE",
        "RUN",
        "DASHBOARD",
        "SQL_WAREHOUSE",
        "QUERY",
        "ALERT",
        "EXPERIMENT",
        "MODEL",
        "FEATURE",
        "AGENT",
        "SERVING",
        "CATALOG",
        "SCHEMA",
    }
    assert expected.issubset(discovered_types)
