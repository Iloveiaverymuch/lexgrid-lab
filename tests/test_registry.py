import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from lexgrid.parsers import PARSERS
from lexgrid.registry import check_fixtures, load_registry, pin_fixture
from tests.conftest import SAMPLES, make_source

REPO = Path(__file__).resolve().parents[1]


def test_repo_registry_is_valid_and_covers_scope() -> None:
    sources = load_registry(REPO / "data" / "sources.yaml", set(PARSERS))
    enabled = [s for s in sources if s.enabled]
    assert {s.jurisdiction for s in enabled} >= {"EU", "FR", "DE"}
    assert len({lang for s in enabled for lang in s.languages}) >= 2
    assert len({s.format for s in enabled}) >= 3
    assert all(s.license for s in enabled)


def test_rejects_unknown_field(tmp_path: Path) -> None:
    src = make_source().model_dump(mode="json") | {"surprise": 1}
    (tmp_path / "s.yaml").write_text(yaml.safe_dump([src]))
    with pytest.raises(ValidationError):
        load_registry(tmp_path / "s.yaml", set(PARSERS))


def test_rejects_unknown_parser(tmp_path: Path) -> None:
    src = make_source().model_dump(mode="json") | {"parser": "nope"}
    (tmp_path / "s.yaml").write_text(yaml.safe_dump([src]))
    with pytest.raises(ValueError, match="unknown parser"):
        load_registry(tmp_path / "s.yaml", set(PARSERS))


def test_rejects_bad_cadence() -> None:
    with pytest.raises(ValidationError):
        make_source(refresh_cadence="weekly")


def test_pin_then_check_detects_tamper_and_orphans(tmp_path: Path) -> None:
    src = make_source()
    root = tmp_path / "fixtures"
    inbox = tmp_path / "inbox.html"
    shutil.copy(SAMPLES / "eurlex_en.html", inbox)
    entry = pin_fixture(source=src, fixtures_root=root, file=inbox, language="en")
    assert entry.path == "en.html"
    assert check_fixtures([src], root, require_files=True) == []

    (root / src.id / "en.html").write_bytes(b"tampered")
    (root / src.id / "stray.html").write_bytes(b"x")
    errors = check_fixtures([src], root, require_files=True)
    assert any("sha256 mismatch" in e for e in errors)
    assert any("stray.html" in e for e in errors)


def test_check_requires_fixtures_for_enabled_sources(tmp_path: Path) -> None:
    errors = check_fixtures([make_source()], tmp_path, require_files=True)
    assert errors == ["eu-gdpr: enabled but has no pinned fixture"]
