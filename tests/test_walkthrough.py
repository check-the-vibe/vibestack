"""Diagnostics must never accept arbitrary user text or bypass origin checks."""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'control'))
import walkthrough
from tests import test_control_api


class DiagnosticSchemaTests(unittest.TestCase):
    def setUp(self):
        self.event = dict(session='a'*32, seq=1, kind='step', page='/setup/', step='password')

    def test_fixed_metadata_accepted_and_raw_text_rejected(self):
        self.assertEqual(walkthrough.validate(self.event), self.event)
        for key, value in [('password','not-logged'),('body','not-logged'),('endpoint','/private?token=not-logged'),('action','not-logged'),('error','secret exception message'),('seq',True),('duration_ms',-1),('session','not-logged')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                walkthrough.validate(dict(self.event, **{key:value}))

    def test_bounded_logging(self):
        output=io.StringIO()
        with mock.patch.object(walkthrough, '_count', 0), mock.patch.object(walkthrough, '_window', 10), mock.patch.object(walkthrough.time, 'monotonic', return_value=11), contextlib.redirect_stdout(output):
            for _ in range(200):
                self.assertTrue(walkthrough.record(self.event))
            self.assertFalse(walkthrough.record(self.event))
        self.assertEqual(len(output.getvalue().splitlines()), 200)


class DiagnosticHTTPTests(unittest.TestCase):
    setUp = test_control_api.HTTPServiceTests.setUp
    tearDown = test_control_api.HTTPServiceTests.tearDown
    request = test_control_api.HTTPServiceTests.request

    def test_diagnostics_origin_and_unknown_fields(self):
        event=dict(session='b'*32,seq=1,kind='page',page='/setup/')
        with mock.patch.object(walkthrough, 'record', return_value=True) as record:
            self.assertEqual(self.request('POST','/api/v1/diagnostics/events',event)[0],202)
            record.assert_called_once_with(event)
            self.assertEqual(self.request('POST','/api/v1/diagnostics/events',event,{'Origin':'https://evil.invalid'})[0],403)
            self.assertEqual(record.call_count,1)
        self.assertEqual(self.request('POST','/api/v1/diagnostics/events',dict(event,password='not-logged'))[0],400)
