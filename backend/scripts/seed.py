from app.comparison import compare_observations
from app.config import get_settings
from app.fixtures import CURRENT_OBSERVATIONS, PRODUCTION, REFERENCE_OBSERVATIONS
from app.repository import ClickHouseRepository

repo = ClickHouseRepository(get_settings())
conflicts = compare_observations(REFERENCE_OBSERVATIONS, CURRENT_OBSERVATIONS)
repo.seed_demo(PRODUCTION.model_dump(), REFERENCE_OBSERVATIONS + CURRENT_OBSERVATIONS, conflicts)
print(f"Seeded {len(REFERENCE_OBSERVATIONS) + len(CURRENT_OBSERVATIONS)} observations and {len(conflicts)} conflicts")
