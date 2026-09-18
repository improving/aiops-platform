"""The model cache as the backend sees it (utils/model_cache.py): how much of
a Hugging Face model is on the shared cache volume, read from file sizes."""

from utils.kubernetes_utils import LaunchProgress
from utils.model_cache import downloaded_bytes, with_download

REFERENCE = "Qwen/Qwen2.5-14B-Instruct-AWQ"
GB = 10**9


def _blobs(root, sizes):
    blobs = root / "models--Qwen--Qwen2.5-14B-Instruct-AWQ" / "blobs"
    blobs.mkdir(parents=True)
    for name, size in sizes.items():
        with open(blobs / name, "wb") as f:
            f.truncate(size)  # sparse: a size, no data
    return blobs


def _starting():
    return LaunchProgress(
        phase="Starting",
        message="The container runs and is not ready yet",
        since="2026-09-18T14:41:59+00:00",
    )


def test_downloaded_bytes_counts_complete_and_partial_files(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path))
    _blobs(
        tmp_path,
        {
            "25b97bf2": 2 * GB,
            # What the hub library writes while a file downloads.
            "4e874dc3.0f6b9ad5.incomplete": 3 * GB,
            "443909a6": 7_000_000,
        },
    )
    assert downloaded_bytes(REFERENCE) == 5 * GB + 7_000_000


def test_downloaded_bytes_is_none_when_it_cannot_tell(tmp_path, monkeypatch):
    # No mount (the default): the launch line stays as it was.
    monkeypatch.delenv("MODEL_CACHE_DIR", raising=False)
    assert downloaded_bytes(REFERENCE) is None
    # A mount, and nothing of this model yet: that is zero, not unknown.
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path))
    assert downloaded_bytes(REFERENCE) == 0
    # Not a Hugging Face id (an Ollama tag), or no reference at all.
    assert downloaded_bytes("qwen3:0.6b") is None
    assert downloaded_bytes(None) is None


def test_downloaded_bytes_also_reads_the_hub_subdirectory(
    tmp_path, monkeypatch
):
    # HF_HOME points at the volume for some engines: <volume>/hub/models--...
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path))
    _blobs(tmp_path / "hub", {"abc": GB})
    assert downloaded_bytes(REFERENCE) == GB


def test_a_starting_instance_says_how_far_the_download_is(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path))
    _blobs(tmp_path, {"a.x.incomplete": 8 * GB})
    launch = with_download(_starting(), REFERENCE, 10 * GB)
    assert launch.downloaded_bytes == 8 * GB
    assert launch.total_bytes == 10 * GB
    assert launch.message == "Downloading the model: 8.0 of 10.0 GB"


def test_a_complete_download_means_the_model_is_loading(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path))
    # Tokenizer and config files make the cache a little larger than the
    # weights the registry counts.
    _blobs(tmp_path, {"a": 10 * GB, "tokenizer": 7_000_000})
    launch = with_download(_starting(), REFERENCE, 10 * GB)
    assert launch.downloaded_bytes == launch.total_bytes == 10 * GB
    assert launch.message == (
        "The model is downloaded: loading it into GPU memory and compiling"
    )


def test_download_without_a_known_size_gives_the_bytes_alone(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path))
    _blobs(tmp_path, {"a.x.incomplete": 3 * GB})
    launch = with_download(_starting(), REFERENCE, None)
    assert (launch.downloaded_bytes, launch.total_bytes) == (3 * GB, None)
    assert launch.message == "Downloading the model: 3.0 GB so far"


def test_other_phases_and_unknown_progress_are_left_alone(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path))
    pulling = LaunchProgress(phase="Pulling image", message="m", since=None)
    assert with_download(pulling, REFERENCE, GB) is pulling
    assert with_download(None, REFERENCE, GB) is None
    monkeypatch.delenv("MODEL_CACHE_DIR")
    starting = _starting()
    assert with_download(starting, REFERENCE, GB) is starting


def test_partial_files_of_a_killed_attempt_do_not_count_twice(
    tmp_path, monkeypatch
):
    # Seen on the lab: a download that is killed leaves its ".incomplete"
    # file behind, and the next attempt starts a new one for the same blob
    # (the hub library does not resume). The sum of all of them would pass
    # the model's size and say "downloaded" while the download still runs.
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path))
    _blobs(
        tmp_path,
        {
            "aaaa.11111111.incomplete": 3 * GB,  # killed attempt
            "aaaa.22222222.incomplete": 4 * GB,  # killed attempt
            "aaaa.33333333.incomplete": 1 * GB,  # the one that runs now
            "bbbb": 2 * GB,  # complete
            "bbbb.44444444.incomplete": 1 * GB,  # leftover of a done blob
        },
    )
    # aaaa: its largest partial file; bbbb: the complete file alone.
    assert downloaded_bytes(REFERENCE) == 4 * GB + 2 * GB
    launch = with_download(_starting(), REFERENCE, 10 * GB)
    assert launch.message == "Downloading the model: 6.0 of 10.0 GB"
