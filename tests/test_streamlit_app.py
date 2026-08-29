from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


class StreamlitAppTests(unittest.TestCase):
    def test_landing_page_and_sample_review(self) -> None:
        app = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=30)
        app.run()

        self.assertFalse(app.exception)
        self.assertIn(
            "Welcome back, Arvind 👋",
            [title.value for title in app.title],
        )

        sample_button = next(
            button
            for button in app.button
            if button.label == "Use realistic sample package"
        )
        sample_button.click().run(timeout=30)

        self.assertFalse(app.exception)
        self.assertTrue(
            any("Executive Summary" in markdown.value for markdown in app.markdown)
        )


if __name__ == "__main__":
    unittest.main()
