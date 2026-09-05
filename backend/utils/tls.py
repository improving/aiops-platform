"""TLS trust for calls to public hosts.

``make backend`` points ``SSL_CERT_FILE`` at the local development CA so
the process can reach the gateway hosts; httpx honours that variable,
which would make every public host (api.openai.com, huggingface.co)
fail verification. Public calls pass ``verify=public_ca_bundle()``
(certifi's roots) instead.
"""

import certifi


def public_ca_bundle() -> str:
    return certifi.where()
