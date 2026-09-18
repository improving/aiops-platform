"""How much of a Hugging Face model is on the shared model cache volume.

The engines download a model into the claim ``hf-cache`` on their first
start. When the chart mounts that claim read-only into this pod
(``backend.hfCache.mount``, env ``MODEL_CACHE_DIR``), the sizes of a few
files say how far the download is: the hub library writes
``models--<org>--<name>/blobs/<sha>``, and ``<sha>.<id>.incomplete`` while a
file downloads. No exec into the engine's pod, no call to it, no new
permission; without the mount every answer is "unknown" and the launch line
stays as it is.
"""

import os
from pathlib import Path

from utils.kubernetes_utils import LAUNCH_STARTING, LaunchProgress

GB = 10**9


def _model_dirs(reference: str) -> list[Path]:
    root = os.environ.get("MODEL_CACHE_DIR")
    # A Hugging Face id is "<org>/<name>"; an Ollama tag ("qwen3:0.6b") or a
    # local path has no such directory.
    if not root or not reference or reference.count("/") != 1:
        return []
    if ":" in reference or reference.startswith((".", "/")):
        return []
    name = "models--" + reference.replace("/", "--")
    # The cache is the volume itself (HF_HUB_CACHE) or its "hub" directory
    # (HF_HOME), depending on the engine.
    return [Path(root) / name, Path(root) / "hub" / name]


def _blob_bytes(blobs: Path) -> int:
    """Bytes of the blobs in one directory. A blob counts once: its complete
    file, else its largest partial one. A killed download leaves its
    ``<sha>.<id>.incomplete`` behind and the next attempt starts another
    (the hub library does not resume), so the plain sum would pass the
    model's size while the download still runs. The largest partial file
    can itself be a dead one, which makes the amount optimistic, never
    more than the blob's size."""
    complete: dict[str, int] = {}
    partial: dict[str, int] = {}
    with os.scandir(blobs) as entries:
        for entry in entries:
            if not entry.is_file(follow_symlinks=False):
                continue
            size = entry.stat(follow_symlinks=False).st_size
            sha, _, rest = entry.name.partition(".")
            if rest.endswith("incomplete"):
                partial[sha] = max(partial.get(sha, 0), size)
            else:
                complete[sha] = size
    return sum(complete.values()) + sum(
        size for sha, size in partial.items() if sha not in complete
    )


def downloaded_bytes(reference: str | None) -> int | None:
    """Bytes of ``reference`` on the cache volume, complete and partial
    files alike; None when that cannot be told (no mount, not a Hugging Face
    id, an unreadable volume)."""
    dirs = _model_dirs(reference or "")
    if not dirs:
        return None
    total = 0
    try:
        for model_dir in dirs:
            blobs = model_dir / "blobs"
            if not blobs.is_dir():
                continue
            total += _blob_bytes(blobs)
    except OSError:
        return None
    return total


def _gb(value: int) -> str:
    return f"{value / GB:.1f}"


def with_download(
    launch: LaunchProgress | None, reference: str | None, size: int | None
) -> LaunchProgress | None:
    """``launch`` with the download progress of ``reference``, for an
    instance whose container runs and is not ready: that step is the
    download, then the load. ``size`` is the registry's byte count of the
    weights. Anything else comes back unchanged."""
    if launch is None or launch.phase != LAUNCH_STARTING:
        return launch
    done = downloaded_bytes(reference)
    if done is None:
        return launch
    if not size:
        return launch._replace(
            downloaded_bytes=done,
            message=f"Downloading the model: {_gb(done)} GB so far",
        )
    # The cache also holds the tokenizer and config files, so it ends a
    # little above the weights the registry counts.
    if done >= size:
        return launch._replace(
            downloaded_bytes=size,
            total_bytes=size,
            message=(
                "The model is downloaded: loading it into GPU memory "
                "and compiling"
            ),
        )
    return launch._replace(
        downloaded_bytes=done,
        total_bytes=size,
        message=f"Downloading the model: {_gb(done)} of {_gb(size)} GB",
    )
