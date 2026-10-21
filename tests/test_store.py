from dbxmigrator.store import MigrationStore
from pathlib import Path


def test_store_normalizes_dbfs_root_to_workspace(tmp_path):
    normalized = MigrationStore.normalize_root("/dbfs/migration-plans")

    assert normalized == Path(
        "/Workspace/Shared/dbxmigrator/migration-plans"
    )


def test_store_creates_plan_and_event_in_writable_root(tmp_path):
    store = MigrationStore(tmp_path)
    plan = store.create_plan({"migration": {"dry_run": True}})

    assert store.plan_path(plan.migration_plan_id).exists()


def test_store_never_returns_dbfs_root(tmp_path):
    store = MigrationStore("/dbfs/migration-plans")

    assert not str(store.root).startswith("/dbfs/")
    assert store.root.is_dir()
