import os
import uuid

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"


def _mock_uuid4_generator():
    _uuid_counter = 0

    def _mock_uuid4() -> uuid.UUID:
        nonlocal _uuid_counter
        _uuid_counter += 1
        seed = 20240101
        bytes = seed.to_bytes(12, byteorder="big") + _uuid_counter.to_bytes(
            4, byteorder="big"
        )
        return uuid.UUID(bytes=bytes, version=4)

    return _mock_uuid4


uuid4 = _mock_uuid4_generator() if TEST_MODE else uuid.uuid4


def uuid4_gen(tag=None):
    if TEST_MODE:
        return _mock_uuid4_generator()
    return uuid.uuid4
