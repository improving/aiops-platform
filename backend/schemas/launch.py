from typing import Literal

from pydantic import BaseModel, ConfigDict

LaunchPhase = Literal[
    "Scheduling",
    "Blocked",
    "Pulling image",
    "Restarting",
    "Starting",
    "Terminating",
]


class LaunchProgressSchema(BaseModel):
    """What an instance that is not ready yet is waiting for
    (utils.kubernetes_utils.LaunchProgress): derived on every read, never
    stored, and None once the instance is ready, stopped or failed."""

    model_config = ConfigDict(from_attributes=True)

    phase: LaunchPhase
    message: str
    since: str | None = None
    # Only a person can move it on: a pod no node can take, a container
    # that cannot be created, a restart loop. The UI styles by this, not by
    # the wording of ``message``.
    needs_attention: bool = False
    restart_count: int = 0
    replicas_total: int = 1
