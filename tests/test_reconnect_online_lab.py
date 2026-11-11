"""Real cryptography with an in-process peer; no firmware or HA runtime."""
import asyncio
from hashlib import sha256
import importlib
from pathlib import Path
import sys
import types
import unittest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

base = Path(__file__).resolve().parents[1] / 'custom_components/omote_manager'
pkg = types.ModuleType('reconnect_online_tests'); pkg.__path__ = [str(base)]
sys.modules[pkg.__name__] = pkg
crypto = importlib.import_module(pkg.__name__ + '.reconnect_crypto_draft')
lab = importlib.import_module(pkg.__name__ + '.reconnect_online_lab')

class Peer:
    def __init__(self, device, ha_pub, tamper=None):
        self.device, self.ha_pub, self.tamper = device, ha_pub, tamper
        self.eph = ec.generate_private_key(ec.SECP256R1())
        self.challenge = b'd' * 32
        self.calls = []
    async def exchange(self, stage, msg):
        self.calls.append(stage)
        if stage == 'open':
            assert msg['ha_static'] == self.ha_pub
            self.fields = dict(ha_static=self.ha_pub, device_static=crypto.public_bytes(self.device.public_key()), ha_ephemeral=msg['ha_ephemeral'], device_ephemeral=crypto.public_bytes(self.eph.public_key()), ha_challenge=msg['ha_challenge'], device_challenge=self.challenge)
            self.ctx = crypto.transcript(**self.fields)
            self.signature = crypto.sign(self.device, 'device', self.ctx)
            if self.tamper == 'signature': self.signature = self.signature[:-1] + bytes([self.signature[-1] ^ 1])
            return dict(device_ephemeral=self.fields['device_ephemeral'], device_challenge=self.challenge, device_signature=self.signature)
        assert stage == 'confirm'
        send, receive = crypto.derive(role='device', own_ephemeral=self.eph, **self.fields, ha_signature=msg['ha_signature'], device_signature=self.signature, pinned_ha_sha256=sha256(self.ha_pub).digest(), pinned_device_sha256=sha256(self.fields['device_static']).digest())
        aad = sha256(self.ctx).digest()
        probe = AESGCM(receive).decrypt(bytes(12), msg['ciphertext'], aad)
        ciphertext = AESGCM(send).encrypt(bytes(12), probe, aad)
        return ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]) if self.tamper == 'response' else ciphertext

class OnlineLabTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ha = ec.generate_private_key(ec.SECP256R1())
        self.dev = ec.generate_private_key(ec.SECP256R1())
        self.ha_pub = crypto.public_bytes(self.ha.public_key())
        self.dev_pub = crypto.public_bytes(self.dev.public_key())
    async def run_peer(self, peer, pin=None):
        return await lab.run_reconnect_lab(transport=peer, ha_key=self.ha, device_public=pin or self.dev_pub, ack_lab_only=True)
    async def test_success_is_never_pairing(self):
        p = Peer(self.dev, self.ha_pub)
        result = await self.run_peer(p)
        self.assertTrue(result['encrypted_reconnect_verified'])
        self.assertFalse(result['paired']); self.assertFalse(result['deployment_enabled'])
        self.assertEqual(p.calls, ['open', 'confirm'])
    async def test_wrong_device_key_and_bad_signature_fail_before_confirm(self):
        for tamper in ('signature', None):
            peer = Peer(self.dev, self.ha_pub, tamper)
            pin = self.dev_pub if tamper else crypto.public_bytes(ec.generate_private_key(ec.SECP256R1()).public_key())
            with self.assertRaises(lab.ReconnectLabError): await self.run_peer(peer, pin)
            self.assertEqual(peer.calls, ['open'])
    async def test_modified_encrypted_response_fails(self):
        with self.assertRaises(lab.ReconnectLabError): await self.run_peer(Peer(self.dev, self.ha_pub, 'response'))
    async def test_requires_explicit_lab_ack(self):
        p = Peer(self.dev, self.ha_pub)
        with self.assertRaises(lab.ReconnectLabError):
            await lab.run_reconnect_lab(transport=p, ha_key=self.ha, device_public=self.dev_pub)
        self.assertFalse(p.calls)
    async def test_old_open_reply_rejected_on_new_session(self):
        peer = Peer(self.dev, self.ha_pub)
        original = peer.exchange
        saved = {}
        async def capture(stage, msg):
            result = await original(stage, msg)
            if stage == 'open': saved['reply'] = result
            return result
        peer.exchange = capture
        await self.run_peer(peer)
        async def replay(stage, msg):
            if stage == 'open': return saved['reply']
            raise AssertionError('stale response reached confirm')
        peer.exchange = replay
        with self.assertRaises(lab.ReconnectLabError): await self.run_peer(peer)
