# SPDX-License-Identifier: Apache-2.0
"""Exercise the delivered artifact with real Chromium and publish individual outcomes."""
import functools
import http.server
import os
from pathlib import Path
import threading
import time
import unittest
import xml.etree.ElementTree as ET

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'artifacts'


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
            functools.partial(QuietHandler, directory=str(ARTIFACTS / 'site')))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'),
            args=['--no-sandbox'], headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.page = self.context.new_page()
        self.page.goto(self.base + '/')

    def tearDown(self):
        self.page.screenshot(path=str(ARTIFACTS / (self._testMethodName + '.png')), full_page=True)
        self.context.close()

    def test_search_opens_local_result_and_reload(self):
        self.page.locator('.md-search__button').click()
        self.page.get_by_role('combobox', name='Search').fill('diagnosis')
        result = self.page.locator('dialog a').filter(has_text='Evaluation is not diagnosis').first
        expect(result).to_be_visible()
        result.click()
        self.page.wait_for_url('**/vision.html?*#evaluation-is-not-diagnosis')
        self.page.reload()
        expect(self.page.locator('#evaluation-is-not-diagnosis')).to_be_visible()
        self.page.locator('.md-search__button').click()
        self.page.get_by_role('combobox', name='Search').fill('zzzxnonexistententry')
        expect(self.page.locator('dialog a')).to_have_count(0)
        self.page.keyboard.press('Escape')

    def test_architecture_from_homepage_search_and_redirect(self):
        self.page.locator('article a[href$="architecture/verification-architecture.html"]').first.click()
        self.page.wait_for_url('**/architecture/verification-architecture.html')
        expect(self.page.locator('.docs-identity')).to_contain_text('content ')
        expect(self.page.locator('.md-nav--primary').get_by_role('link', name='Verification architecture', exact=True)).to_have_count(1)
        self.page.goto(self.base + '/')
        self.page.locator('.md-search__button').click()
        self.page.get_by_role('combobox', name='Search').fill('verification architecture')
        result = self.page.locator('dialog a[href*="architecture/verification-architecture.html"]').first
        expect(result).to_be_visible()
        result.click()
        self.page.wait_for_url('**/architecture/verification-architecture.html*')
        self.page.goto(self.base + '/architecture.html')
        self.page.wait_for_url('**/architecture/verification-architecture.html')

    def test_palette_persists_and_follows_system(self):
        self.page.locator('label[for="__palette_1"]').click()
        self.page.locator('label[for="__palette_2"]').click()
        expect(self.page.locator('body')).to_have_attribute('data-md-color-scheme', 'slate')
        self.page.reload()
        expect(self.page.locator('body')).to_have_attribute('data-md-color-scheme', 'slate')
        self.page.locator('label[for="__palette_0"]').click()
        self.page.emulate_media(color_scheme='light')
        expect(self.page.locator('body')).to_have_attribute('data-md-color-scheme', 'default')
        self.page.emulate_media(color_scheme='dark')
        expect(self.page.locator('body')).to_have_attribute('data-md-color-scheme', 'slate')

    def test_responsive_navigation_and_old_fragments(self):
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for path in ('/#published-manuals', '/#livingproof',
                         '/vision.html#what-goes-in-what-comes-out',
                         '/vision.html#see-it-today'):
                self.page.goto(self.base + path)
                self.page.reload()
                expect(self.page.locator('[id="' + path.split('#')[1] + '"]')).to_have_count(1)
                self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
            self.page.goto(self.base + '/')
            self.page.keyboard.press('Tab')
            self.assertIn('Skip', self.page.evaluate('document.activeElement.textContent'))
            self.page.keyboard.press('Enter')
            self.assertTrue(self.page.url.endswith('#__skip'))
            if width == 390:
                # Start the drawer journey after the skip-link hash navigation settles.
                # A fresh load keeps its pending hashchange from closing the drawer.
                self.page.goto(self.base + '/')
                self.page.reload()
                self.page.locator('label.md-header__button[for="__drawer"]').first.click()
                expect(self.page.locator('#__drawer')).to_be_checked()
                link = self.page.locator('.md-nav--primary').get_by_role('link', name='Vision and terminology', exact=True)
                expect(link).to_be_in_viewport()
                link.click()
                self.page.wait_for_url('**/vision.html')
            self.page.screenshot(path=str(ARTIFACTS / f'navigation-{width}.png'), full_page=True)

    def test_mermaid_renders_on_desktop_and_mobile_in_light_and_dark(self):
        errors, external = [], []
        self.page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        self.page.on('pageerror', lambda e: errors.append(str(e)))
        # Offline proof that the vendored release renders: any non-local request fails.
        def guard(route):
            if route.request.url.startswith(self.base):
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()
        self.page.route('**/*', guard)
        # Zensical attaches each rendered diagram in a closed shadow root. Open it for the
        # test only, so the assertions can read the SVG Mermaid produced.
        self.page.add_init_script('const attach = Element.prototype.attachShadow;'
                                  'Element.prototype.attachShadow = function (init) {'
                                  ' return attach.call(this, {...init, mode: "open"}); };')
        for width, height in ((1440, 1000), (390, 844)):
            for scheme, palette in (('light', 'default'), ('dark', 'slate')):
                self.page.set_viewport_size({'width': width, 'height': height})
                self.page.emulate_media(color_scheme=scheme)
                self.page.goto(self.base + '/architecture/verification-architecture.html')
                expect(self.page.locator('body')).to_have_attribute('data-md-color-scheme', palette)
                diagrams = self.page.locator('.mermaid svg')
                expect(diagrams).to_have_count(3, timeout=20000)
                expect(self.page.locator('pre.mermaid')).to_have_count(0)
                expect(self.page.locator('div.mermaid')).to_have_count(3)
                expect(self.page.locator('div.mermaid').get_by_text('Syntax error')).to_have_count(0)
                expect(self.page.locator('.mermaid .error-icon')).to_have_count(0)
                first = diagrams.first
                for label in ('Verification consumer', 'capability-verifier', 'capability-report'):
                    expect(first.get_by_text(label).first).to_be_visible()
                self.assertTrue(self.page.evaluate('typeof mermaid === "object"'))
                for i in range(3):
                    box = diagrams.nth(i).bounding_box()
                    self.assertGreater(box['height'], 40)
                    self.assertLessEqual(box['x'] + box['width'], width + 1)
                # Effective label size: computed font size times the SVG's scale to fit.
                sizes = self.page.evaluate('''() => [...document.querySelectorAll('div.mermaid')].map(d => {
                    const svg = d.shadowRoot.querySelector('svg');
                    const scale = svg.getBoundingClientRect().width / svg.viewBox.baseVal.width;
                    return Math.min(...[...svg.querySelectorAll('.nodeLabel, .edgeLabel span, text')]
                        .filter(e => e.textContent.trim())
                        .map(e => parseFloat(getComputedStyle(e).fontSize) * scale)); })''')
                print(f'mermaid labels {width}px {scheme}: ' + ', '.join(f'{s:.1f}px' for s in sizes))
                self.assertTrue(all(s >= 12 for s in sizes), f'labels below 12 px at {width}: {sizes}')
                self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                diagrams.first.scroll_into_view_if_needed()
                self.page.locator('.mermaid').first.screenshot(
                    path=str(ARTIFACTS / f'mermaid-{width}-{scheme}.png'))
                self.page.screenshot(path=str(ARTIFACTS / f'mermaid-page-{width}-{scheme}.png'), full_page=True)
        # The site's existing font and GitHub-release widget requests are aborted here as
        # they are in the offline CI container; their load failures are the only allowed
        # console errors. Mermaid itself must come from the site, never a CDN.
        self.assertEqual([e for e in errors if 'net::ERR_FAILED' not in e], [])
        allowed = ('https://fonts.googleapis.com/', 'https://api.github.com/')
        self.assertEqual([u for u in external if not u.startswith(allowed)], [])

    def test_directory_identity_tasks_and_license(self):
        expect(self.page.locator('article table').first.locator('tbody tr')).to_have_count(7)
        expect(self.page.locator('.docs-identity')).to_contain_text('Docs: development')
        expect(self.page.locator('.docs-identity')).to_contain_text('publisher ')
        self.assertIn('current scope', self.page.locator('article').inner_text().lower())
        self.page.goto(self.base + '/tasks.html')
        for name in ('setup', 'build', 'check', 'test', 'verify'):
            expect(self.page.locator('#' + name)).to_have_count(1)
        self.assertNotIn('/workspace/', self.page.locator('article').inner_text())
        self.page.goto(self.base + '/vision.html')
        expect(self.page.locator('article')).to_contain_text('License: Apache-2.0')
        expect(self.page.locator('article')).to_contain_text('not proof of root cause')


class Results(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []
    def startTest(self, test):
        self.started = time.monotonic()
        super().startTest(test)
    def addSuccess(self, test):
        self.rows.append((test.id(), time.monotonic() - self.started, None))
        super().addSuccess(test)
    def addFailure(self, test, err):
        self.rows.append((test.id(), time.monotonic() - self.started, self._exc_info_to_string(err, test)))
        super().addFailure(test, err)
    def addError(self, test, err):
        self.rows.append((test.id(), time.monotonic() - getattr(self, 'started', time.monotonic()), self._exc_info_to_string(err, test)))
        super().addError(test, err)


if __name__ == '__main__':
    ARTIFACTS.mkdir(exist_ok=True)
    result = unittest.TextTestRunner(verbosity=2, resultclass=Results).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(BrowserTests))
    suite = ET.Element('testsuite', tests=str(len(result.rows)),
                       failures=str(sum(row[2] is not None for row in result.rows)))
    for name, duration, failure in result.rows:
        case = ET.SubElement(suite, 'testcase', name=name, time=str(duration))
        if failure:
            ET.SubElement(case, 'failure').text = failure
    ET.ElementTree(suite).write(ARTIFACTS / 'browser-tests.xml', encoding='utf-8', xml_declaration=True)
    raise SystemExit(not result.wasSuccessful())
