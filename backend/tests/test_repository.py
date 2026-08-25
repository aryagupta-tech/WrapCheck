from app.config import Settings
from app.fixtures import PRODUCTION
from app.repository import ClickHouseRepository


class FakeClient:
    def __init__(self): self.inserts = []
    def insert(self, *args, **kwargs): self.inserts.append((args, kwargs))
    def ping(self): return True


def test_clickhouse_repository_layer_accepts_seed():
    repository = ClickHouseRepository(Settings())
    repository._client = FakeClient()
    repository.seed_demo(PRODUCTION.model_dump(), [], [])
    assert repository.ping()
    assert repository._client.inserts[0][0][0] == "productions"
