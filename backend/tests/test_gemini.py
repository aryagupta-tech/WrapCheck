from app.fixtures import REFERENCE_OBSERVATIONS
from app.services.gemini import parse_gemini_response


def test_structured_gemini_response_parsing():
    payload = '{"observations":[' + REFERENCE_OBSERVATIONS[0].model_dump_json() + "]}"
    parsed = parse_gemini_response(payload)
    assert parsed.observations[0].entity_name == "Mara's watch"
