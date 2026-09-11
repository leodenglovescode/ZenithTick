from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FrontendPreferenceTests(unittest.TestCase):
    def test_sensitive_location_is_hidden_by_default(self) -> None:
        html = (PROJECT_ROOT / "web" / "templates" / "index.html").read_text()
        self.assertIn('data-location-visible="false"', html)
        for field in ("latitude", "longitude", "altitude"):
            self.assertIn(f'id="{field}" class="sensitive-value" aria-hidden="true"', html)

    def test_preference_bootstrap_runs_before_stylesheet(self) -> None:
        html = (PROJECT_ROOT / "web" / "templates" / "index.html").read_text()
        self.assertLess(html.index("preferences.js"), html.index("style.css"))
        bootstrap = (PROJECT_ROOT / "web" / "static" / "preferences.js").read_text()
        self.assertIn('localStorage.getItem("zenitick.theme")', bootstrap)
        self.assertIn('localStorage.getItem("zenitick.locationVisible")', bootstrap)

    def test_theme_and_privacy_controls_are_accessible(self) -> None:
        html = (PROJECT_ROOT / "web" / "templates" / "index.html").read_text()
        self.assertIn('id="theme-toggle"', html)
        self.assertIn('aria-label="Use light theme"', html)
        self.assertIn('id="privacy-toggle"', html)
        self.assertIn('aria-label="Show location values"', html)

        css = (PROJECT_ROOT / "web" / "static" / "style.css").read_text()
        self.assertIn('html[data-theme="light"]', css)
        self.assertIn(".sensitive-value { filter: blur(5px)", css)

    def test_instrument_uses_full_browser_width(self) -> None:
        css = (PROJECT_ROOT / "web" / "static" / "style.css").read_text()
        instrument_rule = css.split(".instrument {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 100%", instrument_rule)
        self.assertNotIn("max-width", instrument_rule)

    def test_wide_layout_places_live_tables_side_by_side(self) -> None:
        html = (PROJECT_ROOT / "web" / "templates" / "index.html").read_text()
        css = (PROJECT_ROOT / "web" / "static" / "style.css").read_text()
        self.assertIn('<div class="detail-grid">', html)
        self.assertIn("@media (min-width: 1500px)", css)
        self.assertIn("grid-template-columns: minmax(0, 3fr) minmax(640px, 2fr)", css)
        self.assertIn(".detail-grid .timing-strip", css)


if __name__ == "__main__":
    unittest.main()
