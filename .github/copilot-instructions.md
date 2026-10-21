# Copilot instructions

## Repository purpose

This repository is a sample/reference Azure Databricks workspace migration accelerator. It is not production-ready. Treat migration behavior as safety-sensitive and do not weaken dry-run, approval, credential, or drift checks.

The implementation inventories workspace artifacts, builds dependencies, classifies migration dispositions, persists a migration plan, and optionally executes approved target mutations. Unity Catalog, physical data, and workspace migration are separate dimensions.

## Build, test, and lint

Install the repository locally:

```bash
python3 -m pip install -e ".[dev]"
python3 -m pip install -e ".[dev,databricks]"
```

Run the full test suite:

```bash
python3 -m pytest -q
```

Run one test file or one test:

```bash
python3 -m pytest -q tests/test_engine.py
python3 -m pytest -q tests/test_engine.py::test_execution_requires_approval
```

Compile the package, tests, and notebook:

```bash
python3 -m compileall -q src tests notebooks
```

There is no repository lint or formatting configuration currently defined in `pyproject.toml`; do not invent tool-specific lint commands without adding configuration.

## High-level architecture

- `src/dbxmigrator/models.py` defines artifact identities, dependency edges, lifecycle/status enums, and serialization for `Artifact` and `MigrationPlan`. Artifact source hashes cover identity and source definition.
- `src/dbxmigrator/registry.py` defines the `ArtifactHandlerRegistry` and fallback handler behavior.
- `src/dbxmigrator/handlers.py` contains discovery and migration implementations. `default_registry()` is the central registration point for all supported artifact types.
- `src/dbxmigrator/planning.py` builds inventory, analyzes dependencies, classifies artifacts using migration configuration, creates the dependency graph, and orders artifacts topologically.
- `src/dbxmigrator/engine.py` coordinates dry-run creation, source drift checks, approval, execution, validation, reporting, plan events, and lifecycle transitions.
- `src/dbxmigrator/store.py` persists plans as JSON and append-only events as JSONL. It normalizes legacy `/dbfs/...` roots to `/Workspace/Shared/...`.
- `src/dbxmigrator/config.py` is the YAML/JSON configuration boundary and infers assessment-only behavior when Unity Catalog is assessed without a target.
- `src/dbxmigrator/auth.py` constructs separate source and target SDK clients and rejects credentials embedded in configuration.
- `src/dbxmigrator/report.py` renders the migration/readiness summary used by the notebook.
- `notebooks/migration_accelerator.py` is the Databricks notebook entrypoint. It exposes `dry_run`, `approve`, `drift_check`, `execute`, and `report` actions through notebook widgets.
- `docs/manual.md` contains the operator workflow and configuration detail; `config/example-migration.yaml` is the shortest runnable configuration template.

The normal lifecycle is discovery/inventory, dependency analysis, classification, durable dry-run plan, explicit approval plus drift check, guarded execution, artifact migration validation, readiness validation, and reporting.

## Key repository conventions

### Preserve safety boundaries

- Dry run is the default and must remain discovery/planning-only.
- Execution requires `dry_run=false`, target configuration, an `APPROVED` plan, and assessment-only to be false.
- Approval performs source drift validation; changing configuration creates a new plan rather than silently modifying an existing plan.
- Separate migration completeness and workload runtime readiness. Do not infer readiness from successful migration alone.
- No credentials belong in YAML, plans, notebook output, or source definitions. Supported target authentication is `DEFAULT`, `PROFILE`, or `TOKEN_SECRET`; `TOKEN_SECRET` resolves a scope/key through the Databricks secrets utility.

### Extend artifact support through handlers

- Add a type to `ArtifactType` when the new artifact needs a distinct identity or status behavior.
- Implement discovery, optional dependency analysis, planning, migration, and validation in an `ArtifactHandler`.
- Register each handler from `default_registry()` for the artifact types it owns.
- `NotebookHandler` and `ClusterHandler` contain concrete SDK implementations. Use `GenericInventoryHandler` for inventory/planning-only surfaces whose SDK/API migration behavior is still manual or unsupported.
- Discovery must support both dict-based test inventories and Databricks SDK context. New handlers should preserve that dual path where practical.
- Unsupported, blocked, skipped, and manual surfaces must produce a ledger disposition and status. Do not silently omit them.

### Artifact data model

- Artifact keys follow `TYPE:identifier`, for example `NOTEBOOK:/Shared/path` and `CLUSTER:cluster-id`.
- Every artifact has exactly one migration status (`MIGRATED`, `PLANNED`, `SKIPPED`, `BLOCKED`, `UNSUPPORTED`, or `MANUAL_REQUIRED`) and one readiness status (`READY`, `WARNING`, `BLOCKED`, `UNKNOWN`, or `NOT_APPLICABLE`).
- Dependency edges are serialized with source key, target key, dependency type, reference, and resolution.
- `MigrationDisposition` determines execution behavior; classify policy exclusions, blockers, manual work, and unsupported work explicitly.
- Preserve both structured blockers/warnings and migration metadata so reports and plans remain auditable.

### Planning and execution

- Inventory is deduplicated by artifact key.
- Dependency analysis happens before classification and before topological execution.
- Workspace artifacts, data artifacts, and governance artifacts are dimensions handled independently by configuration.
- In `unity_catalog.mode=NONE`, Hive/DBFS-style governance dependencies remain inventory/blocker information rather than automatic UC mutations.
- `MigrationPlanner.topological_artifacts()` expects dependencies to use known target keys; execution should tolerate missing or unresolved dependencies without mutating silently.
- Durable plans live under the configured `storage.plan_store`; legacy DBFS roots are normalized by `MigrationStore`.

### Testing patterns

- Prefer `tmp_path` migration stores and dict-based inventories such as `make_context(...)` in tests.
- Engine tests verify lifecycle guards, dry-run behavior, approval/drift behavior, assessment-only behavior, and status separation.
- Tests can inject fake SDK client classes, as in `tests/test_auth.py`, to verify authentication without external credentials.
