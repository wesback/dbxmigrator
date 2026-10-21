# Databricks notebook source
# Widgets:
#   config_path: DBFS or Workspace file containing migration YAML/JSON
#   action: dry_run, approve, drift_check, execute, report

import json
from pathlib import Path
import importlib
import subprocess
import sys

try:
    import yaml
except ImportError:
    yaml = None


dbutils.widgets.text("config_path", "/Workspace/Shared/dbxmigrator/config.yaml")
dbutils.widgets.dropdown(
    "action",
    "dry_run",
    ["dry_run", "approve", "drift_check", "execute", "report"],
)
dbutils.widgets.text("migration_plan_id", "")
dbutils.widgets.text("approved_by", "")
dbutils.widgets.text(
    "package_source",
    "git+https://github.com/wesback/dbxmigrator.git@main",
)

config_path = dbutils.widgets.get("config_path")
action = dbutils.widgets.get("action")
plan_id = dbutils.widgets.get("migration_plan_id")
approved_by = dbutils.widgets.get("approved_by")
package_source = dbutils.widgets.get("package_source")


def ensure_dbxmigrator(package_source):
    try:
        return importlib.import_module("dbxmigrator")
    except ModuleNotFoundError as import_error:
        if import_error.name != "dbxmigrator":
            raise

        subprocess.check_call([
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--upgrade",
            "dbxmigrator[databricks] @ "
            + package_source,
        ])
        importlib.invalidate_caches()
        try:
            return importlib.import_module("dbxmigrator")
        except ModuleNotFoundError as retry_error:
            raise RuntimeError(
                "dbxmigrator still could not be imported after package installation. "
                "Detach and reattach the notebook cluster, then rerun the notebook."
            ) from retry_error


accelerator = ensure_dbxmigrator(package_source)

from dbxmigrator.config import MigrationConfig
from dbxmigrator.engine import MigrationEngine
from dbxmigrator.handlers import default_registry
from dbxmigrator.report import render_summary_table
from dbxmigrator.store import MigrationStore
from dbxmigrator.auth import build_workspace_client


def load_config(path):
    if path.startswith("dbfs:/"):
        local_path = "/dbfs/" + path.removeprefix("dbfs:/")
        path = local_path
    elif path.startswith("workspace:/"):
        path = "/Workspace/" + path.removeprefix("workspace:/")

    source = Path(path)
    if source.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML is required for YAML configuration")
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    else:
        payload = json.loads(source.read_text(encoding="utf-8"))
    return MigrationConfig.from_dict(payload)


class DatabricksContext:
    """Source and target SDK context for notebook execution."""

    def __init__(self, source_client, target_client=None):
        self.source_client = source_client
        self.target_client = target_client
        self.inventory = {}


try:
    from databricks.sdk import WorkspaceClient
except ImportError:
    WorkspaceClient = None


config = load_config(config_path)
store_root = config.storage.get(
    "plan_store",
    "/Workspace/Shared/dbxmigrator/plans",
)
store = MigrationStore(store_root)
engine = MigrationEngine(default_registry(), store)

secret_resolver = lambda scope, key: dbutils.secrets.get(scope, key)
source_client = build_workspace_client(
    config.source_workspace,
    secret_resolver=secret_resolver,
    workspace_client_class=WorkspaceClient,
) if WorkspaceClient else None
target_client = (
    build_workspace_client(
        config.target_workspace,
        secret_resolver=secret_resolver,
        workspace_client_class=WorkspaceClient,
    )
    if WorkspaceClient and config.target_workspace
    else None
)

context = DatabricksContext(source_client, target_client)

if action == "dry_run":
    plan = engine.create_dry_run(context, config.to_dict())
    report = engine.report(plan.migration_plan_id)
    print(render_summary_table(report))
elif action == "approve":
    if not plan_id:
        raise ValueError("migration_plan_id is required for approval")
    plan = engine.approve_plan(
        plan_id,
        approved_by or dbutils.notebook.entry_point.getDbutils().notebook.getContext().tags().apply("user"),
        drift_check=True,
        context=context,
    )
    print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
elif action == "drift_check":
    if not plan_id:
        raise ValueError("migration_plan_id is required for drift_check")
    print(json.dumps(engine.drift_check(plan_id, context), indent=2, sort_keys=True))
elif action == "execute":
    if not plan_id:
        raise ValueError("migration_plan_id is required for execute")
    plan = engine.execute(plan_id, context)
    print(json.dumps(engine.report(plan.migration_plan_id), indent=2, sort_keys=True))
elif action == "report":
    if not plan_id:
        raise ValueError("migration_plan_id is required for report")
    print(render_summary_table(engine.report(plan_id)))
