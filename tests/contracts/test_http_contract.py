"""Public contract regression tests; these do not claim a running server."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[2]
API = json.loads((ROOT / "api/http/openapi.json").read_text())


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(dict(API, **{"$ref": f"#/components/schemas/{name}"}))


def read_context() -> dict:
    return {"read_consistency": "published", "data_revision_id": "revision-a",
            "read_view_id": "view-a", "source_versions": [
                {"source_id": "assets", "format": "parquet-manifest", "version": "manifest-a"}],
            "index_versions": []}


def data_page() -> dict:
    return {"query_id": "q", "result_kind": "data", "columns": [], "rows": [],
            "next_cursor": None, "truncated": False, "read_context": read_context()}


class HttpContractTests(unittest.TestCase):
    def test_standard_and_example(self):
        validate(API)
        example = json.loads((ROOT / "examples/http/query.json").read_text())
        validator("QueryRequest").validate(example)
        embedded = API["paths"]["/v1/queries"]["post"]["requestBody"]["content"]["application/json"]["example"]
        self.assertEqual(embedded, example)

    def test_explicit_view_and_latest_are_mutually_exclusive(self):
        value = {"sql": "SELECT 1", "read_view_id": "view-a", "read_consistency": "data_committed"}
        self.assertFalse(validator("QueryRequest").is_valid(value))
        value["read_consistency"] = "published"
        validator("QueryRequest").validate(value)

    def test_query_endpoint_accepts_only_read_only_mode(self):
        validator("QueryRequest").validate({"sql": "SELECT 1", "mode": "read_only"})
        # Classifying SQL side effects is a planner duty, not JSON validation.
        for controls in ({}, {"read_view_id": "view-a"}, {"read_consistency": "published"}):
            with self.subTest(controls=controls):
                request = {"sql": "INSERT INTO t SELECT 1", "mode": "read_write", **controls}
                self.assertFalse(validator("QueryRequest").is_valid(request))

    def test_unknown_fields_invalid_budgets_and_client_result_kind_are_rejected(self):
        for extra in ({"tenant_id": "other-tenant"}, {"timeout_ms": 0}, {"max_rows": -1},
                      {"result_kind": "metadata"}):
            with self.subTest(extra=extra):
                self.assertFalse(validator("QueryRequest").is_valid({"sql": "SELECT 1", **extra}))

    def test_query_handles_do_not_advertise_write_outcomes(self):
        for extra in ({"write_outcome": "committed"}, {"affected_rows": "10"},
                      {"data_revision_id": "revision-a"}, {"search_ready": False}):
            with self.subTest(extra=extra):
                value = {"query_id": "q", "status": "succeeded", "result_kind": "metadata", **extra}
                self.assertFalse(validator("QueryHandle").is_valid(value))

    def test_successful_data_handle_requires_classification_and_context(self):
        value = {"query_id": "q", "status": "succeeded"}
        self.assertFalse(validator("QueryHandle").is_valid(value))
        value["result_kind"] = "data"
        self.assertFalse(validator("QueryHandle").is_valid(value))
        value["read_context"] = read_context()
        validator("QueryHandle").validate(value)
        # Before source binding, a queued handle has no fabricated revision.
        validator("QueryHandle").validate({"query_id": "q", "status": "queued"})

    def test_data_pages_require_context_even_for_empty_results(self):
        page = data_page()
        validator("ResultPage").validate(page)
        del page["read_context"]
        self.assertFalse(validator("ResultPage").is_valid(page))
        page["read_context"] = {}
        self.assertFalse(validator("ResultPage").is_valid(page))

    def test_read_context_cannot_omit_revision_or_actual_sources(self):
        context = read_context()
        for field in ("read_consistency", "data_revision_id", "read_view_id", "source_versions", "index_versions"):
            with self.subTest(field=field):
                value = deepcopy(context)
                del value[field]
                self.assertFalse(validator("ReadContext").is_valid(value))
        for extra in ({"data_revision_id": ""}, {"read_view_id": ""}, {"source_versions": []},
                      {"source_versions": [{"source_id": "assets", "format": "parquet", "version": ""}]}):
            with self.subTest(extra=extra):
                self.assertFalse(validator("ReadContext").is_valid({**context, **extra}))

    def test_future_committed_context_still_requires_revision_and_sources(self):
        context = read_context()
        context["read_consistency"] = "data_committed"
        del context["read_view_id"]
        validator("ReadContext").validate(context)
        del context["data_revision_id"]
        self.assertFalse(validator("ReadContext").is_valid(context))

    def test_metadata_results_are_explicit_and_do_not_fake_a_data_context(self):
        handle = {"query_id": "q", "status": "succeeded", "result_kind": "metadata"}
        validator("QueryHandle").validate(handle)
        self.assertFalse(validator("QueryHandle").is_valid({**handle, "read_context": read_context()}))
        page = data_page()
        page["result_kind"] = "metadata"
        self.assertFalse(validator("ResultPage").is_valid(page))
        del page["read_context"]
        validator("ResultPage").validate(page)
        del page["result_kind"]
        self.assertFalse(validator("ResultPage").is_valid(page))

    def test_cancellation_terminal_states_remain_in_query_contract(self):
        for status in ("cancel_requested", "cancelled"):
            with self.subTest(status=status):
                validator("QueryHandle").validate({"query_id": "q", "status": status})
        operation = API["paths"]["/v1/queries/{query_id}"]["delete"]
        self.assertIn("200", operation["responses"])
        self.assertIn("202", operation["responses"])
        # Runtime tests must additionally prove terminal status never regresses.

    def test_failure_needs_structured_error(self):
        value = {"query_id": "q", "status": "failed"}
        self.assertFalse(validator("QueryHandle").is_valid(value))
        value["error"] = {"code": "SOURCE_EXPIRED", "message": "snapshot expired",
                          "retryable": False, "request_id": "r"}
        validator("QueryHandle").validate(value)

    def test_pagination_cannot_hide_truncation_or_use_an_empty_cursor(self):
        page = data_page()
        page["truncated"] = True
        validator("ResultPage").validate(page)
        page["next_cursor"] = ""
        self.assertFalse(validator("ResultPage").is_valid(page))
        page["next_cursor"] = "opaque-next-page"
        validator("ResultPage").validate(page)
        del page["truncated"]
        self.assertFalse(validator("ResultPage").is_valid(page))


if __name__ == "__main__":
    unittest.main()
