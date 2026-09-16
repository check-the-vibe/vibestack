import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class APICommandCoverageTests(unittest.TestCase):
    def test_every_published_operation_has_a_cli_route(self):
        coverage = json.loads((ROOT / "api/command-coverage.json").read_text())
        operation_ids = set()
        for name in ("workspace.openapi.json", "runner.openapi.json"):
            document = json.loads((ROOT / "api" / name).read_text())
            for path in document["paths"].values():
                for operation in path.values():
                    operation_ids.add(operation["operationId"])
        self.assertEqual(operation_ids, set(coverage))

    def test_coverage_names_commands_documented_by_the_cli(self):
        coverage = json.loads((ROOT / "api/command-coverage.json").read_text())
        reference = (ROOT / "docs/CLI.md").read_text()
        for operation, command in coverage.items():
            command_group = command.split()[0]
            self.assertIn(command_group, reference, operation)


if __name__ == "__main__":
    unittest.main()
