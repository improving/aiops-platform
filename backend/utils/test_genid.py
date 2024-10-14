from utils import genid


def test_genid(snapshot):
    uuid4 = genid.uuid4_gen()
    ids = []
    for _ in range(10):
        ids.append(str(uuid4()))
    snapshot.assert_match(str(ids), "uuids")
