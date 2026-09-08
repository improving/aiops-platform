#!/usr/bin/env python3
"""Derive the platform chart's realm files from the dev realm.

Reads infra/local/auth/realm-aiops.json and writes
charts/aiops-platform/files/realm-aiops.json (the realm with the parent
domain and the two client secrets as placeholders, and no people) and
charts/aiops-platform/files/realm-dev-users.json (admin, alice, bob for
keycloak.devUsers=true). Deterministic: re-run it after editing the dev
realm and commit both outputs.

Placeholders: __PARENT_DOMAIN__ is replaced by the chart template,
${KEYCLOAK_CLIENT_SECRET} and ${AUTOMATION_CLIENT_SECRET} by Keycloak at
import time from the pod environment.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "infra/local/auth/realm-aiops.json"
FILES = ROOT / "charts/aiops-platform/files"
DEV_DOMAIN = "127.0.0.1.nip.io"
PLACEHOLDER = "__PARENT_DOMAIN__"
DEV_USERS = ("admin", "alice", "bob")
DEV_SECRETS = ("dev-gateway-secret", "dev-automation-secret")


def main() -> None:
    realm = json.loads(SOURCE.read_text())
    users = realm.pop("users", [])
    people = [u for u in users if u.get("username") in DEV_USERS]
    # Service-account users (aiops-automation) stay with the realm.
    realm["users"] = [u for u in users if u.get("username") not in DEV_USERS]
    assert len(people) == len(DEV_USERS), [u.get("username") for u in users]

    clients = {c["clientId"]: c for c in realm["clients"]}
    clients["aiops-ui"]["redirectUris"] = [f"https://ui.{PLACEHOLDER}/*"]
    clients["aiops-gateway"]["redirectUris"] = [
        f"https://sso.{PLACEHOLDER}/oauth2/callback",
        # Langflow's own policy has a callback of its own (langflow.enabled).
        f"https://langflow.{PLACEHOLDER}/oauth2/callback",
    ]
    clients["aiops-gateway"]["secret"] = "${KEYCLOAK_CLIENT_SECRET}"
    clients["aiops-automation"]["secret"] = "${AUTOMATION_CLIENT_SECRET}"

    text = json.dumps(realm, indent=2).replace(DEV_DOMAIN, PLACEHOLDER) + "\n"
    assert DEV_DOMAIN not in text and "localhost" not in text, "a dev host survived"
    for secret in DEV_SECRETS:
        assert secret not in text, f"{secret} survived"
    FILES.mkdir(parents=True, exist_ok=True)
    (FILES / "realm-aiops.json").write_text(text)
    (FILES / "realm-dev-users.json").write_text(
        json.dumps(people, indent=2) + "\n"
    )
    print(f"wrote {FILES / 'realm-aiops.json'} and realm-dev-users.json")


if __name__ == "__main__":
    main()
