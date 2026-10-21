from dbxmigrator.handlers import _call_sdk_list, _sdk_items


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
