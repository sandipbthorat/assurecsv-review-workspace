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
        next(button for button in app.button if button.label == "Discard and continue").click().run()
        self.assertIn("Welcome back, Demo 👋", [title.value for title in app.title])
        self.assertFalse(app.exception)

    def test_every_reviewer_page_is_reachable_from_always_visible_navigation(self) -> None:
        app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
        next(button for button in app.button if button.label == "Enter demo workspace").click().run()
        next(button for button in app.button if button.label == "Use realistic sample package").click().run(timeout=30)
        expected_pages = {
            "Home": "Welcome back, Demo",
            "My Reviews": "My Reviews",
            "All Documents": "All Documents",
            "Upload": "Turn a validation package into a defensible decision record",
            "Document Generation": "Document Generation",
            "Chat": "Chat with CSVQualReviewer",
            "Run History": "Run History",
            "Feedback & Analytics": "Feedback & Analytics",
            "All References": "All References",
            "Templates": "Templates",
            "SOPs": "SOPs",
            "Golden Reports": "Golden Reports",
            "Guidance Documents": "Guidance Documents",
            "Executive Summary": "Executive Summary",
            "Findings": "Findings",
            "Documents": "Documents",
            "Traceability": "Traceability",
            "Redlines": "Redlines",
            "Review Decisions": "Review Decisions",
        }
        route_slugs = {
            "Home": "home", "My Reviews": "my-reviews", "All Documents": "all-documents",
            "Upload": "upload", "Document Generation": "document-generation", "Chat": "chat",
            "Run History": "run-history", "Feedback & Analytics": "analytics",
            "All References": "references", "Templates": "templates", "SOPs": "sops",
            "Golden Reports": "golden-reports", "Guidance Documents": "guidance",
            "Executive Summary": "executive-summary", "Findings": "findings",
            "Documents": "review-documents", "Traceability": "traceability", "Redlines": "redlines",
            "Review Decisions": "review-decisions",
        }
        route_picker = next(select for select in app.selectbox if select.label == "Page navigation")
        self.assertEqual(list(expected_pages), route_picker.options)
        for page, expected_text in expected_pages.items():
            with self.subTest(page=page):
                next(select for select in app.selectbox if select.label == "Page navigation").set_value(page).run(timeout=30)
                rendered_text = "\n".join(
                    [title.value for title in app.title]
                    + [markdown.value for markdown in app.markdown]
                    + [heading.value for heading in app.subheader]
                )
                self.assertIn(expected_text, rendered_text)
                self.assertEqual([route_slugs[page]], app.query_params["page"])
                self.assertFalse(app.exception)

    def test_internal_and_browser_history_navigation_stay_synchronized(self) -> None:
        app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
        next(button for button in app.button if button.label == "Enter demo workspace").click().run()
        next(select for select in app.selectbox if select.label == "Page navigation").set_value("Upload").run()
        next(select for select in app.selectbox if select.label == "Page navigation").set_value("Run History").run()

        next(button for button in app.button if button.label == "← Back").click().run()
        self.assertTrue(any("Turn a validation package" in title.value for title in app.title))
        next(button for button in app.button if button.label == "← Back").click().run()
        self.assertIn("Welcome back, Demo 👋", [title.value for title in app.title])
        next(button for button in app.button if button.label == "Forward →").click().run()
        self.assertTrue(any("Turn a validation package" in title.value for title in app.title))

        app.query_params["page"] = "home"
        app.run()
        self.assertIn("Welcome back, Demo 👋", [title.value for title in app.title])
        app.query_params["page"] = "upload"
        app.run()
        self.assertTrue(any("Turn a validation package" in title.value for title in app.title))
        self.assertFalse(app.exception)

    def test_browser_history_bridge_changes_content_without_rewriting_history(self) -> None:
        app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
        next(button for button in app.button if button.label == "Enter demo workspace").click().run()
        next(select for select in app.selectbox if select.label == "Page navigation").set_value("Upload").run()
        next(select for select in app.selectbox if select.label == "Page navigation").set_value("Run History").run()

        next(button for button in app.button if button.label == "Browser route: upload").click().run()
        self.assertTrue(any("Turn a validation package" in title.value for title in app.title))
        self.assertEqual(["run-history"], app.query_params["page"])
        next(button for button in app.button if button.label == "Browser route: run-history").click().run()
        self.assertIn("Run History", [title.value for title in app.title])
        self.assertEqual(["run-history"], app.query_params["page"])
        self.assertFalse(app.exception)

    def test_production_mode_fails_closed_without_oidc(self) -> None:
        os.environ["CSVQUALREVIEWER_MODE"] = "production"
        app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30).run()
        self.assertNotIn("Enter demo workspace", [button.label for button in app.button])
        self.assertTrue(any("Production mode requires configured OIDC" in error.value for error in app.error))
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
