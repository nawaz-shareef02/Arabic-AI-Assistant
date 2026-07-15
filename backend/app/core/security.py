import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Any, Union
from jose import jwt
from app.core.config import settings

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def create_access_token(subject: Union[str, Any], expires_delta: timedelta = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


import re

COMMON_PASSWORDS = {
    "password", "password123", "12345678", "123456789", "qwertyuiop",
    "admin123", "welcome1", "letmein1", "login123", "change_me"
}

def validate_password_strength(password: str, email: str, full_name: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not any(c.isupper() for c in password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must contain at least one digit.")
    if not any(c in "!@#$%^&*(),.?\":{}|<>" for c in password):
        raise ValueError("Password must contain at least one special character.")
    if password.lower() in COMMON_PASSWORDS:
        raise ValueError("Password is too common or weak.")
    
    # Check if contains email
    email_local = email.split("@")[0].lower() if "@" in email else email.lower()
    if email_local and email_local in password.lower():
        raise ValueError("Password cannot contain parts of your email address.")
        
    # Check if contains full name
    name_parts = [p.lower() for p in full_name.split() if len(p) > 2]
    for part in name_parts:
        if part in password.lower():
            raise ValueError("Password cannot contain parts of your name.")