# SPDX-License-Identifier: Apache-2.0
"""Ordinary final-HTML destination fixtures; no browser execution required."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_site import Page


class RenderedDestinations(unittest.TestCase):
    def test_ordinary_relative_https_and_contact_destinations(self):
        page = Page('<a href="guide.html#example">Guide</a>'
                    '<a href="https://example.org/?a=1&amp;b=2">Source</a>'
                    '<a href="mailto:team@example.org">Contact</a>'
                    '<img src="media/poster.jpg">')
        self.assertEqual(page.destination_errors, [])
        self.assertIn('https://example.org/?a=1&b=2', page.links)

    def test_unsupported_destination_and_base_are_rejected(self):
        for html in ['<a href="file:///example.txt">Local document</a>',
                     '<img src="ftp://example.org/poster.jpg">',
                     '<a href="https://user@example.org/">Account</a>',
                     '<base href="https://example.org/">']:
            with self.subTest(html=html):
                self.assertTrue(Page(html).destination_errors)
