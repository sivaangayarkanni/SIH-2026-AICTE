"""KMS adapters for envelope encryption.

KMS_BACKEND = soft (default) | aws | vault | pkcs11

Every backend does the same thing. A fresh 256-bit DEK encrypts the payload with AES-256-GCM.
The backend wraps the DEK under a key-encryption key that never leaves it. The blob stores
key_id (provider:key:version) so that rotation can re-wrap DEKs without touching the ciphertext.

* soft   - versioned local KEK files (data/keys/kms_kek_vN.key). DEV ONLY, not an HSM.
* aws    - AWS KMS Encrypt/Decrypt on the DEK (KMS_AWS_KEY_ID, region from AWS env). Tested with moto only.
* vault  - HashiCorp Vault Transit (VAULT_ADDR, VAULT_TOKEN, KMS_VAULT_KEY). Tested against a mock HTTP server only.
* pkcs11 - PKCS#11 HSM AES key wrap (PKCS11_LIB, PKCS11_TOKEN, PKCS11_PIN, PKCS11_KEY_LABEL).
           NOT TESTED: SoftHSM is not installable on the build box.
"""
from __future__ import annotations
import base64, os, time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class KMSUnavailable(RuntimeError):
    pass


def _retry(fn, attempts=3, base=0.2):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except KMSUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(base * (2 ** i))
    raise KMSUnavailable(f"KMS call failed after {attempts} attempts: {last}")


class BaseKMS:
    name = "base"
    key_id = ""

    def wrap(self, dek: bytes) -> tuple[bytes, str]:
        raise NotImplementedError

    def unwrap(self, wrapped: bytes, key_id: str) -> bytes:
        raise NotImplementedError

    def encrypt(self, plaintext: bytes, aad: bytes = b"") -> dict:
        dek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        ct = AESGCM(dek).encrypt(nonce, plaintext, aad)
        wrapped, kid = self.wrap(dek)
        return {"ciphertext": _b64(ct), "nonce": _b64(nonce), "wrapped_dek": _b64(wrapped), "key_id": kid}

    def decrypt(self, blob: dict, aad: bytes = b"") -> bytes:
        dek = self.unwrap(_unb64(blob["wrapped_dek"]), blob.get("key_id") or self.key_id)
        return AESGCM(dek).decrypt(_unb64(blob["nonce"]), _unb64(blob["ciphertext"]), aad)

    def rewrap(self, blob: dict) -> dict:
        """Re-wrap the DEK under the current key version. The ciphertext is unchanged."""
        dek = self.unwrap(_unb64(blob["wrapped_dek"]), blob.get("key_id") or self.key_id)
        wrapped, kid = self.wrap(dek)
        return {**blob, "wrapped_dek": _b64(wrapped), "key_id": kid}

    def rotate(self) -> str:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"backend": self.name, "key_id": self.key_id}


class SoftKMS(BaseKMS):
    """Versioned local KEKs. key_id = local-kek-vN (v1 keeps compatibility with earlier data)."""
    name = "soft"

    def __init__(self, key_dir: str | None = None):
        from .config import KEYS_DIR
        self.dir = key_dir or str(KEYS_DIR)
        os.makedirs(self.dir, exist_ok=True)
        cur = os.path.join(self.dir, "kms_current")
        self.version = int(open(cur).read().strip()) if os.path.exists(cur) else 1
        self._kek(self.version)

    @property
    def key_id(self):
        return f"local-kek-v{self.version}"

    def _kek(self, v: int) -> bytes:
        p = os.path.join(self.dir, f"kms_kek_v{v}.key")
        if not os.path.exists(p):
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, os.urandom(32)); os.close(fd)
        return open(p, "rb").read()

    def wrap(self, dek):
        kid = self.key_id
        n = os.urandom(12)
        return n + AESGCM(self._kek(self.version)).encrypt(n, dek, kid.encode()), kid

    def unwrap(self, wrapped, key_id):
        v = int(key_id.rsplit("-v", 1)[1])
        if not os.path.exists(os.path.join(self.dir, f"kms_kek_v{v}.key")):
            raise KMSUnavailable(f"unknown KEK version {key_id}")
        return AESGCM(self._kek(v)).decrypt(wrapped[:12], wrapped[12:], key_id.encode())

    def rotate(self):
        self.version += 1
        self._kek(self.version)
        with open(os.path.join(self.dir, "kms_current"), "w") as f:
            f.write(str(self.version))
        return self.key_id


class AwsKMS(BaseKMS):
    name = "aws"

    def __init__(self, key_id: str | None = None, client=None):
        import boto3
        from botocore.config import Config
        self.key_id = key_id or os.environ["KMS_AWS_KEY_ID"]
        self.c = client or boto3.client("kms", config=Config(connect_timeout=3, read_timeout=5,
                                                              retries={"max_attempts": 3, "mode": "standard"}))

    def wrap(self, dek):
        r = _retry(lambda: self.c.encrypt(KeyId=self.key_id, Plaintext=dek,
                                          EncryptionContext={"app": "sealcheck"}))
        return r["CiphertextBlob"], "aws:" + r["KeyId"]

    def unwrap(self, wrapped, key_id):
        r = _retry(lambda: self.c.decrypt(CiphertextBlob=wrapped, EncryptionContext={"app": "sealcheck"}))
        return r["Plaintext"]

    def rotate(self):
        # AWS rotates key material behind the same key ARN; old material stays available for decrypt.
        _retry(lambda: self.c.enable_key_rotation(KeyId=self.key_id))
        return self.key_id


class VaultTransitKMS(BaseKMS):
    name = "vault"

    def __init__(self, addr=None, token=None, key=None, timeout=5.0, client=None):
        import httpx
        self.addr = (addr or os.environ["VAULT_ADDR"]).rstrip("/")
        self.key = key or os.environ.get("KMS_VAULT_KEY", "sealcheck")
        self.key_id = f"vault:{self.key}"
        self.h = client or httpx.Client(timeout=timeout, headers={"X-Vault-Token": token or os.environ["VAULT_TOKEN"]})

    def _post(self, path, body):
        def call():
            r = self.h.post(f"{self.addr}/v1/transit/{path}/{self.key}", json=body)
            if r.status_code in (400, 403, 404):
                raise KMSUnavailable(f"vault {path}: {r.status_code} {r.text[:200]}")
            r.raise_for_status()
            return r.json()["data"]
        return _retry(call)

    def wrap(self, dek):
        d = self._post("encrypt", {"plaintext": base64.b64encode(dek).decode()})
        ct = d["ciphertext"]  # vault:vN:...
        return ct.encode(), f"vault:{self.key}:{ct.split(':')[1]}"

    def unwrap(self, wrapped, key_id):
        return base64.b64decode(self._post("decrypt", {"ciphertext": wrapped.decode()})["plaintext"])

    def rewrap(self, blob):
        d = self._post("rewrap", {"ciphertext": _unb64(blob["wrapped_dek"]).decode()})
        ct = d["ciphertext"]
        return {**blob, "wrapped_dek": _b64(ct.encode()), "key_id": f"vault:{self.key}:{ct.split(':')[1]}"}

    def rotate(self):
        def call():
            r = self.h.post(f"{self.addr}/v1/transit/keys/{self.key}/rotate"); r.raise_for_status()
        _retry(call)
        return self.key_id


class Pkcs11KMS(BaseKMS):
    """AES key wrap (CKM_AES_KEY_WRAP_PAD) inside an HSM. Not tested here because SoftHSM is unavailable."""
    name = "pkcs11"

    def __init__(self):
        import pkcs11
        self._p = pkcs11
        lib = pkcs11.lib(os.environ["PKCS11_LIB"])
        tok = lib.get_token(token_label=os.environ["PKCS11_TOKEN"])
        self.session = tok.open(user_pin=os.environ["PKCS11_PIN"], rw=True)
        self.label = os.environ.get("PKCS11_KEY_LABEL", "sealcheck-kek")
        self.key_id = f"pkcs11:{self.label}"

    def _key(self, label):
        return self.session.get_key(label=label, key_type=self._p.KeyType.AES)

    def wrap(self, dek):
        tmp = self.session.create_object({self._p.Attribute.CLASS: self._p.ObjectClass.SECRET_KEY,
                                          self._p.Attribute.KEY_TYPE: self._p.KeyType.AES,
                                          self._p.Attribute.VALUE: dek, self._p.Attribute.EXTRACTABLE: True,
                                          self._p.Attribute.TOKEN: False})
        return self._key(self.label).wrap_key(tmp, mechanism=self._p.Mechanism.AES_KEY_WRAP_PAD), self.key_id

    def unwrap(self, wrapped, key_id):
        k = self._key(key_id.split(":", 1)[1]).unwrap_key(self._p.ObjectClass.SECRET_KEY, self._p.KeyType.AES, wrapped,
                                                          mechanism=self._p.Mechanism.AES_KEY_WRAP_PAD,
                                                          template={self._p.Attribute.EXTRACTABLE: True,
                                                                    self._p.Attribute.SENSITIVE: False})
        return k[self._p.Attribute.VALUE]

    def rotate(self):
        raise KMSUnavailable("PKCS#11 rotation: generate a new key label in the HSM and set PKCS11_KEY_LABEL")


def get_kms() -> BaseKMS:
    b = os.environ.get("KMS_BACKEND", "soft").lower()
    return {"soft": SoftKMS, "aws": AwsKMS, "vault": VaultTransitKMS, "pkcs11": Pkcs11KMS}[b]()


def rewrap_all(session, km: BaseKMS | None = None, ids: list[int] | None = None) -> int:
    """Re-wrap every PII vault DEK under the KMS's current key. Returns the number of rows changed."""
    from .db import PiiVault
    km = km or get_kms()
    n = 0
    q = session.query(PiiVault)
    if ids is not None:
        q = q.filter(PiiVault.id.in_(ids))
    for row in q.all():
        blob = {"ciphertext": row.ciphertext, "nonce": row.nonce, "wrapped_dek": row.wrapped_dek, "key_id": row.key_id}
        nb = km.rewrap(blob)
        if nb["key_id"] != row.key_id or nb["wrapped_dek"] != row.wrapped_dek:
            row.wrapped_dek, row.key_id = nb["wrapped_dek"], nb["key_id"]
            n += 1
    session.commit()
    return n


if __name__ == "__main__":  # python -m app.kms rotate|rewrap|status
    import sys
    from .db import SessionLocal
    km = get_kms()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "rotate":
        print("new key:", km.rotate())
        with SessionLocal() as s:
            print("re-wrapped rows:", rewrap_all(s, km))
    elif cmd == "rewrap":
        with SessionLocal() as s:
            print("re-wrapped rows:", rewrap_all(s, km))
    else:
        print(km.describe())
