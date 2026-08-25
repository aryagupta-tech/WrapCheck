from pathlib import Path

from app.delivery_service import probe_media


ASSETS = Path(__file__).parents[1] / "app" / "demo_assets"


def test_ffprobe_reads_real_camera_metadata():
    metadata = probe_media(ASSETS / "A017_C003_0825Q7.mp4")
    assert metadata["codec"] == "h264"
    assert metadata["width"] == 1280
    assert metadata["height"] == 720
    assert metadata["frame_rate"] == "24/1"
    assert 7 <= metadata["duration_seconds"] <= 8


def test_ffprobe_reads_real_production_audio_metadata():
    metadata = probe_media(ASSETS / "SR12_024B_T07.wav")
    assert metadata["audio_codec"] == "pcm_s24le"
    assert metadata["sample_rate"] == 48000
    assert metadata["channels"] == 2
    assert metadata["bits_per_sample"] == 24
    assert 7 <= metadata["duration_seconds"] <= 8
