"""How BrowserTestCase starts and stops (Codex audit M-22): a broken browser must not pass as a skip,
and a failed start must leave nothing behind. The server and Playwright are fakes here, so this runs
everywhere, SQLite included."""
import multiprocessing
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from channels.testing import ChannelsLiveServerTestCase
from django.test import SimpleTestCase

from chats import test_browser

MISSING_BROWSER = "BrowserType.launch: Executable doesn't exist at /nowhere/chrome-headless-shell"


class BrowserSetupTests(SimpleTestCase):
    def start(self, launch_error, required, vendor='postgresql'):
        """Run a one-test BrowserTestCase whose browser fails to launch; return the result and the fakes."""
        playwright = mock.Mock()
        playwright.chromium.launch.side_effect = Exception(launch_error)
        server = mock.Mock()

        class Probe(test_browser.BrowserTestCase):   # defined here, so the test runner never collects it
            def test_nothing(self):
                pass

        result = unittest.TestResult()
        with (
            mock.patch.object(test_browser, 'REQUIRED', required),
            mock.patch.object(test_browser, 'connection', SimpleNamespace(vendor=vendor)),
            mock.patch.object(test_browser, 'sync_playwright', lambda: SimpleNamespace(start=lambda: playwright)),
            mock.patch.object(ChannelsLiveServerTestCase, 'setUpClass', classmethod(lambda cls: server.start())),
            mock.patch.object(ChannelsLiveServerTestCase, 'tearDownClass', classmethod(lambda cls: server.stop())),
        ):
            unittest.TestSuite([Probe('test_nothing')]).run(result)
        return result, playwright, server

    def test_where_browser_tests_are_required_a_launch_failure_fails(self):
        result, _, _ = self.start(MISSING_BROWSER, required=True)
        self.assertEqual((len(result.errors), len(result.skipped)), (1, 0))

    def test_where_browser_tests_are_required_sqlite_fails(self):
        result, _, _ = self.start(MISSING_BROWSER, required=True, vendor='sqlite')
        self.assertEqual((len(result.errors), len(result.skipped)), (1, 0))

    def test_otherwise_a_missing_browser_is_a_skip(self):
        result, _, _ = self.start(MISSING_BROWSER, required=False)
        self.assertEqual((len(result.errors), len(result.skipped)), (0, 1))

    def test_an_unexpected_launch_error_is_never_a_skip(self):
        result, _, _ = self.start('Target page, context or browser has been closed', required=False)
        self.assertEqual((len(result.errors), len(result.skipped)), (1, 0))

    def test_a_failed_start_stops_everything_it_started_and_restores_the_settings(self):
        method = multiprocessing.get_start_method(allow_none=True)
        with mock.patch.dict(os.environ, {'DJANGO_ALLOW_ASYNC_UNSAFE': 'as-before'}):
            _, playwright, server = self.start('boom', required=False)
            self.assertEqual(os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'], 'as-before')
        self.assertEqual(multiprocessing.get_start_method(allow_none=True), method)
        server.stop.assert_called_once()
        playwright.stop.assert_called_once()

    def test_an_unset_setting_is_unset_again(self):
        with mock.patch.dict(os.environ):
            os.environ.pop('DJANGO_ALLOW_ASYNC_UNSAFE', None)
            self.start(MISSING_BROWSER, required=False)
            # Not assertNotIn: its failure message prints the whole environment, secrets included.
            self.assertIsNone(os.environ.get('DJANGO_ALLOW_ASYNC_UNSAFE'))
