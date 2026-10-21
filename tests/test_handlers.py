from dbxmigrator.handlers import (
    _call_sdk_list,
    _decode_exported_source,
    _encode_source_content,
    _sdk_items,
    default_registry,
)
from dbxmigrator.models import ArtifactType


class ListQueriesResponse:
    def __init__(self):
        self.queries = [
            {"id": "query-1", "display_name": "Revenue query"}
        ]


class ItemsResponse:
    def __init__(self):
        self.items = [
            {"id": "item-1", "name": "test item"}
        ]


class QueriesService:
    def list(self):
        return ListQueriesResponse()


def test_sdk_items_handles_non_iterable_response_wrapper():
    response = ListQueriesResponse()

    items = _sdk_items(response, "queries")

    assert items == [{"id": "query-1", "display_name": "Revenue query"}]


def test_sdk_items_handles_generic_items_response():
    assert _sdk_items(ItemsResponse(), "unknown") == [
        {"id": "item-1", "name": "test item"}
    ]


def test_generic_sdk_list_handles_list_response_wrapper():
    items = _call_sdk_list(QueriesService(), "queries")

    assert items == [{"id": "query-1", "display_name": "Revenue query"}]


def test_notebook_source_content_round_trips_through_base64():
    source = "print('migration')\n"

    encoded = _encode_source_content(source)
    decoded = _decode_exported_source(encoded)

    assert decoded == source


def test_notebook_source_content_accepts_plain_text_fallback():
    assert _decode_exported_source("print('migration')") == "print('migration')"


def test_schema_discovery_lists_each_catalog_schema():
    calls = []

    class SchemasService:
        def list(self, catalog_name):
            calls.append(catalog_name)
            return [{"name": f"{catalog_name}.default", "catalog_name": catalog_name}]

    class CatalogsService:
        def list(self):
            return [{"name": "main"}, {"name": "analytics"}]

    class Context:
        catalogs = CatalogsService()
        schemas = SchemasService()

    registry = default_registry()
    handler = registry.get(ArtifactType.SCHEMA)
    artifacts = list(handler.discover(Context()))

    assert calls == ["main", "analytics"]
    assert len(artifacts) == 2
