"""Source registry (data/sources.yaml) and pinned fixture manifests."""

from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from lexgrid.models import DocType, Jurisdiction

SourceFormat = Literal["eurlex_html", "legifrance_html", "gii_xml"]
_ISO_DURATION = re.compile(r"^P(?:\d+[YMWD])+(?:T(?:\d+[HMS])+)?$")
FIXTURE_BUDGET_BYTES = 25 * 1024 * 1024


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    jurisdiction: Jurisdiction
    languages: list[str] = Field(min_length=1)
    act_short: str
    external_id: str
    title: str
    publisher: str
    license: str
    license_url: HttpUrl
    url: str
    format: SourceFormat
    parser: str
    refresh_cadence: str
    pii_risk: Literal["low", "medium", "high"]
    doc_type: DocType
    default_valid_from: date | None = None
    enabled: bool = True

    @field_validator("refresh_cadence")
    @classmethod
    def _iso_duration(cls, v: str) -> str:
        if not _ISO_DURATION.match(v):
            raise ValueError(f"refresh_cadence must be an ISO 8601 duration, got {v!r}")
        return v


class FixtureEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    language: str
    sha256: str
    bytes: int
    url: str
    fetched_at: datetime
    etag: str | None = None
    origin_sha256: str | None = Field(default=None, description="sha256 of the archive it came from")


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    files: list[FixtureEntry]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_registry(path: Path, known_parsers: set[str]) -> list[Source]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a list of sources")
    sources = [Source.model_validate(item) for item in raw]
    ids = [s.id for s in sources]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate source ids: {sorted(dupes)}")
    for s in sources:
        if s.parser not in known_parsers:
            raise ValueError(f"source {s.id}: unknown parser {s.parser!r}")
    return sources


def manifest_path(fixtures_root: Path, source_id: str) -> Path:
    return fixtures_root / source_id / "MANIFEST.json"


def load_manifest(fixtures_root: Path, source_id: str) -> Manifest:
    p = manifest_path(fixtures_root, source_id)
    if not p.exists():
        return Manifest(source_id=source_id, files=[])
    return Manifest.model_validate_json(p.read_text(encoding="utf-8"))


def save_manifest(fixtures_root: Path, manifest: Manifest) -> None:
    p = manifest_path(fixtures_root, manifest.source_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = manifest.model_dump(mode="json")
    data["files"].sort(key=lambda f: f["path"])
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check_fixtures(sources: list[Source], fixtures_root: Path, *, require_files: bool) -> list[str]:
    """Return a list of human-readable problems (empty list == healthy)."""
    errors: list[str] = []
    total = 0
    for s in sources:
        m = load_manifest(fixtures_root, s.id)
        listed = {f.path for f in m.files}
        src_dir = fixtures_root / s.id
        on_disk = (
            {p.name for p in src_dir.iterdir() if p.is_file() and p.name != "MANIFEST.json"}
            if src_dir.exists()
            else set()
        )
        if s.enabled and require_files and not m.files:
            errors.append(f"{s.id}: enabled but has no pinned fixture")
        for orphan in sorted(on_disk - listed):
            errors.append(f"{s.id}: file {orphan} is not in MANIFEST.json")
        for f in m.files:
            fp = src_dir / f.path
            if not fp.exists():
                errors.append(f"{s.id}: manifest lists missing file {f.path}")
                continue
            data = fp.read_bytes()
            total += len(data)
            if sha256_bytes(data) != f.sha256:
                errors.append(f"{s.id}: sha256 mismatch for {f.path}")
            if f.language not in s.languages:
                errors.append(f"{s.id}: {f.path} language {f.language} not declared on source")
    if total > FIXTURE_BUDGET_BYTES:
        errors.append(f"fixtures total {total} bytes exceeds budget {FIXTURE_BUDGET_BYTES}")
    return errors


@dataclass(frozen=True)
class Capture:
    data: bytes
    suffix: str
    url: str | None
    origin_sha256: str | None
    fetched_at: datetime | None = None


def extract_capture(file: Path) -> Capture:
    """Unwrap browser/archive containers into the raw document bytes.

    - .mhtml / .mht (browser "save as single file"): the text/html part, decoded, bytes as served.
    - .zip (gesetze-im-internet.de): the single XML member.
    - anything else: the file as is.
    """
    raw = file.read_bytes()
    suffix = file.suffix.lower()
    if suffix in {".mhtml", ".mht"}:
        msg = email.message_from_bytes(raw, policy=email.policy.compat32)
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if not isinstance(payload, bytes):
                    break
                url = msg.get("Snapshot-Content-Location") or part.get("Content-Location")
                saved = msg.get("Date")
                fetched = email.utils.parsedate_to_datetime(saved) if saved else None
                return Capture(payload, ".html", str(url) if url else None, sha256_bytes(raw), fetched)
        raise ValueError(f"{file}: no text/html part in MHTML")
    if suffix == ".zip":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            if len(xml_names) != 1:
                raise ValueError(f"{file}: expected exactly one XML member, got {xml_names}")
            return Capture(zf.read(xml_names[0]), ".xml", None, sha256_bytes(raw))
    return Capture(raw, suffix, None, None)


def pin_fixture(
    *,
    source: Source,
    fixtures_root: Path,
    file: Path,
    language: str,
    url: str | None = None,
) -> FixtureEntry:
    """Unwrap a downloaded file into fixtures and record its checksum. Content bytes are not re-encoded."""
    if language not in source.languages:
        raise ValueError(f"{source.id}: language {language} not declared")
    cap = extract_capture(file)
    data = cap.data
    target_name = f"{language}{cap.suffix}"
    target_dir = fixtures_root / source.id
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / target_name).write_bytes(data)
    entry = FixtureEntry(
        path=target_name,
        language=language,
        sha256=sha256_bytes(data),
        bytes=len(data),
        url=url or cap.url or source.url.format(lang=language.upper()),
        fetched_at=cap.fetched_at or datetime.fromtimestamp(file.stat().st_mtime, tz=UTC),
        origin_sha256=cap.origin_sha256,
    )
    m = load_manifest(fixtures_root, source.id)
    m.files = [f for f in m.files if f.path != target_name] + [entry]
    save_manifest(fixtures_root, m)
    return entry
