"""Request ids and the audit trail (spec section 5.3).

``middleware`` stamps ``X-Request-ID`` and records one ``AuditEvent``
per mutating ``/v1alpha1/*`` call; ``events`` holds ``record`` for the
explicit events a router writes itself (the credential reveal).
"""

from audit.events import record
