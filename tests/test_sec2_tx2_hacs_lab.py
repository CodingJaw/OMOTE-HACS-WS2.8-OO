"""Offline HACS-to-v2 LAB framing tests using real P-256 signatures.

The simulated transport is not a Security2 or physical hardware acceptance.
"""
import asyncio
from hashlib import sha256
import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_candidate_identity import identity, FakeHAStore
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

package = identity.__package__
lab = importlib.import_module(package + '.sec2_lab_session')
proof = importlib.import_module(package + '.sec2_mutual_transaction_proof_v2_draft')
txmod = importlib.import_module(package + '.sec2_tx_v2_lab')


class MockSecurity:
    def __init__(self, **kwargs):
        assert kwargs['sec_patch_ver'] == 1
        self.step = 0
    def security_session(self, response):
        self.step += 1
        return 'SRP' if self.step == 1 else None
    def encrypt_data(self, b): return b
    def decrypt_data(self, b): return b


class MockTransport:
    patch = 1
    corrupt = False
    reject = False
    bad_receipt = False
    def __init__(self, address):
        self.headers = {'Cookie': 'session=17'}
        self.calls = []
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.pub = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.closed = False
    async def send_data(self, endpoint, payload):
        self.calls.append(endpoint)
        if endpoint == 'proto-ver':
            return '{"prov":{"ver":"omote-sec2-lab-v1","sec_patch_ver":%d}}' % self.patch
        if endpoint == 'prov-session': return 'SRP-RESPONSE'
        b = payload.encode('latin-1') if isinstance(payload, str) else payload
        if endpoint == 'omote-probe': return 'OMOTE-SEC2-OK-V1'
        if endpoint == 'omote-tx2-open':
            self.ha, self.nonce = b[1:66], b[66:98]
            self.context = {'version': 2, 'session_id': 17, 'epoch': 1,
                'tx_id': (b't'*16).hex(), 'device_id': sha256(self.pub).digest()[:8].hex(),
                'ha_public_sec1_hex': self.ha.hex(), 'device_public_sec1_hex': self.pub.hex(),
                'ha_nonce_hex': self.nonce.hex(), 'device_challenge_hex': (b'c'*32).hex()}
            reply = b'\x02' + (17).to_bytes(4,'big') + (1).to_bytes(4,'big') + b't'*16 + b'\x08' + sha256(self.pub).digest()[:8] + self.pub + b'c'*32
        elif endpoint == 'omote-tx2-commit':
            context = proof.canonical_context(self.context)
            ha_sig = b[2:]
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), self.ha).verify(ha_sig, proof.HA_DOMAIN + context, ec.ECDSA(hashes.SHA256()))
            ds = self.key.sign(proof.DEVICE_DOMAIN + context, ec.ECDSA(hashes.SHA256()))
            self.digest = sha256(proof.DIGEST_DOMAIN + context + bytes([len(ha_sig)]) + ha_sig + bytes([len(ds)]) + ds).digest()
            reply = b'\x02' + bytes([len(ds)]) + ds + self.digest
            if self.corrupt: reply = reply[:-1] + bytes([reply[-1] ^ 1])
        elif endpoint == 'omote-tx2-review':
            if self.reject: raise ValueError('rejected')
            assert b == b'\x02' + self.digest
            reply = b'\x02\x01' + self.digest
        elif endpoint == 'omote-tx2-touch-receipt':
            assert b[:33] == b'\x02' + self.digest
            msg = txmod.TOUCH_RECEIPT_DOMAIN + b'\x02' + (17).to_bytes(4,'big') + self.digest + b[33:] + b'\x01'
            sig = self.key.sign(msg, ec.ECDSA(hashes.SHA256()))
            if self.bad_receipt:
                sig = sig[:-1] + bytes([sig[-1] ^ 1])
            reply = b'\x02\x01' + bytes([len(sig)]) + sig
        else: raise AssertionError(endpoint)
        return reply.decode('latin-1')
    async def aclose(self): self.closed = True


class HacsV2LabTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = identity.CandidateIdentityStore(FakeHAStore())
        await self.store.async_load()
        self.fingerprint = (await self.store.async_prepare('remote'))['fingerprint']
        self.transports = []
    async def run_lab(self, **options):
        def factory(address):
            t = MockTransport(address)
            for k,v in options.items(): setattr(t,k,v)
            self.transports.append(t)
            return t
        return await lab.run_tx2_lab_session(host='10.0.10.121', pin='123456', entry_id='remote', identities=self.store, security_factory=MockSecurity, transport_factory=factory, ack_lab_only=True)
    async def test_persistent_candidate_and_signed_touch_without_trust(self):
        result = await self.run_lab()
        self.assertEqual(result['candidate_ha_fingerprint'], self.fingerprint)
        self.assertTrue(result['touch_receipt_verified'])
        self.assertFalse(result['paired'])
        self.assertFalse(result['deployment_enabled'])
        self.assertTrue(self.transports[-1].closed)
        self.assertIn('omote-tx2-touch-receipt', self.transports[-1].calls)
    async def test_legacy_patch_fails_before_srp(self):
        with self.assertRaises(lab.LabSessionError) as error: await self.run_lab(patch=0)
        self.assertEqual(error.exception.stage, 'version')
        self.assertEqual(self.transports[-1].calls, ['proto-ver'])
        self.assertTrue(self.transports[-1].closed)
    async def test_corrupt_transcript_cannot_reach_review(self):
        with self.assertRaises(lab.LabSessionError) as error: await self.run_lab(corrupt=True)
        self.assertEqual(error.exception.stage, 'transaction-commit')
        self.assertNotIn('omote-tx2-review', self.transports[-1].calls)
    async def test_rejection_cannot_issue_receipt(self):
        with self.assertRaises(lab.LabSessionError) as error: await self.run_lab(reject=True)
        self.assertEqual(error.exception.stage, 'touch-review')
        self.assertNotIn('omote-tx2-touch-receipt', self.transports[-1].calls)
    async def test_invalid_touch_signature_cannot_report_success(self):
        with self.assertRaises(lab.LabSessionError) as error:
            await self.run_lab(bad_receipt=True)
        self.assertEqual(error.exception.stage, 'touch-receipt')
        self.assertTrue(self.transports[-1].closed)
