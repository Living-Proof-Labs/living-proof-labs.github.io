# SPDX-License-Identifier: Apache-2.0
"""Exercise the delivered artifact with real Chromium and publish individual outcomes."""
import functools
import http.server
import os
from pathlib import Path
import threading
import time
import unittest
import urllib.request
import xml.etree.ElementTree as ET

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'artifacts'
CONTENT = Path(os.environ.get('CONTENT_DIR') or ROOT / '.content').resolve()
# brand.css imports these faces. Offline CI (docker --network none) cannot fetch
# them; they are not site files and not the GitHub releases lookup.
EXCUSED_REQUEST_PREFIXES = (
    'https://fonts.googleapis.com/',
    'https://fonts.gstatic.com/',
)


def excused_request(url):
    return url.startswith(EXCUSED_REQUEST_PREFIXES)


def chrome_cancels_recording(url, reason):
    """Chrome reports net::ERR_ABORTED for the hallway recording without a bad response.

    After a successful 206 it cancels its own media loader, and the video element
    still reaches HAVE_ENOUGH_DATA. Leaving the page also cancels an in-flight
    download. GitHub Pages sends video/mp4 and a correct byte range, and the moov
    atom already precedes mdat, so this is not a broken file. An HTTP error for
    the same URL is still a failure.
    """
    path = url.split('?', 1)[0]
    return reason == 'net::ERR_ABORTED' and path.endswith('/media/g1-comparison.mp4')


def first_table_rows(markdown):
    """Data rows of the first Markdown table, so the content decides the count."""
    lines = markdown.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('|'))
    rows = []
    for line in lines[start:]:
        if not line.startswith('|'):
            break
        rows.append(line)
    return len(rows) - 2  # header and delimiter


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
        self.release_requests = []
        self.failed_requests = []

        def on_request(request):
            url = request.url
            if 'api.github.com' in url and '/releases' in url:
                self.release_requests.append(url)

        def on_response(response):
            if response.status >= 400 and not excused_request(response.url):
                self.failed_requests.append(f'{response.status} {response.url}')

        def on_failed(request):
            if excused_request(request.url):
                return
            failure = request.failure
            if isinstance(failure, str):
                reason = failure
            elif isinstance(failure, dict):
                reason = failure.get('errorText', 'failed')
            else:
                reason = 'failed'
            if chrome_cancels_recording(request.url, reason):
                return
            self.failed_requests.append(f'{reason} {request.url}')

        self.page.on('request', on_request)
        self.page.on('response', on_response)
        self.page.on('requestfailed', on_failed)
        self.page.goto(self.base + '/')

    def tearDown(self):
        try:
            self.page.screenshot(path=str(ARTIFACTS / (self._testMethodName + '.png')), full_page=True)
            self.assertEqual(self.release_requests, [])
            self.assertEqual(self.failed_requests, [])
        finally:
            self.context.close()

    def test_root_favicon_is_served(self):
        with urllib.request.urlopen(self.base + '/favicon.ico') as response:
            body = response.read()
            content_type = response.headers.get_content_type()
            status = response.status
        self.assertEqual(status, 200)
        self.assertIn(content_type, ('image/vnd.microsoft.icon', 'image/x-icon'))
        self.assertTrue(body.startswith(b'\x00\x00\x01\x00'))
        self.assertEqual(body, (ROOT / 'docs' / 'favicon.ico').read_bytes())

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
            self.page.wait_for_url(lambda url: url.endswith('#__skip'))
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
        # Brand fonts are the only requests that may leave the box. The header
        # repository badge must not call the GitHub releases API.
        allowed = EXCUSED_REQUEST_PREFIXES
        self.page.on('console', lambda m: m.type == 'error' and errors.append(
            (m.text, (m.location or {}).get('url', ''))))
        self.page.on('pageerror', lambda e: errors.append((str(e), '')))
        # Offline proof that the vendored release renders: no request ever leaves the box.
        # Every non-local request is answered here with an empty 204, so the result does not
        # depend on whether the host has a network (Chromium reports ERR_FAILED for an abort
        # but ERR_INTERNET_DISCONNECTED under docker --network none).
        def guard(route):
            if route.request.url.startswith(self.base):
                route.continue_()
            else:
                external.append(route.request.url)
                route.fulfill(status=204, body='')
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
        # Only the brand fonts may reach outward (answered with 204 above); a network
        # failure is tolerated only for those origins, under either code. Mermaid
        # itself must come from the site, never a CDN. A GitHub releases request is
        # not tolerated: this publisher has no releases, and that lookup 404s.
        net = ('net::ERR_FAILED', 'net::ERR_INTERNET_DISCONNECTED')
        self.assertEqual([t for t, url in errors
                          if not (url.startswith(allowed) and any(c in t for c in net))], [])
        self.assertEqual([u for u in external if not u.startswith(allowed)], [])

    def test_comparison_recording_caption_caveat_and_fit(self):
        caveat = (
            'Historical recording: the Booster T1 pane in the segment from 00:47 to 00:56 '
            'is an open checkerboard scene, not the hallway shown in the Unitree G1 comparison. '
            'That segment does not establish equivalent test conditions or comparable results '
            'across the robots shown there.'
        )
        video = self.page.locator('video')
        expect(video).to_have_count(1)
        expect(video).to_have_attribute('poster', 'media/g1-comparison-poster.jpg')
        expect(video).to_have_attribute('preload', 'metadata')
        expect(video.locator('source')).to_have_attribute('src', 'media/g1-comparison.mp4')
        expect(video.locator('source')).to_have_attribute('type', 'video/mp4')
        track = video.locator('track')
        expect(track).to_have_attribute('src', 'media/g1-comparison.en.vtt')
        expect(track).to_have_attribute('srclang', 'en')
        expect(track).to_have_attribute('label', 'English')
        self.assertEqual(self.page.evaluate('''() => {
            const video = document.querySelector('video');
            const track = document.querySelector('track');
            return {autoplay: video.autoplay, controls: video.controls, playsinline: video.playsInline,
                    defaultTrack: track.default, videos: document.querySelectorAll('video').length};
        }'''), {'autoplay': False, 'controls': True, 'playsinline': True, 'defaultTrack': True, 'videos': 1})
        expect(self.page.locator('#g1-comparison-caption')).to_contain_text(
            'Snapshot recorded 1 Nov 2026, spec v1.5.0.')
        expect(self.page.locator('#g1-comparison-caption a')).to_have_attribute(
            'href', 'https://docs.livingprooflabs.com/livingproof-verification/')
        expect(self.page.locator('#g1-comparison-limit')).to_contain_text(caveat)
        expect(self.page.locator('video a[href="media/g1-comparison.mp4"]')).to_have_count(1)
        poster = self.page.evaluate('''async () => {
            const img = new Image();
            img.src = document.querySelector('video').poster;
            await img.decode();
            return [img.naturalWidth, img.naturalHeight];
        }''')
        self.assertEqual(poster, [1280, 720])
        fetched = self.page.evaluate('''async () => {
            const track = await fetch(document.querySelector('track').src);
            const trackText = await track.text();
            const movie = await fetch(document.querySelector('video source').src, {headers: {Range: 'bytes=0-15'}});
            const bytes = Array.from(new Uint8Array(await movie.arrayBuffer()));
            const probe = document.createElement('video');
            return {trackOk: track.ok, trackText, videoStatus: movie.status, bytes,
                    canPlay: probe.canPlayType('video/mp4; codecs="avc1.42E01E"')};
        }''')
        self.assertTrue(fetched['trackOk'])
        self.assertIn('WEBVTT', fetched['trackText'])
        self.assertIn('Spec v1.5.0', fetched['trackText'])
        self.assertNotIn('at time of recording', fetched['trackText'])
        self.assertIn(fetched['videoStatus'], (200, 206))
        self.assertEqual(bytes(fetched['bytes'][4:8]), b'ftyp')
        if fetched['canPlay']:
            self.page.wait_for_function(
                '() => { const v = document.querySelector("video"); return v.readyState >= 1; }',
                timeout=10000)
            decoded = self.page.evaluate('''() => {
                const v = document.querySelector('video');
                return {width: v.videoWidth, height: v.videoHeight, duration: v.duration, paused: v.paused};
            }''')
            self.assertEqual([decoded['width'], decoded['height']], [1280, 720])
            self.assertAlmostEqual(decoded['duration'], 66.04, delta=0.05)
            self.assertTrue(decoded['paused'])
        else:
            print('mp4 decode is unavailable in this browser; file bytes were checked instead')
        for width, height in ((1440, 1000), (390, 844)):
            for scheme, palette in (('light', 'default'), ('dark', 'slate')):
                self.page.set_viewport_size({'width': width, 'height': height})
                self.page.emulate_media(color_scheme=scheme)
                self.page.goto(self.base + '/#how-it-works')
                expect(self.page.locator('body')).to_have_attribute('data-md-color-scheme', palette)
                figure = self.page.locator('figure').filter(has=self.page.locator('video'))
                expect(figure).to_be_visible()
                expect(self.page.locator('#g1-comparison-caption')).to_be_visible()
                expect(self.page.locator('#g1-comparison-limit')).to_be_visible()
                box = figure.bounding_box()
                self.assertLessEqual(box['x'] + box['width'], width + 1)
                self.assertGreater(box['height'], 120)
                self.assertFalse(self.page.evaluate('''() => {
                    const nodes = [document.getElementById('g1-comparison-caption'),
                                   document.getElementById('g1-comparison-limit'),
                                   document.querySelector('video')];
                    return nodes.some(node => node.scrollWidth > node.clientWidth + 1)
                        || document.documentElement.scrollWidth > innerWidth;
                }'''))
                # Scroll the figure under the header and capture the viewport. An element
                # screenshot of this tall figure also paints the fixed "On this page" control.
                self.page.evaluate('''() => {
                    const fig = document.querySelector('video').closest('figure');
                    const header = document.querySelector('.md-header');
                    const top = fig.getBoundingClientRect().top + window.scrollY
                        - ((header && header.offsetHeight) || 0) - 8;
                    window.scrollTo(0, Math.max(0, top));
                }''')
                self.page.screenshot(path=str(ARTIFACTS / f'recording-{width}-{scheme}.png'))

    def test_directory_identity_tasks_and_license(self):
        tasks = first_table_rows((CONTENT / 'docs' / 'index.md').read_text(encoding='utf-8'))
        self.assertGreater(tasks, 0)
        expect(self.page.locator('article table').first.locator('tbody tr')).to_have_count(tasks)
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
