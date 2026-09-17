"""用户个人 API Key 的对称加密（Fernet）。

密钥来自 settings.LLM_CREDENTIAL_KEY，与数据库分开保管：备份文件里只有密文，
拿到库而没有密钥无法还原 key。换密钥后旧密文解不开，让用户重新录入即可（不做
密钥轮换机制）。
"""
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class CryptoError(Exception):
    """密文损坏或密钥不匹配导致无法解密。"""


def _fernet() -> Fernet:
    return Fernet(settings.LLM_CREDENTIAL_KEY.encode("utf-8"))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise CryptoError("API Key 密文无法解密（密钥可能已更换），请重新填写") from exc


def mask_api_key(key: str) -> str:
    """脱敏串：保留前 3 后 4；太短不足以安全展示时只给固定掩码。"""
    key = key.strip()
    if len(key) >= 10:
        return f"{key[:3]}...{key[-4:]}"
    return "****"
