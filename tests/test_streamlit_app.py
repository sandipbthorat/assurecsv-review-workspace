import os
from pathlib import Path
import tempfile
import unittest

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


class StreamlitAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data_directory = tempfile.TemporaryDirectory()
        os.environ["CSVQUALREVIEWER_DATA_DIR"] = self.data_directory.name
        os.environ["CSVQUALREVIEWER_DEMO_ADMIN_ROLES"] = "true"
        os.environ["CSVQUALREVIEWER_MODE"] = "demo"

    def tearDown(self) -> None:
        for key in (
            "CSVQUALREVIEWER_DATA_DIR",
            "CSVQUALREVIEWER_DEMO_ADMIN_ROLES",
            "CSVQUALREVIEWER_MODE",
        ):
            os.environ.pop(key, None)
        self.data_directory.cleanup()

    def test_demo_roles_control_admin_navigation(self) -> None:
        expectations = {
            "Reviewer": [],
            "Review Administrator": ["⚙   Review Administrator"],
            "Platform Administrator": ["⚙   Review Administrator", "⚙   Platform Administrator"],
        }
        for role, expected in expectations.items():
            with self.subTest(role=role):
                app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
                next(select for select in app.selectbox if select.label == "Demo role").set_value(role)
                next(button for button in app.button if button.label == "Enter demo workspace").click().run()
                admin_buttons = [button.label for button in app.button if "Administrator" in button.label]
                self.assertEqual(expected, admin_buttons)
                self.assertFalse(app.exception)

    def test_login_navigation_and_sample_review(self) -> None:
        app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30)
        app.run()

        self.assertFalse(app.exception)
        self.assertTrue(
            any("Sign in to review with confidence" in markdown.value for markdown in app.markdown)
        )
        self.assertIn("Enterprise SSO not configured", [button.label for button in app.button])

        next(button for button in app.button if button.label == "Enter demo workspace").click().run()
        self.assertFalse(app.exception)
        self.assertIn("Welcome back, Demo 👋", [title.value for title in app.title])
        self.assertNotIn("⚙   Review Administrator", [button.label for button in app.button])
        self.assertNotIn("⚙   Platform Administrator", [button.label for button in app.button])

        next(button for button in app.button if button.label == "↶   Run History").click().run()
        self.assertFalse(app.exception)
        self.assertIn("Run History", [title.value for title in app.title])

        next(button for button in app.button if button.label == "▱   All References").click().run()
        self.assertFalse(app.exception)
        self.assertIn("All References", [title.value for title in app.title])

        next(button for button in app.button if button.label == "⌂   Home").click().run()
        next(button for button in app.button if button.label == "Use realistic sample package").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any("Executive Summary" in markdown.value for markdown in app.markdown))

        next(button for button in app.button if button.label == "◷   Findings").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any("Findings" in markdown.value for markdown in app.markdown))
        self.assertIn("Clear filters", [button.label for button in app.button])
        safe_action = next(select for select in app.selectbox if select.label == "Safe bulk action")
        self.assertEqual(["Select an action", "Deferred", "Needs SME Review"], safe_action.options)

        next(button for button in app.button if button.label == "Sign out").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Sign in to review with confidence" in markdown.value for markdown in app.markdown))

    def test_document_generation_and_review_agent_handoff(self) -> None:
        app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
        next(button for button in app.button if button.label == "Enter demo workspace").click().run()
        next(button for button in app.button if button.label == "✦   Document Generation").click().run()

        self.assertFalse(app.exception)
        self.assertIn("Document Generation", [title.value for title in app.title])
        next(button for button in app.button if button.label == "Use controlled demo sources").click().run()

        self.assertFalse(app.exception)
        self.assertIn("Download controlled Word draft", [button.label for button in app.get("download_button")])
        self.assertTrue(any(metric.label == "Sections reviewed" for metric in app.metric))
        next(button for button in app.button if button.label == "Mark human reviewed").click().run()
        self.assertFalse(app.exception)
        next(button for button in app.button if button.label == "Send draft to Review Agent").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any("Executive Summary" in markdown.value for markdown in app.markdown))

    def test_platform_settings_and_sign_out_clear_session_identity(self) -> None:
        app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
        next(select for select in app.selectbox if select.label == "Demo role").set_value("Platform Administrator")
        next(button for button in app.button if button.label == "Enter demo workspace").click().run()
        next(button for button in app.button if button.label == "⚙   Platform Administrator").click().run()
        next(button for button in app.button if button.label == "Save demo settings").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["platform_settings_data"]["retention"], "7 years")

        app.session_state["reviewer_name"] = "Prior User"
        next(button for button in app.button if button.label == "Sign out").click().run()
        self.assertFalse(app.exception)
        self.assertNotIn("reviewer_name", app.session_state)

    def test_summary_metrics_and_review_restore_are_complete(self) -> None:
        app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
        next(button for button in app.button if button.label == "Enter demo workspace").click().run()
        next(button for button in app.button if button.label == "Use realistic sample package").click().run(timeout=30)
        labels = {metric.label for metric in app.metric}
        self.assertTrue(
            {
                "Documents", "Total findings", "Critical", "Major", "Minor", "Observations",
                "Open actions", "Accepted", "Rejected", "Needs SME", "Overall status",
            }.issubset(labels)
        )
        next(button for button in app.button if button.label == "Sign out").click().run()

        restored = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
        next(button for button in restored.button if button.label == "Enter demo workspace").click().run()
        self.assertTrue(any("NovaQMS 2.4 validation package" in markdown.value for markdown in restored.markdown))
        self.assertFalse(restored.exception)

    def test_unsaved_decision_blocks_navigation_until_discarded(self) -> None:
        app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
        next(button for button in app.button if button.label == "Enter demo workspace").click().run()
        next(button for button in app.button if button.label == "Use realistic sample package").click().run(timeout=30)
        next(button for button in app.button if button.label == "◷   Findings").click().run(timeout=30)
        next(select for select in app.selectbox if select.label == "Disposition").set_value("Deferred").run()
        next(button for button in app.button if button.label == "⌂   Home").click().run()
        self.assertTrue(any("unsaved reviewer decision" in warning.value.lower() for warning in app.warning))
        self.assertTrue(any("Findings" in markdown.value for markdown in app.markdown))
        next(button for button in app.button if button.label == "Discard").click().run()
        self.assertIn("Welcome back, Demo 👋", [title.value for title in app.title])
        self.assertFalse(app.exception)

    def test_production_mode_fails_closed_without_oidc(self) -> None:
        os.environ["CSVQUALREVIEWER_MODE"] = "production"
        app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
        self.assertNotIn("Enter demo workspace", [button.label for button in app.button])
        self.assertTrue(any("Production mode requires configured OIDC" in error.value for error in app.error))
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
