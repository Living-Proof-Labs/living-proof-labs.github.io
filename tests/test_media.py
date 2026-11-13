# SPDX-License-Identifier: Apache-2.0
"""docs/media is copied as bytes, and a missing poster or caption track fails the check.

The copy is the whole directory, not a list of recording filenames. An older
content revision with no docs/media directory produces no media directory.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'artifacts' / 'site'
sys.path.insert(0, str(ROOT / 'tools'))
from build_docs import copy_content_media, media_digests  # noqa: E402
from check_site import Page, main as check_site  # noqa: E402

# Organization directory #80 merge; preserves the exact reviewed recording bytes.
MERGED = 'dc189945fd4b376a9bdd3b9c0c4f5b68f5d9a81d'
# Reviewed pre-merge tip. The pin must be the merge commit, which has the same
# recording bytes; this constant is the commit the lock must not use.
REVIEWED_TIP = 'adb1144c68d915e8331efa58b719c38cb6486427'
# Unmerged tip of the NOTICE wording pull request. The lock uses the merge.
NOTICE_TIP = '942d173900079d1c070e8076b39501f50d481335'
RECORDING = {
    'g1-comparison.mp4': '918330b81b9e4de5c6a5b9c5b3aa81de21c42e9ddd246c049e8b1acdb07ca0ca',
    'g1-comparison-poster.jpg': 'f4cf729e36fd5a6def52a151346e1aae842023694f74895ab3190452de361455',
    'g1-comparison.en.vtt': '7652f3d89dc87f712ba55926603391c5bd85d1ea0e1382dbe0f042880b246428',
    'NOTICE.txt': 'de97fe0c33a30f58a45940961b4d30787a92c7514928cb0040aeeb6f56f7cbd4',
}
CAVEAT = (
    'Historical recording: the Booster T1 pane in the segment from 00:47 to 00:56 '
    'is an open checkerboard scene, not the hallway shown in the Unitree G1 comparison. '
    'That segment does not establish equivalent test conditions or comparable results '
    'across the robots shown there.'
)
CAPTION = 'Snapshot recorded 1 Nov 2026, spec v1.5.0.'


def run_check(site):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        failed = check_site([str(site)])
    return failed, output.getvalue()


def fail_lines(output):
    return [line for line in output.splitlines() if line.startswith('FAIL:')]


class MediaCopy(unittest.TestCase):
    def test_missing_directory_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / 'content'
            (content / 'docs').mkdir(parents=True)
            (content / 'docs' / 'index.md').write_text('older page\n')
            destination = Path(tmp) / 'site' / 'media'
            copy_content_media(content, destination)
            self.assertFalse(destination.exists())
            self.assertEqual(media_digests(content), {})

    def test_copies_the_whole_directory_without_changing_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / 'content'
            media = content / 'docs' / 'media'
            nested = media / 'nested'
            nested.mkdir(parents=True)
            notice = b'Provenance for the hallway comparison recording\n'
            payload = bytes(range(256)) + b'\x00immutable'
            (media / 'NOTICE.txt').write_bytes(notice)
            (nested / 'clip.bin').write_bytes(payload)
            (content / 'docs' / 'not-media.txt').write_bytes(b'leave this')
            destination = Path(tmp) / 'built' / 'media'
            copy_content_media(content, destination)
            self.assertEqual((destination / 'NOTICE.txt').read_bytes(), notice)
            self.assertEqual((destination / 'nested' / 'clip.bin').read_bytes(), payload)
            self.assertFalse((destination / 'not-media.txt').exists())
            self.assertEqual(media_digests(content), {
                'NOTICE.txt': hashlib.sha256(notice).hexdigest(),
                'nested/clip.bin': hashlib.sha256(payload).hexdigest(),
            })


class VideoReferences(unittest.TestCase):
    def test_poster_track_and_source_are_checked_not_only_the_download(self):
        page = Page('''<video poster="media/g1-comparison-poster.jpg">
          <source src="media/g1-comparison.mp4" type="video/mp4" />
          <track kind="captions" src="media/g1-comparison.en.vtt" srclang="en" default />
          <a href="media/g1-comparison.mp4">Download the comparison video (MP4)</a>
        </video>''')
        self.assertIn('media/g1-comparison-poster.jpg', page.links)
        self.assertIn('media/g1-comparison.en.vtt', page.links)
        self.assertEqual(page.links.count('media/g1-comparison.mp4'), 2)


class BuiltRecording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (SITE / 'index.html').is_file() or not (SITE / 'build.json').is_file():
            raise AssertionError('Missing built site; run task build first')

    def test_pin_provenance_and_bytes(self):
        lock = json.loads((ROOT / 'content.lock.json').read_text())
        identity = json.loads((SITE / 'build.json').read_text())
        content = identity['content']
        self.assertEqual(lock['repository'], 'Living-Proof-Labs/.github')
        self.assertEqual(lock['commit'], MERGED)
        self.assertNotEqual(lock['commit'], REVIEWED_TIP)
        self.assertNotEqual(lock['commit'], NOTICE_TIP)
        self.assertEqual(content['commit'], MERGED)
        self.assertEqual(content['locked_commit'], MERGED)
        self.assertTrue(content['pinned'])
        self.assertFalse(content['dirty'])
        self.assertEqual(content['media_files'], RECORDING)
        source_media = Path(os.environ.get('CONTENT_DIR') or ROOT / '.content') / 'docs' / 'media'
        self.assertTrue(source_media.is_dir(), 'pinned docs/media was not fetched')
        published = {}
        for path in source_media.rglob('*'):
            if not path.is_file():
                continue
            rel = path.relative_to(source_media).as_posix()
            built = SITE / 'media' / rel
            self.assertTrue(built.is_file(), rel)
            self.assertEqual(built.read_bytes(), path.read_bytes(), rel)
            published[rel] = hashlib.sha256(built.read_bytes()).hexdigest()
        self.assertEqual(published, RECORDING)
        notice = (SITE / 'media' / 'NOTICE.txt').read_text(encoding='utf-8')
        for phrase in (
            'Source repository: Living-Proof-Labs/website',
            'Source commit: 2bddea0327f016e1a1a7f57d1fb4bc7384754393',
            '4faae73777c9c853420769a37bfd364dcec247a9',
            'e84323eb05b7136260ea32bad34e058d2505d433',
            'bb67a1f5199d206704cf19945a4fa6ce680f9cf8',
            RECORDING['g1-comparison.mp4'],
            RECORDING['g1-comparison-poster.jpg'],
            RECORDING['g1-comparison.en.vtt'],
            'edits only that last cue, removing',
            'at time of recording',
            'This copy does not\nrelicense the recording.',
            'Git history at that commit still',
            'has the files. This note does not claim they remain on the website\'s current',
            '47be2bc708f34e93ff6fff86c092a35176b5a818 removed these three paths from the',
        ):
            self.assertIn(phrase, notice)
        self.assertNotIn('still has the originals', notice)
        page = (SITE / 'index.html').read_text(encoding='utf-8')
        video_at = page.find('<video')
        video_end = page.find('</video>', video_at)
        video_html = page[video_at:video_end]
        self.assertEqual(page.count('<video'), 1)
        self.assertGreater(video_at, 0)
        self.assertIn(CAPTION, page)
        self.assertIn(CAVEAT, page)
        self.assertNotIn('autoplay', video_html)
        links = Page(page).links
        for name in RECORDING:
            if name == 'NOTICE.txt':
                continue
            self.assertTrue(any(item.endswith(name) for item in links), name)
        failed, output = run_check(SITE)
        self.assertFalse(failed, output)

    def test_missing_poster_or_track_fails_while_the_download_remains(self):
        self._expect_missing('g1-comparison-poster.jpg')
        self._expect_missing('g1-comparison.en.vtt')

    def test_changed_video_bytes_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / 'site'
            shutil.copytree(SITE, site)
            video = site / 'media' / 'g1-comparison.mp4'
            original = video.read_bytes()
            video.write_bytes(original[:-1] + bytes([original[-1] ^ 0x01]))
            failed, output = run_check(site)
        self.assertTrue(failed)
        self.assertTrue(any('Media bytes differ from build.json: media/g1-comparison.mp4' in line
                            for line in fail_lines(output)), output)
        self.assertFalse(any('g1-comparison.mp4' in line and 'missing' in line
                             for line in fail_lines(output)), output)

    def _expect_missing(self, name):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / 'site'
            shutil.copytree(SITE, site)
            (site / 'media' / name).unlink()
            failed, output = run_check(site)
        lines = fail_lines(output)
        self.assertTrue(failed, output)
        self.assertTrue(any(name in line and line.startswith('FAIL: index.html: missing ')
                            for line in lines), output)
        self.assertTrue(any(f'Missing built media file: media/{name}' in line for line in lines), output)
        self.assertFalse(any('g1-comparison.mp4' in line and 'missing' in line for line in lines), output)


if __name__ == '__main__':
    unittest.main()
