from passlib.context import CryptContext

# Workaround for passlib + bcrypt >= 4.1 compatibility
try:
    import bcrypt

    if not hasattr(bcrypt, "__about__"):
        bcrypt.__about__ = type("About", (), {"__version__": bcrypt.__version__})()
except Exception:  # pragma: no cover
    pass

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)
