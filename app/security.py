import hashlib
import re
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{3,50}$")
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def validate_username(username: str) -> None:
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("用户名须为 3–50 位字母、数字、点、下划线或连字符。")


def validate_password(password: str) -> None:
    if len(password) < 14:
        raise ValueError("密码至少需要 14 个字符。")
    if len(password) > 256:
        raise ValueError("密码长度不能超过 256 个字符。")


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(encoded, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
