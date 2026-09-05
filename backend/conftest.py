"""Pytest defaults for the backend.

``TEST_MODE`` has to be set before ``utils.genid`` is imported (ids are
deterministic only then), and ``AUTH_MODE=disabled`` lets the tests call
the API without a token. ``hack/runtest.sh`` exports both as well; this
keeps single-test commands working.
"""

import os

os.environ.setdefault("TEST_MODE", "true")
os.environ.setdefault("AUTH_MODE", "disabled")
