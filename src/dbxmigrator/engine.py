from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from .models import (
    Artifact,
    ArtifactMigrationStatus,
    MigrationDisposition,
    MigrationPlan,
    ReadinessStatus,
)
from .planning import MigrationPlanner
from .registry import ArtifactHandlerRegistry
from .store import MigrationStore


class MigrationEngine:
    def __init__(
        self,
        registry: ArtifactHandlerRegistry,
        store: MigrationStore,
    ) -> None:
        self.registry = registry
        self.store = store
        self.planner = MigrationPlanner(registry)

    def discover(self, context: Any) -> list[Artifact]:
        return self.planner.build_inventory(context)

    def create_dry_run(
        self,
        context: Any,
        configuration: dict[str, Any],
    ) -> MigrationPlan:
        plan = self.store.create_plan(configuration)
        artifacts = self.discover(context)
        plan.artifacts = self.planner.classify(context, artifacts, configuration)
        plan.dependency_edges = self.planner.build_dependency_graph(plan.artifacts)
        plan.lifecycle_state = "DRY_RUN"
        plan.blockers = sorted(
            {
                blocker
                for artifact in plan.artifacts
                for blocker in artifact.blockers
            }
        )
        plan.warnings = sorted(
            {
                warning
                for artifact in plan.artifacts
                for warning in artifact.warnings
            }
        )
        self.store.save_plan(plan)
        self.store.append_event(
            plan.migration_plan_id,
            {
                "event": "DRY_RUN_CREATED",
                "artifact_count": len(plan.artifacts),
                "mutating": False,
            },
        )
        return plan

    def approve_plan(
        self,
        migration_plan_id: str,
        approved_by: str,
        *,
        drift_check: bool = True,
        context: Any = None,
    ) -> MigrationPlan:
        plan = self.store.load_plan(migration_plan_id)
        if drift_check and context is not None:
            current = self.discover(context)
            current_hashes = {artifact.key: artifact.source_hash() for artifact in current}
            drifted = []
            for artifact in plan.artifacts:
                if current_hashes.get(artifact.key) != artifact.source_hash():
                    drifted.append(artifact.key)
            if drifted:
                plan.lifecycle_state = "DRIFT_BLOCKED"
                plan.blockers = sorted(set(plan.blockers).union(
                    f"Source drift detected for: {key}" for key in drifted
                ))
                plan.warnings = list(set(plan.warnings))
                self.store.save_plan(plan)
                self.store.append_event(
                    migration_plan_id,
                    {
                        "event": "APPROVAL_BLOCKED_DRIFT",
                        "artifacts": drifted,
                    },
                )
                return plan

        plan.approved_at = datetime.now(timezone.utc).isoformat()
        plan.approved_by = approved_by
        plan.lifecycle_state = "APPROVED"
        self.store.save_plan(plan)
        self.store.append_event(
            migration_plan_id,
            {
                "event": "PLAN_APPROVED",
                "approved_by": approved_by,
            },
        )
        return plan

    def drift_check(self, migration_plan_id: str, context: Any) -> dict[str, Any]:
        plan = self.store.load_plan(migration_plan_id)
        current = self.discover(context)
        current_hashes = {artifact.key: artifact.source_hash() for artifact in current}
        unchanged = []
        drifted = []
        missing = []
        approved_keys = {artifact.key for artifact in plan.artifacts}
        for artifact in plan.artifacts:
            if artifact.key not in current_hashes:
                missing.append(artifact.key)
            elif current_hashes[artifact.key] == artifact.source_hash():
                unchanged.append(artifact.key)
            else:
                drifted.append(artifact.key)
        new = sorted(set(current_hashes) - approved_keys)
        report = {
            "migration_plan_id": migration_plan_id,
            "unchanged": unchanged,
            "drifted": drifted,
            "missing": missing,
            "new": new,
        }
        self.store.append_event(
            migration_plan_id,
            {"event": "DRIFT_CHECK", "report": report},
        )
        return report

    def execute(
        self,
        migration_plan_id: str,
        context: Any,
    ) -> MigrationPlan:
        plan = self.store.load_plan(migration_plan_id)
        if plan.lifecycle_state != "APPROVED":
            raise PermissionError(
                "Execution requires an APPROVED migration plan; "
                f"current state is {plan.lifecycle_state}"
            )
        if plan.configuration.get("migration", {}).get("dry_run", True):
            raise PermissionError("Dry-run configuration cannot execute mutations")

        plan.lifecycle_state = "EXECUTING"
        self.store.save_plan(plan)
        for artifact in self.planner.topological_artifacts(plan.artifacts):
            if artifact.disposition in {
                MigrationDisposition.SKIP_BY_POLICY,
                MigrationDisposition.UNSUPPORTED,
            }:
                artifact.migration_status = (
                    ArtifactMigrationStatus.SKIPPED
                    if artifact.disposition == MigrationDisposition.SKIP_BY_POLICY
                    else ArtifactMigrationStatus.UNSUPPORTED
                )
                continue
            if artifact.disposition in {
                MigrationDisposition.BLOCKED_DEPENDENCY,
                MigrationDisposition.MANUAL_REQUIRED,
            }:
                artifact.migration_status = (
                    ArtifactMigrationStatus.BLOCKED
                    if artifact.disposition == MigrationDisposition.BLOCKED_DEPENDENCY
                    else ArtifactMigrationStatus.MANUAL_REQUIRED
                )
                continue
            if not artifact.migration_strategy:
                artifact.migration_status = ArtifactMigrationStatus.BLOCKED
                artifact.blockers.append("No migration strategy was selected")
                continue

            handler = self.registry.get(artifact.artifact_type)
            try:
                result = handler.migrate(context, artifact)
                artifact.metadata["migration_result"] = result
                artifact.migration_status = (
                    ArtifactMigrationStatus.MIGRATED
                    if handler.validate_migration(context, artifact)
                    else ArtifactMigrationStatus.BLOCKED
                )
                if artifact.migration_status == ArtifactMigrationStatus.MIGRATED:
                    readiness_ok = handler.validate_readiness(context, artifact)
                    artifact.readiness_status = (
                        ReadinessStatus.READY
                        if readiness_ok and not artifact.blockers
                        else ReadinessStatus.BLOCKED
                    )
            except NotImplementedError as exc:
                artifact.migration_status = ArtifactMigrationStatus.UNSUPPORTED
                artifact.readiness_status = ReadinessStatus.NOT_APPLICABLE
                artifact.blockers.append(str(exc))
            except Exception as exc:
                artifact.migration_status = ArtifactMigrationStatus.BLOCKED
                artifact.readiness_status = ReadinessStatus.BLOCKED
                artifact.blockers.append(f"Migration failed: {exc}")

            self.store.append_event(
                migration_plan_id,
                {
                    "event": "ARTIFACT_EXECUTED",
                    "artifact_key": artifact.key,
                    "migration_status": artifact.migration_status.value,
                    "readiness_status": artifact.readiness_status.value,
                },
            )
            self.store.save_plan(plan)

        plan.lifecycle_state = "VALIDATED"
        plan.blockers = sorted(
            {
                blocker
                for artifact in plan.artifacts
                for blocker in artifact.blockers
            }
        )
        self.store.save_plan(plan)
        self.store.append_event(
            migration_plan_id,
            {"event": "EXECUTION_VALIDATED", "plan_state": plan.lifecycle_state},
        )
        return plan

    def report(self, migration_plan_id: str) -> dict[str, Any]:
        plan = self.store.load_plan(migration_plan_id)
        migration_counts: dict[str, int] = {}
        readiness_counts: dict[str, int] = {}
        for artifact in plan.artifacts:
            migration_counts[artifact.migration_status.value] = (
                migration_counts.get(artifact.migration_status.value, 0) + 1
            )
            readiness_counts[artifact.readiness_status.value] = (
                readiness_counts.get(artifact.readiness_status.value, 0) + 1
            )
        by_type: dict[str, int] = {}
        for artifact in plan.artifacts:
            by_type[artifact.artifact_type.value] = (
                by_type.get(artifact.artifact_type.value, 0) + 1
            )
        return {
            "migration_plan_id": plan.migration_plan_id,
            "lifecycle_state": plan.lifecycle_state,
            "configuration": plan.configuration,
            "discovered_by_type": dict(sorted(by_type.items())),
            "migration_status_counts": migration_counts,
            "readiness_status_counts": readiness_counts,
            "blockers": plan.blockers,
            "warnings": plan.warnings,
            "artifacts": [artifact.to_dict() for artifact in plan.artifacts],
            "dependency_edges": plan.dependency_edges,
            "dry_run_mutations": False if plan.configuration.get("migration", {}).get("dry_run", True) else None,
        }
