"""Password hashing service using Argon2id."""

from passlib.context import CryptContext

from echoroo.core.settings import get_settings

settings = get_settings()

# Configure Argon2id with OWASP recommended parameters
pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__memory_cost=settings.ARGON2_MEMORY_COST,  # 19 MiB
    argon2__time_cost=settings.ARGON2_TIME_COST,  # 2 iterations
    argon2__parallelism=settings.ARGON2_PARALLELISM,  # 1 thread
)


def hash_password(password: str) -> str:
    """Hash a password using Argon2id.

    Args:
        password: Plain text password to hash

    Returns:
        Hashed password string

    Example:
        ```python
        hashed = hash_password("secure_password_123")
        # Returns: $argon2id$v=19$m=19456,t=2,p=1$...
        ```
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to compare against

    Returns:
        True if password matches, False otherwise

    Example:
        ```python
        is_valid = verify_password("user_input", stored_hash)
        if not is_valid:
            raise ValueError("Invalid password")
        ```
    """
    return pwd_context.verify(plain_password, hashed_password)
