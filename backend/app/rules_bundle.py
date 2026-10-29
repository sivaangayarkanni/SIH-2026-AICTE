"""Signed rule bundles. Rules are YAML; a detached Ed25519 signature proves they were not altered.
The engine refuses to run with an unsigned or tampered bundle."""
import base64, hashlib
from pathlib import Path
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature
from .config import RULES_DIR, KEYS_DIR

BUNDLE = RULES_DIR / "aicte_rules.yaml"
SIG = RULES_DIR / "aicte_rules.yaml.sig"
PUB = RULES_DIR / "rules_signing.pub"
PRIV = KEYS_DIR / "rules_signing.key"   # private key lives only in data/keys (never shipped)


def ensure_keys():
    if not PRIV.exists():
        k = Ed25519PrivateKey.generate()
        PRIV.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
        PUB.write_bytes(k.public_key().public_bytes(serialization.Encoding.PEM,
                                                    serialization.PublicFormat.SubjectPublicKeyInfo))


def sign_bundle(path: Path = BUNDLE, sig: Path = SIG):
    ensure_keys()
    k = serialization.load_pem_private_key(PRIV.read_bytes(), None)
    PUB.write_bytes(k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    sig.write_text(base64.b64encode(k.sign(path.read_bytes())).decode())


def verify_bundle(path: Path = BUNDLE, sig: Path = SIG, pub: Path = PUB) -> dict:
    data = path.read_bytes()
    info = {"bundle": path.name, "sha256": hashlib.sha256(data).hexdigest(), "algorithm": "Ed25519"}
    if not sig.exists() or not pub.exists():
        return {**info, "valid": False, "reason": "signature or public key missing"}
    try:
        k: Ed25519PublicKey = serialization.load_pem_public_key(pub.read_bytes())
        k.verify(base64.b64decode(sig.read_text()), data)
        return {**info, "valid": True}
    except (InvalidSignature, ValueError):
        return {**info, "valid": False, "reason": "signature does not match bundle contents"}


class RuleBundleError(Exception):
    pass


def load_rules(path: Path = BUNDLE, sig: Path = SIG, pub: Path = PUB) -> dict:
    v = verify_bundle(path, sig, pub)
    if not v["valid"]:
        raise RuleBundleError(v["reason"])
    rules = yaml.safe_load(path.read_text())
    rules["_verification"] = v
    return rules
