"""Auth error helpers shared by current_user.py and dev_users.py.

Split out so dev_users.py can raise ``unauthorized`` without importing
current_user.py, which itself imports dev_users.py.
"""

from fastapi import HTTPException


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )
