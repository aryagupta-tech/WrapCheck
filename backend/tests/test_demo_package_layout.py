from pathlib import Path
from zipfile import ZipFile


PACKAGES = Path(__file__).parents[1] / "app" / "demo_packages"


def _file_names(variant: str):
    with ZipFile(PACKAGES / f"{variant}-delivery.zip") as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
    return members, [name.rsplit("/", 1)[-1] for name in members]


def test_problem_package_has_one_root_and_no_take_7_wav():
    members, names = _file_names("problem")
    assert all(name.startswith("problem-delivery/") for name in members)
    assert len(names) == len(set(names))
    assert "SR12_024B_T07.wav" not in names


def test_recovered_package_has_one_root_and_unique_complete_media():
    members, names = _file_names("recovered")
    assert all(name.startswith("recovered-delivery/") for name in members)
    assert len(names) == len(set(names))
    assert "SR12_024B_T07.wav" in names
