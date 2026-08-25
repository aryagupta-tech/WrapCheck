import json
from typing import Literal
from uuid import uuid4

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from ..config import Settings
from ..models import (
    GeminiObservationBatch, ObservationResult, RequirementObservation, SceneBrief,
)


SYSTEM_INSTRUCTION = """You are a film continuity observation system. Report only visible or audible evidence.
Never infer details that cannot be verified, including camera focal length. Use observed_value='unknown'
when evidence is insufficient. Produce independent timestamped observations for props, wardrobe,
screen position, movement direction, dialogue, and shot coverage. Do not decide whether differences are errors."""

REQUIREMENT_INSTRUCTION = """You inspect a short production take against a closed list of declared requirements.
Return exactly one evidence record per requirement_id. Do not create new requirements and do not decide whether
the setup can wrap. For continuity, report the visible normalized value. For required dialogue, use result
'observed' only when the required line is audibly present, 'not_observed' when the whole clip is inspectable and
the line is absent, and 'uncertain' when audio or visuals are insufficient. Timestamps are milliseconds. Missing
dialogue should use the full inspected clip range rather than an invented point timestamp."""


class GeminiRequirementEvidence(BaseModel):
    requirement_id: str
    result: Literal["observed", "not_observed", "uncertain"]
    normalized_value: str
    confidence: float = Field(ge=0, le=1)
    evidence_description: str
    timestamp_start_ms: int | None = Field(default=None, ge=0)
    timestamp_end_ms: int | None = Field(default=None, ge=0)


class GeminiRequirementBatch(BaseModel):
    observations: list[GeminiRequirementEvidence]


class GeminiAnalyzer:
    """Live Vertex AI analyzer. This class is never invoked in Demo Mode."""

    def __init__(self, settings: Settings):
        if not settings.live_ready:
            raise RuntimeError(
                "Live Mode needs GOOGLE_CLOUD_PROJECT and Application Default Credentials. "
                "Run `gcloud auth application-default login` and restart the backend."
            )
        self.settings = settings
        self.client = genai.Client(
            vertexai=True,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )

    def analyze_gcs_video(self, gcs_uri: str, context: dict[str, str]) -> list:
        response = self.client.models.generate_content(
            model=self.settings.gemini_model,
            contents=[
                types.Part.from_uri(file_uri=gcs_uri, mime_type="video/mp4"),
                json.dumps(context),
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=GeminiObservationBatch,
                temperature=0.1,
            ),
        )
        return parse_gemini_response(response.text).observations

    def analyze_requirements_gcs(
        self, gcs_uri: str, run_id: str, brief: SceneBrief, take_id: str,
    ) -> list[RequirementObservation]:
        declared = [item.model_dump(mode="json") for item in brief.requirements]
        response = self.client.models.generate_content(
            model=self.settings.gemini_model,
            contents=[
                types.Part.from_uri(file_uri=gcs_uri, mime_type="video/mp4"),
                json.dumps({
                    "production_id": brief.production_id, "scene_id": brief.scene_id,
                    "setup_id": brief.setup_id, "take_id": take_id,
                    "declared_requirements": declared,
                }),
            ],
            config=types.GenerateContentConfig(
                system_instruction=REQUIREMENT_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=GeminiRequirementBatch,
                temperature=0,
            ),
        )
        parsed = GeminiRequirementBatch.model_validate_json(response.text)
        expected_ids = {item.requirement_id for item in brief.requirements}
        returned_ids = {item.requirement_id for item in parsed.observations}
        if returned_ids != expected_ids or len(parsed.observations) != len(expected_ids):
            raise RuntimeError("Gemini did not return exactly one observation for each declared requirement.")
        return [
            RequirementObservation(
                observation_id=str(uuid4()), run_id=run_id, production_id=brief.production_id,
                scene_id=brief.scene_id, setup_id=brief.setup_id, take_id=take_id,
                requirement_id=item.requirement_id, result=ObservationResult(item.result),
                normalized_value=item.normalized_value, confidence=item.confidence,
                evidence_description=item.evidence_description,
                timestamp_start_ms=item.timestamp_start_ms, timestamp_end_ms=item.timestamp_end_ms,
                source="gemini",
            )
            for item in parsed.observations
        ]


def parse_gemini_response(text: str) -> GeminiObservationBatch:
    return GeminiObservationBatch.model_validate_json(text)
