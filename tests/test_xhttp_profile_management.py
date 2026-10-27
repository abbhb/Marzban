import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.routers import core
from app.services.xhttp_profiles import PROFILE_KEY, profile_document, validate_profiles
from app.subscription.xhttp import mihomo_xhttp_profiles
from app.xray.config import XRayConfig


def document():
    return {"inbounds": [{"tag": "XHTTP", "listen": "127.0.0.1", "port": 10085,
            "protocol": "vless", "settings": {"clients": [], "decryption": "none"},
            "streamSettings": {"network": "xhttp", "security": "none",
                "xhttpSettings": {"path": "/test/", "mode": "packet-up"}},
            PROFILE_KEY: [{"label": "one"}, {"label": "two"}]}],
            "outbounds": [{"protocol": "freedom", "tag": "DIRECT"}]}


def custom_profile():
    return {"label": "IPv6", "address": "2001:db8::10", "port": 443,
            "streamSettings": {"network": "xhttp", "security": "reality",
                "realitySettings": {"serverName": "front.example.test", "publicKey": "A" * 43, "shortId": "aabb"},
                "xhttpSettings": {"path": "/test/", "mode": "packet-up",
                    "xmux": {"maxConcurrency": "16-32"},
                    "downloadSettings": {"address": "cdn.example.test", "port": 443,
                        "network": "xhttp", "security": "tls",
                        "tlsSettings": {"serverName": "cdn.example.test", "alpn": ["h2"]},
                        "xhttpSettings": {"path": "/test/", "host": "cdn.example.test"}}}}}


class XhttpProfileManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "core.json"
        self.before = document()
        self.file.write_text(json.dumps(self.before))
        self.file.chmod(0o600)
        self.config = XRayConfig(self.before, api_port=49123)
        for name, value in (("XRAY_JSON", str(self.file)),):
            change = patch.object(core, name, value)
            change.start(); self.addCleanup(change.stop)
        change = patch.multiple(core.xray, config=self.config, hosts={}, nodes={})
        change.start(); self.addCleanup(change.stop)
        change = patch.object(core.xray.core, "restart")
        self.restart = change.start()
        self.addCleanup(change.stop)

    def update(self, profiles, revision=None):
        return core.put_xhttp_profiles(core.XhttpProfilesUpdate(
            revision=revision or core._flow_revision(self.before), inbounds={"XHTTP": profiles}), MagicMock())

    def test_save_reorder_disable_and_edit_are_persisted_without_restarting(self):
        result = self.update([{"label": "two", "enabled": False}, custom_profile(), {"label": "renamed"}])
        saved = json.loads(self.file.read_text())
        self.assertEqual([p["label"] for p in saved['inbounds'][0][PROFILE_KEY]], ['two', 'IPv6', 'renamed'])
        self.assertEqual(saved['inbounds'][0][PROFILE_KEY][0]['enabled'], False)
        changed = copy.deepcopy(saved)
        changed['inbounds'][0][PROFILE_KEY] = self.before['inbounds'][0][PROFILE_KEY]
        self.assertEqual(changed, self.before)
        self.assertEqual(core.xray.config.api_port, 49123)
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        self.assertNotEqual(result['revision'], core._flow_revision(self.before))
        self.restart.assert_not_called()
        # A new process also sees the saved metadata; this is not just a UI state.
        self.assertEqual(XRayConfig(self.file).inbounds_by_tag['XHTTP']['xhttpProfiles'], saved['inbounds'][0][PROFILE_KEY])

    def test_stale_save_does_not_overwrite_a_core_edit(self):
        with self.assertRaises(HTTPException) as error:
            self.update([{'label': 'stale'}], revision='old')
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(json.loads(self.file.read_text()), self.before)
        self.assertIs(core.xray.config, self.config)

    def test_invalid_inputs_leave_disk_and_memory_unchanged(self):
        cases = [
            [{'label': 'same'}, {'label': 'same'}], [{'label': ''}],
            [{'label': 'wrong', 'enabled': 'false'}], [{'label': str(i)} for i in range(9)],
        ]
        for mutation in ('private', 'port', 'path', 'download_key', 'key', 'address'):
            profile = custom_profile()
            if mutation == 'private': profile['streamSettings']['realitySettings']['privateKey'] = 'never-accept'
            elif mutation == 'port': profile['port'] = 65536
            elif mutation == 'path': profile['streamSettings']['xhttpSettings']['path'] = '/wrong/'
            elif mutation == 'download_key': profile['streamSettings']['xhttpSettings']['downloadSettings']['tlsSettings']['certificates'] = []
            elif mutation == 'key': profile['streamSettings']['realitySettings']['publicKey'] = 'bad'
            elif mutation == 'address': profile['address'] = 'https://example.test:443/private'
            cases.append([profile])
        for profiles in cases:
            with self.subTest(profiles=profiles), self.assertRaises(HTTPException):
                self.update(profiles)
            self.assertEqual(json.loads(self.file.read_text()), self.before)
            self.assertIs(core.xray.config, self.config)
        self.restart.assert_not_called()

    def test_failed_atomic_write_retains_old_file_and_runtime(self):
        with patch.object(core.os, 'replace', side_effect=OSError('disk failed')):
            with self.assertRaises(HTTPException) as error:
                self.update([{'label': 'new'}])
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(json.loads(self.file.read_text()), self.before)
        self.assertIs(core.xray.config, self.config)
        self.assertEqual(list(self.file.parent.iterdir()), [self.file])

    def test_disabled_profiles_are_absent_including_when_all_are_disabled(self):
        base = {'name': 'host', 'server': 'example.test', 'port': 443}
        rows = [{'label': 'third'}, {'label': 'second', 'enabled': False}, {'label': 'first'}]
        self.assertEqual([n['name'] for n in mihomo_xhttp_profiles(base, rows)], ['host · third', 'host · first'])
        for row in rows: row['enabled'] = False
        self.assertEqual(mihomo_xhttp_profiles(base, rows), [])
        self.assertEqual(mihomo_xhttp_profiles(base, []), [base])

    def test_public_getter_excludes_server_keys_and_certificate_files(self):
        raw = document()
        settings = custom_profile()['streamSettings']['xhttpSettings']
        settings['downloadSettings']['tlsSettings']['certificates'] = [{'keyFile': '/secret.pem'}]
        raw['inbounds'][0]['streamSettings']['xhttpSettings'] = settings
        raw['inbounds'][0]['server-only-secret'] = 'CANARY_SERVER_SECRET'
        result = profile_document(XRayConfig(raw), {}, 'revision')
        self.assertNotIn('/secret.pem', json.dumps(result))
        self.assertNotIn('CANARY_SERVER_SECRET', json.dumps(result))

    def test_ipv6_and_extra_settings_round_trip_without_losing_post_or_mux_options(self):
        row = custom_profile()
        transport = row['streamSettings']['xhttpSettings']
        transport['extra'] = {key: transport.pop(key) for key in ('xmux', 'downloadSettings')}
        transport['extra']['scMinPostsIntervalMs'] = '10-30'
        row['address'] = '[2001:db8::10]'
        result = validate_profiles([row], '/test/')[0]
        self.assertEqual(result['address'], '2001:db8::10')
        self.assertEqual(result['streamSettings'], row['streamSettings'])

