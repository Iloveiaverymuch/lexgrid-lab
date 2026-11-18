import shutil
from pathlib import Path

import pytest

from lexgrid.pipeline import IntegrityError, ingest
from lexgrid.registry import pin_fixture
from lexgrid.store import LineageStore
from tests.conftest import SAMPLES, make_source


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, LineageStore]:
    root = tmp_path / "data" / "fixtures"
    for lang in ("en", "fr"):
        f = tmp_path / f"in_{lang}.html"
        shutil.copy(SAMPLES / f"eurlex_{lang}.html", f)
        pin_fixture(source=make_source(), fixtures_root=root, file=f, language=lang)
    return root, LineageStore.from_url(f"sqlite:///{tmp_path / 'db.sqlite'}")


def test_first_run_ingests_and_rerun_is_noop(setup: tuple[Path, LineageStore]) -> None:
    root, store = setup
    first = ingest([make_source()], root, store)[0]
    assert first.files == 2 and first.new_versions == 2 and first.new_chunks == first.chunks > 0
    before = store.counts()
    second = ingest([make_source()], root, store)[0]
    assert second.new_versions == 0 and second.new_chunks == 0
    assert store.counts() == before


def test_dry_run_has_no_side_effects(setup: tuple[Path, LineageStore]) -> None:
    root, store = setup
    rep = ingest([make_source()], root, store, dry_run=True)[0]
    assert rep.chunks > 0
    assert store.counts() == {"sources": 0, "documents": 0, "doc_versions": 0, "chunks": 0}


def test_changed_content_creates_new_version_and_tombstones_old(
    setup: tuple[Path, LineageStore], tmp_path: Path
) -> None:
    root, store = setup
    ingest([make_source()], root, store)
    live_before = {c["id"] for c in store.live_chunks()}

    changed = tmp_path / "changed.html"
    changed.write_bytes(
        (SAMPLES / "eurlex_en.html").read_bytes().replace(b"natural persons", b"natural people")
    )
    pin_fixture(source=make_source(), fixtures_root=root, file=changed, language="en")
    rep = ingest([make_source()], root, store)[0]
    assert rep.new_versions == 1

    live_after = {c["id"] for c in store.live_chunks()}
    assert live_after != live_before
    assert all(store.lineage(cid) is not None for cid in live_after)
    old_only = live_before - live_after
    assert old_only and all(store.lineage(cid)["superseded_by"] for cid in old_only)  # type: ignore[index]


def test_lineage_traces_chunk_to_raw_file(setup: tuple[Path, LineageStore]) -> None:
    root, store = setup
    ingest([make_source()], root, store)
    chunk = store.live_chunks("EU")[0]
    lin = store.lineage(chunk["id"])
    assert lin is not None
    assert lin["raw_uri"].startswith("fixtures/eu-gdpr/")
    assert len(lin["content_sha256"]) == 64
    assert lin["parser_name"] == "eurlex_html" and lin["parser_version"]
    assert lin["source_url"].startswith("https://")


def test_tampered_fixture_is_refused(setup: tuple[Path, LineageStore]) -> None:
    root, store = setup
    (root / "eu-gdpr" / "en.html").write_bytes(b"<html>tampered</html>")
    with pytest.raises(IntegrityError):
        ingest([make_source()], root, store)
