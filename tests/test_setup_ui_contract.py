"""Source contracts for password-first setup UI."""

from html.parser import HTMLParser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.attributes_by_id: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        identifier = attributes.get("id")
        if identifier:
            self.ids.append(identifier)
            self.attributes_by_id[identifier] = attributes


class SetupUIContractTests(unittest.TestCase):
    def test_password_step_is_accessible_and_password_manager_compatible(self) -> None:
        parser = IdCollector()
        parser.feed((ROOT / "setup/index.html").read_text(encoding="utf-8"))
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertTrue(
            {
                "step-password",
                "password-form",
                "linux-password",
                "linux-password-confirmation",
                "password-error",
                "btn-password-save",
                "btn-change-password",
            }.issubset(parser.ids)
        )
        for identifier in ("linux-password", "linux-password-confirmation"):
            attributes = parser.attributes_by_id[identifier]
            self.assertEqual("password", attributes.get("type"))
            self.assertEqual("new-password", attributes.get("autocomplete"))
            self.assertIn("required", attributes)
        self.assertEqual("alert", parser.attributes_by_id["password-error"].get("role"))

    def test_client_posts_only_password_and_confirmation_then_clears_fields(self) -> None:
        source = (ROOT / "setup/app.js").read_text(encoding="utf-8")
        self.assertIn("api('api/password'", source)
        self.assertIn("JSON.stringify({ password, confirmation })", source)
        self.assertIn("passwordInput.value = '';", source)
        self.assertIn("confirmationInput.value = '';", source)
        self.assertIn("if (!data.authentication.password_configured) openPasswordStep(true)", source)
        self.assertNotIn("localStorage", source)
        self.assertNotIn("current_password", source)

    def test_hidden_state_wins_over_component_display_rules(self) -> None:
        stylesheet = (ROOT / "setup/style.css").read_text(encoding="utf-8")
        self.assertIn("[hidden] { display: none !important; }", stylesheet)


if __name__ == "__main__":
    unittest.main()
