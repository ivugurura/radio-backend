from functools import lru_cache

from cryptography.fernet import Fernet
from django.conf import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = getattr(settings, "STREAMING_CREDENTIAL_KEY", "")
    if not key:
        raise RuntimeError(
            "STREAMING_CREDENTIAL_KEY is not set; generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())"`'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_secret(raw: str) -> str:
    return _fernet().encrypt(raw.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
