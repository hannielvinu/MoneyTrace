"""
Authentication & Authorization utilities for MoneyTrace.
Provides JWT issuance, password verification, and FastAPI dependencies:
- get_current_user: returns user dict or raises 401
- require_operator: ensures role == 'FRAUD_OPERATOR' or raises 403
- optional_user: returns user dict or None
"""

import os
import time
import jwt
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, Depends, Header
from moneytrace.db.database import get_user_by_id, get_user_by_email, hash_password

JWT_SECRET = os.environ.get("JWT_SECRET", "moneytrace-super-secret-key-2026-secure")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_SECONDS = 86400 * 7  # 7 days


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": int(time.time()) + JWT_EXPIRATION_SECONDS
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except Exception:
        return None


def get_token_from_header(authorization: Optional[str] = Header(None)) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return parts[0] if len(parts) == 1 else None


async def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    token = get_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication token missing")
    
    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")
    
    user = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User account not found")
    
    return user


async def require_operator(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") != "FRAUD_OPERATOR":
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: This resource requires FRAUD_OPERATOR privileges"
        )
    return user


async def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[Dict[str, Any]]:
    token = get_token_from_header(authorization)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        return None
    return get_user_by_id(payload["sub"])
