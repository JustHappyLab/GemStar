"""Artifact store: read/write typed artifacts to the artifacts/ directory.

CALLING SPEC:
    write_artifact(run_id, name, data, base_dir="artifacts") -> str
        Writes data as JSON to artifacts/<date>/<run_id>/name.json and emits
        a sidecar name.json.manifest with sha256.  Returns the written URI.

    read_artifact(uri, base_dir="artifacts") -> dict
        Reads and returns the JSON content at the given URI.

    compute_sha256(data: bytes) -> str
        Returns hex SHA-256 of the given bytes.

SIDE EFFECTS:
    Creates directories and writes files under `artifacts/`.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from src.schemas.manifest import ArtifactManifestV1, ArtifactEntry


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_artifact(
    run_id: str,
    name: str,
    data: dict,
    base_dir: str | Path = "artifacts",
    step_id: str = "",
    inputs: list[dict] | None = None,
) -> str:
    """Write an artifact JSON file + sidecar manifest.  Returns URI string."""
    base = Path(base_dir)
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    path = run_dir / f"{name}.json"
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode()
    path.write_bytes(content)

    manifest = ArtifactManifestV1(
        run_id=run_id,
        step_id=step_id or name,
        created_at=datetime.now(),
        inputs=[ArtifactEntry(**i) for i in (inputs or [])],
        outputs=[ArtifactEntry(
            uri=str(path),
            sha256=compute_sha256(content),
        )],
        status="success",
    )
    manifest_path = run_dir / f"{name}.manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2))

    return str(path)


def read_artifact(uri: str, base_dir: str | Path = "artifacts") -> dict:
    """Read an artifact JSON file from the store."""
    path = Path(uri)
    if not path.is_absolute():
        path = Path(base_dir) / uri
    return json.loads(path.read_text())
