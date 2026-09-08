"""Deactivate the pre-identity shared Langflow user, once.

Run inside the Langflow pod by "make langflow-retire-shared-user"
(kubectl exec -i ... python - < this file). Before platform identity,
every browser was the one auto-login superuser "langflow"; its refresh
cookies stay valid for seven days and would keep minting tokens for that
account. Deactivating it ends those sessions and keeps its flows and
variables in the database for recovery: reactivate it as the
break-glass superuser (PATCH /api/v1/users/{id} {"is_active": true}),
reset its password, sign in, export.

Idempotent: nothing to do when the user is missing or already inactive.
Talks to Langflow on localhost with the superuser credentials the pod
already holds in its environment; never prints them.
"""

import json
import os
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:7860/api/v1"
SHARED = "langflow"


def call(method, path, token=None, data=None, form=None):
    body = None
    headers = {}
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        BASE + path, data=body, method=method, headers=headers
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> int:
    username = os.environ["LANGFLOW_SUPERUSER"]
    password = os.environ["LANGFLOW_SUPERUSER_PASSWORD"]
    token = call(
        "POST", "/login", form={"username": username, "password": password}
    )["access_token"]
    # {"total_count": N, "users": [...]}, paged.
    shared, skip = None, 0
    while shared is None:
        page = call("GET", f"/users/?skip={skip}&limit=100", token)
        shared = next(
            (u for u in page["users"] if u["username"] == SHARED), None
        )
        skip += 100
        if skip >= page["total_count"]:
            break
    if shared is None:
        print(f"no user named {SHARED!r}: nothing to retire")
        return 0
    if not shared["is_active"]:
        print(f"{SHARED!r} is already inactive")
        return 0
    call("PATCH", f"/users/{shared['id']}", token, data={"is_active": False})
    print(f"deactivated {SHARED!r}; its flows and variables are kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
