import pytest
from fastapi import HTTPException

from app.delivery_models import AssetKind, UploadAssetDeclaration
from app.delivery_service import validate_declaration


def test_upload_role_rejects_a_false_mime_declaration():
    declaration = UploadAssetDeclaration(
        kind=AssetKind.camera_video,
        filename="A017_C001.mp4",
        content_type="application/pdf",
        size_bytes=1024,
    )
    with pytest.raises(HTTPException) as error:
        validate_declaration(declaration)
    assert error.value.status_code == 415


def test_upload_role_accepts_normalized_content_type_parameters():
    declaration = UploadAssetDeclaration(
        kind=AssetKind.camera_report,
        filename="camera_report.csv",
        content_type="text/csv; charset=utf-8",
        size_bytes=1024,
    )
    assert validate_declaration(declaration) == "camera_report.csv"
