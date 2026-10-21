# Databricks Migration Accelerator Manual

> **Sample code warning:** This manual describes sample/reference code that is not production-ready. Do not use it for production migrations without completing implementation, security, identity, data, operational, and disaster-recovery requirements and obtaining approval from the responsible operators.

## Purpose

Use this accelerator to inventory and migrate an Azure Databricks environment from a source workspace in one region to a target workspace in another region.

The accelerator does not treat Unity Catalog, physical data migration, or workspace migration as a single operation. Each dimension can be enabled, assessed, or left unchanged independently.

## Prerequisites

- The migration notebook runs in the source workspace.
- The source identity can discover the source workspace artifacts.
- The target identity can perform the approved target mutations.
- Source and target workspaces are configured in the migration file.
- Target identities, clusters, jobs, pools, warehouses, secrets, storage, and Unity Catalog resources are known.
- The repository package and dependencies are installed on the migration notebook cluster.

Example package installation:

For a clone-free installation from the source-workspace notebook:

```python
%pip install "dbxmigrator[databricks] @ git+https://github.com/wesback/dbxmigrator.git@main"
dbutils.library.restartPython()
```

For an installation from Databricks Repos:

```python
%pip install -e "/Workspace/Repos/wesback/dbxmigrator[databricks]"
dbutils.library.restartPython()
```

Store credentials in Databricks secrets. Do not place access tokens in the migration YAML or in notebook output.

## Installation in a workspace

1. Add the repository under Databricks Repos.
2. Open `notebooks/migration_accelerator.py`.
3. Attach a cluster with network access to the Databricks control plane and required storage.
4. Install the package and `databricks-sdk`.
5. Open the notebook configuration widgets.

The notebook supports these prefixes:

| Prefix | Location |
|---|---|
| `/Workspace/...` | Databricks workspace file |
| `workspace:/...` | Databricks workspace file |
| `dbfs:/...` | DBFS-mounted file |
| No prefix | Local filesystem path on the notebook cluster |

## Configuration

Create a YAML or JSON configuration. YAML is recommended.

### Full example

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

  include_artifact_types: []
  exclude_artifact_types: []

  storage:
    plan_store: /dbfs/migration-plans

source:
  workspace: source-workspace-name
  workspace_id: "1234567890123456"
  region: eastus
  host: https://adb-1234567890123456.azuredatabricks.net
  auth:
    type: DEFAULT

target:
  workspace: target-workspace-name
  workspace_id: "9876543210987654"
  region: westus
  host: https://adb-9876543210987654.azuredatabricks.net
  auth:
    type: TOKEN_SECRET
    secret_scope: dbxmigrator
    secret_key: target-workspace-token
```

### Configuration fields

| Field | Purpose |
|---|---|
| `migration.scope` | Use `ALL` to inventory all supported artifact types |
| `migration.workspace_artifacts` | Enable or disable workspace artifact planning |
| `migration.data.enabled` | Enable or disable data migration planning |
| `migration.unity_catalog.mode` | Set `NONE`, `ASSESS`, `REGISTER`, or `MIGRATE` |
| `migration.conflict_strategy` | Define target conflict behavior; supported planning value is currently `FAIL` |
| `migration.dry_run` | Must remain `true` during discovery and review |
| `migration.include_artifact_types` | Optional allowlist of artifact types |
| `migration.exclude_artifact_types` | Optional denylist of artifact types |
| `migration.storage.plan_store` | Durable directory for plans and event ledgers |
| `source` | Source workspace identity and regional metadata |
| `target` | Target workspace identity and regional metadata |
| `source.host` | Optional source workspace URL |
| `target.host` | Required target workspace URL for target SDK authentication |
| `source.auth` / `target.auth` | Authentication configuration; credentials must not be written into YAML |

## Workspace and authentication configuration

Source and destination workspaces are defined in the top-level `source` and `target` sections.

The source workspace is the workspace where the migration notebook runs. The source SDK client uses:

- The notebook's Databricks SDK environment by default
- An optional `source.host` URL
- An optional Databricks CLI profile
- A secret-backed token only when explicitly configured

The target workspace is identified by `target.host`, which should be the target workspace URL. It uses a separate SDK client so source discovery and target mutation do not share identity assumptions.

Supported authentication modes:

| Mode | Configuration | Recommended use |
|---|---|---|
| `DEFAULT` | `auth.type: DEFAULT` | Source workspace or environments where the SDK has an automatic notebook identity and host |
| `PROFILE` | `auth.type: PROFILE`, plus `auth.profile` | Interactive or local SDK credentials with an existing Databricks CLI profile |
| `TOKEN_SECRET` | `auth.type: TOKEN_SECRET`, `auth.secret_scope`, `auth.secret_key`, and `target.host` | Secret-backed token authentication in the migration notebook |

`DEFAULT` authentication never reads a token from migration YAML. Depending on SDK configuration, it can use the current Databricks environment, environment variables, Azure identity, or configured SDK credentials.

Example profile authentication:

```yaml
source:
  host: https://adb-SOURCE-WORKSPACE.azuredatabricks.net
  auth:
    type: PROFILE
    profile: source-workspace

target:
  host: https://adb-TARGET-WORKSPACE.azuredatabricks.net
  auth:
    type: PROFILE
    profile: target-workspace
```

Example secret-backed target authentication:

```yaml
target:
  host: https://adb-TARGET-WORKSPACE.azuredatabricks.net
  auth:
    type: TOKEN_SECRET
    secret_scope: dbxmigrator
    secret_key: target-workspace-token
```

Create the target secret in the source workspace before running the notebook:

```python
# Run once as an authorized administrator
dbutils.secrets.put(
    scope="dbxmigrator",
    key="target-workspace-token",
    string_value="<target-access-token>",
)
```

The notebook resolves that secret only when `TOKEN_SECRET` authentication is selected. The token is passed to the Databricks SDK and is not written to the migration plan.

Artifact type values include `NOTEBOOK`, `JOB`, `PIPELINE`, `CLUSTER`, `CLUSTER_POLICY`, `POOL`, `SQL_WAREHOUSE`, `QUERY`, `DASHBOARD`, `ALERT`, `MLFLOW`, `SERVING`, `SECRET_SCOPE`, `HIVE_TABLE`, `DBFS`, `VOLUME`, `CHECKPOINT`, `LEGACY_MOUNT`, and others defined by the core model.

## Separate migration dimensions

### Workspace artifacts

Workspace migration recreates source assets in the target workspace. It does not require the source data or its governance objects to be modernized simultaneously.

Examples:

- Notebooks and workspace files
- Git folders and repositories
- Jobs and pipelines
- Clusters and instance pools
- Cluster policies
- SQL warehouses, queries, dashboards, and alerts
- MLflow and serving resources
- Secret scopes and workspace configuration
- Permissions

### Data

Data migration moves or recreates physical data without automatically registering catalog objects.

Examples:

- Hive-managed data
- DBFS data
- External storage
- Volumes
- Streaming checkpoints
- Application state

### Governance

Governance migration is optional. `NONE` mode inventories legacy dependencies but does not create Unity Catalog catalogs, schemas, tables, credentials, locations, or grants.

## Unity Catalog modes

### NONE

Use `NONE` for the phase-one workspace and data migration.

It inventories Hive and storage dependencies, but creates no Unity Catalog objects.

```yaml
migration:
  workspace_artifacts: true
  data:
    enabled: true
  unity_catalog:
    mode: NONE
  dry_run: true
```

### ASSESS

`ASSESS` produces proposed mappings, external-table candidates, managed-table candidates, identities, permissions, storage dependencies, code changes, and blockers. It does not mutate Unity Catalog.

### Assessment-only inventory without a target

Use a configuration based on [`config/assessment-only.yaml`](../config/assessment-only.yaml) when cataloging the source before the target workspace is available.

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

# No target section is required.
```

Assessment-only discovery:

- Inventories every supported artifact in the source.
- Records workspace, data, and governance dependencies.
- Produces migration dispositions and a complete inventory ledger.
- Does not create a target SDK client.
- Does not copy or register data.
- Does not create or update Unity Catalog objects.
- Cannot execute migrations.

Execution remains blocked until a new non-assessment plan is approved with a configured target workspace.

### REGISTER

`REGISTER` is intended for registering existing external data without physically copying it. The plan must distinguish the data location from the catalog registration.

### MIGRATE

`MIGRATE` represents an approved Hive Metastore-to-Unity Catalog migration. The selected strategy may be external registration, clone, CTAS, storage copy and registration, synchronization, UCX, or manual transformation depending on the object.

## Notebook lifecycle

Use the notebook widgets for the complete lifecycle:

### 1. Dry run

Set:

- `config_path`
- `action=dry_run`
- Leave `migration_plan_id` empty

Run the notebook. Save the returned migration plan ID from the output or plan JSON.

Dry run performs discovery and planning only. It creates the plan record but must make no source or target mutations.

### 2. Review

Review:

- Discovered artifact counts
- Migration status by artifact
- Readiness status by artifact
- Migration disposition
- Dependencies and target resolutions
- Blockers and warnings
- UC assessment, if enabled

A typical report separates outcomes:

```text
Notebook migrated            YES
Job recreated                YES
Table dependency resolved    NO
Runtime readiness             BLOCKED
```

### 3. Approve

For approval, set:

- `action=approve`
- `migration_plan_id` to the reviewed plan ID
- `approved_by` to the approver identity

The approval action performs drift validation before changing the plan state to `APPROVED`.

An approver should verify:

- Scope
- Data behavior
- Unity Catalog mode
- Conflict strategy
- Identity mappings
- Secret replacements
- Storage and network dependencies
- Manual and unsupported artifacts

Changing the configuration does not silently amend an existing plan. Create a new plan for changed input.

### 4. Drift check

Before execution, optionally set:

- `action=drift_check`
- `migration_plan_id`

The result identifies:

- Unchanged artifacts
- Modified artifacts
- Missing artifacts
- Newly discovered artifacts

Execution should use only a plan with no unacceptable drift.

### 5. Execute

Execution requires a reviewed and approved plan and `migration.dry_run=false`.

Set:

- `action=execute`
- `migration_plan_id`

The engine:

1. Reloads the exact approved plan.
2. Rejects execution without approval.
3. Rejects execution while still in dry-run configuration.
4. Executes artifacts in dependency order where dependencies can be resolved.
5. Records an event for each artifact.
6. Separately validates migration completeness and runtime readiness.

Execution is currently expected to be an incremental implementation area. Unsupported or unimplemented handlers are recorded and do not silently disappear.

### 6. Report

Set:

- `action=report`
- `migration_plan_id`

The report displays migration and readiness results from the durable plan.

## Artifact and readiness states

### Migration completeness

Migration completeness answers: “Did the accelerator recreate or move the Databricks artifact?”

Examples:

- Notebook migrated
- Job recreated
- SQL warehouse recreated
- Cluster policy recreated
- Dashboard recreated

### Runtime readiness

Runtime readiness answers: “Can the recreated workload execute?”

Examples:

- Storage dependency resolved
- Hive or UC table dependency resolved
- Secret scope replaced
- Target identity resolved
- Cluster policy compatible
- Network configuration available

An artifact may report `MIGRATED` and still have `BLOCKED` runtime readiness.

## Dispositions

The migration ledger can assign one of the following dispositions:

| Disposition | Meaning |
|---|---|
| `MIGRATE_AUTOMATICALLY` | An implementation is available |
| `MIGRATE_WITH_TRANSFORMATION` | Migration requires an approved transformation |
| `MIGRATE_DATA_ONLY` | Only physical data should be migrated |
| `REGISTER_UC` | Existing external data should be catalog-registered |
| `SKIP_BY_POLICY` | Configuration or policy deliberately excludes the artifact |
| `BLOCKED_DEPENDENCY` | An unresolved dependency prevents migration |
| `MANUAL_REQUIRED` | Human action is required |
| `UNSUPPORTED` | No safe automatic migration provider exists |

## Dependency rules

Notebook migration must not be blocked by a table dependency that is independent of the notebook export/import operation. The dependency is recorded and runtime readiness is evaluated separately.

Example:

```text
Notebook /Shared/ETL/customer_processing
Migration status: MIGRATED
Dependency: raw.customer
Target resolution: UNRESOLVED
Workspace migration: CAN PROCEED
Runtime readiness: BLOCKED
```

## Plan storage

Plans contain artifact definitions, hashes, dependencies, dispositions, blockers, readiness, approval metadata, and lifecycle state.

For disaster recovery:

1. Export `/dbfs/migration-plans/<migration_plan_id>/migration_plan.json`.
2. Retain the matching `events.jsonl`.
3. Record approval outside the plan system according to change-control requirements.
4. Do not execute a plan if plan and event files are missing, inconsistent, or inaccessible.

## Target conflict behavior

The current `FAIL` behavior is appropriate for production migrations. It should prevent an artifact from silently overwriting an existing target artifact.

Before execution:

- Check target object names and IDs.
- Define identity mappings.
- Define secret scope names.
- Define catalog and schema mappings.
- Confirm storage paths and credentials.
- Confirm cluster and network compatibility.
- Confirm permissions and group mappings.

## Validation

After migration:

1. Verify artifact counts and statuses.
2. Verify each non-migrated artifact has `SKIPPED`, `BLOCKED`, `UNSUPPORTED`, or `MANUAL_REQUIRED`.
3. Compare source and target definitions.
4. Run non-destructive smoke workloads first.
5. Resolve external tables, mounts, secret scopes, identities, and storage paths.
6. Validate dashboard data sources and warehouse permissions.
7. Validate job schedule, retry, notification, cluster, and notebook settings.
8. Validate data row counts, checksums, schemas, and checkpoints.
9. Recalculate runtime readiness.
10. Perform final sync and cutover only after human review.

## Common scenarios

### Migrate workspace and data only; leave UC unchanged

```yaml
migration:
  workspace_artifacts: true
  data:
    enabled: true
  unity_catalog:
    mode: NONE
  dry_run: true
```

### Assess UC without changing UC

```yaml
migration:
  workspace_artifacts: false
  data:
    enabled: false
  unity_catalog:
    mode: ASSESS
  dry_run: true
```

### Select only notebooks and jobs

```yaml
migration:
  workspace_artifacts: true
  data:
    enabled: false
  unity_catalog:
    mode: NONE
  dry_run: true
  include_artifact_types:
    - NOTEBOOK
    - JOB
```

### Phase-one migration followed by later UC modernization

1. Run a workspace and data plan with UC mode `NONE`.
2. Validate migrated artifacts and legacy-compatible workloads.
3. Run a separate UC plan with `ASSESS`.
4. Approve selected table and identity transformations.
5. Run `REGISTER` or `MIGRATE` for the selected subset.

## Troubleshooting

### PyYAML is not installed

Install it through `%pip install PyYAML`, or use a JSON configuration.

### Databricks SDK is not installed

Install the optional dependencies:

```python
%pip install "databricks-sdk>=0.30.0"
```

### The notebook has no migration_plan_id

Run `action=dry_run` first. Create a new plan for each discovery version.

### Approval reports drift

Review the modified, missing, and new artifact lists. Create a new plan only if source contents changed or migration scope changed.

### Execution is rejected

Verify all four conditions:

1. The plan state is `APPROVED`.
2. Configuration is not dry-run.
3. The plan ID is correct.
4. The approver intentionally approved source drift resolution.

### An artifact remains blocked

Review its blocker list. Typical blockers are unresolved tables, missing target identities, inaccessible storage, unavailable secrets, mounts without target credentials, and unsupported code.

## License

This project is licensed under the MIT License. See the repository [`LICENSE`](../LICENSE) file.
