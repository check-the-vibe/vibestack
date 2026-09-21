"""Coverage checks for the audited source contract, not runtime availability."""
import ast
import json
import operator
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CapabilityInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads((ROOT / "contracts/capability-inventory-v1.json").read_text())
        cls.operations = cls.inventory["operations"]

    def test_every_published_operation_matches_its_route_and_cli(self):
        actual = {op["id"]: op for op in self.operations if "published_schema" in op}
        expected = {}
        coverage = json.loads((ROOT / "api/command-coverage.json").read_text())
        for name in ("workspace", "runner"):
            filename = f"api/{name}.openapi.json"
            document = json.loads((ROOT / filename).read_text())
            for path, methods in document["paths"].items():
                for method, operation in methods.items():
                    if method not in {"get", "head", "post", "put", "patch", "delete", "options"}:
                        continue
                    oid = operation["operationId"]
                    self.assertNotIn(oid, expected)
                    expected[oid] = (filename, method.upper() + " " + path)
        self.assertEqual(set(expected), set(actual))
        for oid, (filename, route) in expected.items():
            self.assertEqual(actual[oid]["published_schema"], filename, oid)
            self.assertEqual(actual[oid]["current"]["rest"]["entry"], route, oid)
            self.assertEqual(actual[oid]["current"]["cli"]["entry"], "vibestack " + coverage[oid], oid)

    def test_setup_routes_missing_from_openapi_are_still_audited(self):
        # Setup's fixed/regex API literals are not in OpenAPI. Discover these
        # independently so adding a handler requires an inventory decision.
        tree = ast.parse((ROOT / "setup/server.py").read_text())
        patterns = set()
        for node in ast.walk(tree):
            route_expression = None
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "path":
                route_expression = node
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "fullmatch" and len(node.args) == 2
                  and isinstance(node.args[1], ast.Name) and node.args[1].id == "path"):
                route_expression = node.args[0]
            if route_expression:
                patterns.update(item.value for item in ast.walk(route_expression)
                                if isinstance(item, ast.Constant) and isinstance(item.value, str)
                                and item.value.startswith("/api/"))
        routes = []
        for operation in self.operations:
            if operation["source"] != "setup/server.py" or "published_schema" in operation:
                continue
            route = operation["current"]["rest"]["entry"].split(" ", 1)[1]
            route = route.removeprefix("/setup").replace("{code}", "ABCD-EFGH").replace("{id}", "a" * 32)
            routes.append(route)
        self.assertTrue(patterns)
        for pattern in patterns:
            self.assertTrue(any(re.fullmatch(pattern, route) for route in routes), pattern)
        for route in routes:
            self.assertTrue(any(re.fullmatch(pattern, route) for pattern in patterns), route)

    def test_authority_surface_exceptions_and_evidence_are_explicit(self):
        seen = set()
        for operation in self.operations:
            oid = operation["id"]
            self.assertNotIn(oid, seen)
            seen.add(oid)
            self.assertIn(operation["authority"], {"workspace", "host"}, oid)
            self.assertIn(operation["limit_profile"], self.inventory["limit_profiles"], oid)
            self.assertEqual(set(operation["current"]), {"rest", "cli", "mcp", "web"}, oid)
            self.assertEqual(set(operation["target"]), {"rest", "cli", "mcp", "web"}, oid)
            self.assertTrue((ROOT / operation["source"]).is_file(), oid)
            self.assertTrue(operation["verification"], oid)
            for evidence in operation["verification"]:
                self.assertTrue((ROOT / evidence).is_file(), (oid, evidence))
            for surface in operation["current"].values():
                self.assertIn(surface["state"], self.inventory["surface_states"], oid)
                self.assertTrue(surface["reason"], oid)
                self.assertTrue(surface["next_action"], oid)
                if surface["state"] == "implemented":
                    self.assertTrue(surface["entry"], oid)
            if operation["authority"] == "host":
                self.assertEqual(operation["kind"], "compatibility-only", oid)
            if operation["retry"] == "safe-read":
                self.assertEqual(operation["effect"], "read", oid)

    def test_documented_limits_match_source_constants(self):
        # Read literal arithmetic without importing servers or evaluating code.
        arithmetic = {ast.Add: operator.add, ast.Mult: operator.mul, ast.LShift: operator.lshift}

        def number(node):
            if isinstance(node, ast.Constant) and type(node.value) is int:
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in arithmetic:
                return arithmetic[type(node.op)](number(node.left), number(node.right))
            raise ValueError("limit needs a reviewed constant expression")

        mappings = {
            "automation/automationlib.py": {
                "MAX_JSON_BODY_BYTES": ("automation", "json_body_bytes"),
                "MAX_TOOL_OUTPUT_BYTES": ("automation", "tool_output_bytes"),
                "MAX_COMMAND_ARGS": ("command", "argv_entries"),
                "MAX_ARGUMENT_BYTES": ("command", "argument_total_bytes"),
                "MAX_SHELL_BYTES": ("command", "shell_bytes"),
                "MAX_ENVIRONMENT_ENTRIES": ("command", "environment_entries"),
                "MAX_ENVIRONMENT_BYTES": ("command", "environment_bytes"),
            },
            "automation/runner.py": {
                "WORKER_COUNT": ("command", "worker_count"),
                "QUEUE_CAPACITY": ("command", "queue_capacity"),
                "DEFAULT_TIMEOUT_SECONDS": ("command", "timeout_seconds_default"),
                "MAX_TIMEOUT_SECONDS": ("command", "timeout_seconds_max"),
                "MAX_OUTPUT_BYTES": ("command", "output_per_stream_bytes"),
                "MAX_OUTPUT_PAGE_BYTES": ("job-output", "page_bytes"),
            },
            "automation/files.py": {
                "MAX_FILE_BYTES": ("file", "raw_file_bytes"),
                "MAX_RANGE_BYTES": ("file", "range_bytes"),
            },
            "setup/server.py": {
                "MAX_REQUEST_BODY_BYTES": ("setup", "json_body_bytes"),
                "MAX_LOG_PAGE_BYTES": ("setup", "log_page_bytes"),
                "MAX_COMPONENTS": ("setup", "components"),
            },
            "control/server.py": {"MAX_BODY_BYTES": ("control", "json_body_bytes")},
        }
        for filename, bindings in mappings.items():
            constants = {}
            for node in ast.parse((ROOT / filename).read_text()).body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id in bindings:
                            constants[target.id] = number(node.value)
            self.assertEqual(set(bindings), set(constants), filename)
            for name, (profile, key) in bindings.items():
                self.assertEqual(constants[name], self.inventory["limit_profiles"][profile][key], name)


if __name__ == "__main__":
    unittest.main()
