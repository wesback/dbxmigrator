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

### Install without cloning into Databricks Repos

From a source-workspace Databricks notebook:

```python
%pip install "dbxmigrator[databricks] @ git+https://github.com/wesback/dbxmigrator.git@main"
dbutils.library.restartPython()
```

The package name matches the project metadata and Python import package. Upgrade an existing installation with:

```python
%pip install --upgrade "dbxmigrator[databricks] @ git+https://github.com/wesback/dbxmigrator.git@main"
dbutils.library.restartPython()
```

If `ModuleNotFoundError: No module named 'dbxmigrator'` persists after installation:

1. Confirm that the package installed successfully in the notebook environment.
2. Restart the Python process with `dbutils.library.restartPython()`.
3. Detach and reattach a Spark cluster if package caches remain stale.
4. If the notebook is imported without package installation, leave the `package_source` widget at its GitHub default; it attempts an automatic fallback installation.

### Install from Databricks Repos

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

## Assessment-only mode

Use assessment-only mode when source discovery must happen before a target workspace exists:

```yaml
migration:
  scope: ALL
  workspace_artifacts: true
  data:
    enabled: true
  unity_catalog:
    mode: ASSESS
  assessment_only: true
  dry_run: true

source:
  workspace: source-workspace-name
  region: eastus
  auth:
    type: DEFAULT

# The target section is optional in this mode.
```

Assessment-only plans inventory source workspace, data, Hive, DBFS, and governance dependencies. They produce migration and dependency records without creating a target client, registering UC objects, copying data, or recreating artifacts.

Setting `unity_catalog.mode: ASSESS` enables assessment behavior. Setting `assessment_only: true` prevents any execution. A target can be added later by creating a new migration plan or changing the plan configuration and explicitly setting `assessment_only: false`.

## Default safety behavior

Dry-run is the default. The accelerator must not mutate the source or target while `dry_run: true`.

Execution requires:

1. `dry_run: false`
2. A migration plan
3. Explicit approval of the plan ID
4. A successful approval-time drift check

Approved plans are stored as JSON under the configured plan store. Use a durable workspace location such as `/Workspace/Shared/dbxmigrator/plans`.

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

## Databricks menu artifact coverage

The screenshot's Databricks workspace menu is audited against the registered artifact handlers. The current implementation covers:

| Menu area | Artifact coverage |
|---|---|
| Workspace | Notebooks and workspace files |
| Jobs / Runs | Jobs and job-run inventory; run history is audit data, not a normal recreation target |
| Compute | Interactive clusters, cluster policies, and instance pools |
| SQL | Warehouses, SQL queries, dashboards, alerts, and warehouse/query dependencies |
| Data Engineering | Pipelines and data ingestion configuration |
| Catalog | Unity Catalog catalogs, schemas, tables, volumes, functions, credentials, locations, and mounts |
| AI/ML | Experiments, registered models, features, serving endpoints, agents, and apps where SDK/API discovery is available |
| Query History | Inventory-only audit surface; not an executable migrated workspace artifact |
| Marketplace, Genie Agents, Playground, and some preview surfaces | Recorded as assessment candidates or manual-only when a stable migration API is unavailable |

Clusters are move candidates. The accelerator copies cluster configuration to the target and validates target cluster existence. Cluster policy, instance pool, init-script, secret, identity, network, and library dependencies are separately resolved for runtime readiness. Interactive clusters may contain ephemeral state and should not be treated as data-migration mechanisms.

Every handler must produce a ledger disposition. Unsupported surfaces are never silently omitted.

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
    plan_store: /Workspace/Shared/dbxmigrator/plans
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
