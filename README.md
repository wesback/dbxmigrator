# Azure Databricks Workspace Migration Accelerator

> **Sample code warning:** This repository is a demonstration and reference implementation. It is not production-ready and must not be used to migrate production environments without extensive testing, security review, implementation of all required handlers, and approval by the responsible operators.

This accelerator inventories Databricks artifacts, builds a dependency graph, creates an approval-bound migration plan, and separates **migration completeness** from **workload runtime readiness**.

It is designed for migration between Azure Databricks workspaces in different regions. Workspace artifacts, physical data, and Unity Catalog governance are independent migration dimensions.

## What is included

- Artifact inventory and durable migration plans
- Notebook, job, pipeline, cluster, pool, policy, warehouse, dashboard, query, secret scope, MLflow, serving, data, and governance artifact models
- Separate migration and readiness statuses
- Dry-run by default
- Dependency graph and blocker reporting
- Plan approval and source drift detection
- Explicit Unity Catalog modes
- Databricks notebook entrypoint

## Architecture

```text
Artifact Inventory
       |
Dependency Graph
       |
Migration Planner
       |
       +-- Workspace Migration
       +-- Data Migration
       +-- Optional Unity Catalog Migration
       |
Validation
       |
       +-- Migration Completeness
       +-- Workload Readiness
```

## Quick start

1. Clone this repository into Databricks Repos in the source workspace.
2. Install the package on the migration notebook:

```python
%pip install -e /Workspace/Repos/wesback/dbxmigrator
```

Add Databricks SDK support with:

```python
%pip install -e "/Workspace/Repos/wesback/dbxmigrator[databricks]"
```

3. Import `notebooks/migration_accelerator.py` as a Databricks notebook.
4. Upload or place `config/example-migration.yaml` under `/Workspace/Shared/dbxmigrator/config.yaml`.
5. Update the source and target settings:
   - Source uses the notebook's Databricks SDK identity by default.
   - Target must be identified by its workspace URL under `target.host`.
   - Use `auth.type: DEFAULT`, `PROFILE`, or `TOKEN_SECRET`.
   - Store target tokens in a Databricks secret scope; never put tokens directly in YAML.
6. Set the notebook widgets:
   - `config_path` to the configuration path
   - `action` to `dry_run`
7. Run the notebook and save the reported `migration_plan_id`.

For the complete operator workflow, see [docs/manual.md](docs/manual.md).

## Workspace and authentication configuration

Source and destination workspaces are configured in the top-level `source` and `target` sections:

```yaml
source:
  workspace: source-workspace-name
  region: eastus
  host: https://adb-SOURCE-WORKSPACE.azuredatabricks.net
  auth:
    type: DEFAULT

target:
  workspace: target-workspace-name
  region: westus
  host: https://adb-TARGET-WORKSPACE.azuredatabricks.net
  auth:
    type: TOKEN_SECRET
    secret_scope: dbxmigrator
    secret_key: target-workspace-token
```

The notebook runs in the source workspace and creates one SDK client for discovery. It creates a separate SDK client for target mutations.

Supported authentication modes:

- `DEFAULT`: use SDK environment, notebook context, Azure identity, or other SDK-supported credentials.
- `PROFILE`: use `auth.profile` with a Databricks CLI profile.
- `TOKEN_SECRET`: resolve `auth.secret_scope` and `auth.secret_key` through the notebook's Databricks Secret utility.

Do not place `token`, `access_token`, `password`, or `client_secret` values in the migration YAML.

## Default safety behavior

Dry-run is the default. The accelerator must not mutate the source or target while `dry_run: true`.

Execution requires:

1. `dry_run: false`
2. A migration plan
3. Explicit approval of the plan ID
4. A successful approval-time drift check

Approved plans are stored as JSON under the configured plan store. Use a durable location such as `/dbfs/migration-plans` or a mounted or workspace-accessible storage location.

## Status model

Every artifact must have exactly one migration status and one readiness status.

### Migration statuses

| Status | Meaning |
|---|---|
| `MIGRATED` | The artifact was successfully recreated or moved |
| `PLANNED` | The artifact is selected and has a migration strategy |
| `SKIPPED` | Policy, dimension configuration, or selection excluded it |
| `BLOCKED` | Migration cannot proceed until a dependency or condition is resolved |
| `UNSUPPORTED` | No safe automatic implementation exists |
| `MANUAL_REQUIRED` | A human must complete migration or transformation |

### Readiness statuses

| Status | Meaning |
|---|---|
| `READY` | The artifact and its known target dependencies are ready |
| `WARNING` | The artifact may migrate, but review is required |
| `BLOCKED` | The workload cannot yet execute reliably |
| `UNKNOWN` | Readiness has not yet been proven |
| `NOT_APPLICABLE` | The artifact was not migrated or does not require runtime readiness |

Migration completeness and runtime readiness are intentionally independent. A notebook can be recreated successfully while remaining `BLOCKED` because one of its Hive tables is unresolved.

## Unity Catalog modes

Unity Catalog is optional and independent of workspace migration:

| Mode | Behavior |
|---|---|
| `NONE` | Inventories legacy Hive, DBFS, mounts, and storage dependencies, but performs no UC registration or migration |
| `ASSESS` | Creates proposed mappings and identifies blockers without changing UC |
| `REGISTER` | Registers selected external data without treating physical migration as registration |
| `MIGRATE` | Performs the approved Hive-to-UC migration for selected objects |

Workspace migration can proceed in `NONE` mode. UC state does not define workspace artifact identity or migration state.

## Configuration

The example configuration is [`config/example-migration.yaml`](config/example-migration.yaml):

```yaml
migration:
  scope: ALL
  workspace_artifacts: true
  data:
    enabled: true
  unity_catalog:
    mode: NONE
  conflict_strategy: FAIL
  dry_run: true
  storage:
    plan_store: /dbfs/migration-plans
```

Supported Unity Catalog modes, dimensions, and lifecycle states are described in [docs/manual.md](docs/manual.md).

## Development

Run the focused test suite from the repository root:

```bash
python3 -m pytest -q
```

Compile Python sources:

```bash
python3 -m compileall -q src tests notebooks
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for the full license text.
