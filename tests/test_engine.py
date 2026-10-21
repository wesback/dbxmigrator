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
