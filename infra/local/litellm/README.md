# LiteLLM on the local stack

`make litellm-up` installs the LiteLLM proxy (official Helm chart) in namespace `litellm`,
pointed at the compose Postgres on the host (database `litellm`, created by the target),
and publishes it through the gateway at `https://litellm.127.0.0.1.nip.io`.
The backend registers every deployed inference instance in it and routes chat, embeddings and rerank through it
(`backend/utils/litellm.py`, `backend/api/chat.py`).

Secrets in namespace `litellm`:

| Secret | Keys | Note |
| --- | --- | --- |
| `litellm-master` | `masterkey` | `sk-dev-litellm-master`, a dev-only literal like the Keycloak client secrets |
| `litellm-db` | `username`, `password` | the compose Postgres credentials |
| `litellm-env` | `LITELLM_SALT_KEY`, `STORE_MODEL_IN_DB`, `DISABLE_ADMIN_UI` | created once; the salt key must never change, or stored provider keys become unreadable |

Useful calls (the CA is `infra/local/ca/ca.crt`):

```bash
curl --cacert infra/local/ca/ca.crt https://litellm.127.0.0.1.nip.io/health/liveliness
curl --cacert infra/local/ca/ca.crt -H 'Authorization: Bearer sk-dev-litellm-master' https://litellm.127.0.0.1.nip.io/model/info
curl -L --cacert infra/local/ca/ca.crt -H 'Authorization: Bearer sk-dev-litellm-master' https://litellm.127.0.0.1.nip.io/metrics/
```

`make litellm-down` removes the release and the route; the database and the salt Secret stay.
