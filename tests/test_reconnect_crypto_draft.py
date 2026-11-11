"""Offline cryptographic checks; not a firmware interoperability test."""
import importlib.util
from hashlib import sha256
from pathlib import Path
import unittest
from cryptography.hazmat.primitives.asymmetric import ec

p = Path(__file__).resolve().parents[1] / 'custom_components/omote_manager/reconnect_crypto_draft.py'
spec = importlib.util.spec_from_file_location('reconnect_crypto_draft', p)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

class ReconnectTests(unittest.TestCase):
    def setUp(self):
        self.ha = ec.generate_private_key(ec.SECP256R1())
        self.dev = ec.generate_private_key(ec.SECP256R1())
        self.eh = ec.generate_private_key(ec.SECP256R1())
        self.ed = ec.generate_private_key(ec.SECP256R1())
        self.fields = dict(ha_static=r.public_bytes(self.ha.public_key()), device_static=r.public_bytes(self.dev.public_key()), ha_ephemeral=r.public_bytes(self.eh.public_key()), device_ephemeral=r.public_bytes(self.ed.public_key()), ha_challenge=b'a'*32, device_challenge=b'b'*32)
        ctx = r.transcript(**self.fields)
        self.proofs = dict(ha_signature=r.sign(self.ha, 'ha', ctx), device_signature=r.sign(self.dev, 'device', ctx), pinned_ha_sha256=sha256(self.fields['ha_static']).digest(), pinned_device_sha256=sha256(self.fields['device_static']).digest())
    def test_both_sides_derive_matching_opposite_direction_keys(self):
        h = r.derive(role='ha', own_ephemeral=self.eh, **self.fields, **self.proofs)
        d = r.derive(role='device', own_ephemeral=self.ed, **self.fields, **self.proofs)
        self.assertEqual(h, (d[1], d[0]))
        self.assertNotEqual(h[0], h[1])
    def test_changed_challenge_and_wrong_pin_rejected(self):
        for update in ({'device_challenge':b'c'*32}, {'device_static':r.public_bytes(ec.generate_private_key(ec.SECP256R1()).public_key())}):
            with self.assertRaises(r.ReconnectRejected):
                r.derive(role='ha', own_ephemeral=self.eh, **{**self.fields, **update}, **self.proofs)
    def test_role_reflection_and_wrong_ephemeral_rejected(self):
        with self.assertRaises(r.ReconnectRejected):
            r.derive(role='ha', own_ephemeral=self.ed, **self.fields, **self.proofs)
        with self.assertRaises(r.ReconnectRejected):
            r.derive(role='ha', own_ephemeral=self.eh, **self.fields, **{**self.proofs, 'device_signature':self.proofs['ha_signature']})
    def test_reflected_challenge_rejected(self):
        with self.assertRaises(r.ReconnectRejected):
            r.transcript(**{**self.fields, 'device_challenge':self.fields['ha_challenge']})
