"""Tests for artifact store read/write and manifest sidecar."""

import json
import tempfile
from pathlib import Path

from src.orchestrator.artifact_store import compute_sha256, read_artifact, write_artifact


def test_write_and_read():
    with tempfile.TemporaryDirectory() as tmpdir:
        uri = write_artifact("run_001", "metrics", {"sharpe": 1.2}, base_dir=tmpdir)
        assert "run_001" in uri
        assert uri.endswith("metrics.json")
        data = read_artifact(uri)
        assert data["sharpe"] == 1.2


def test_manifest_sidecar_written():
    with tempfile.TemporaryDirectory() as tmpdir:
        write_artifact("run_001", "verdict", {"verdict": "candidate"}, base_dir=tmpdir)
        manifest_path = Path(tmpdir) / "run_001" / "verdict.manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["version"] == "ArtifactManifestV1"
        assert len(manifest["outputs"]) == 1
        assert len(manifest["outputs"][0]["sha256"]) == 64


def test_sha256_deterministic():
    h1 = compute_sha256(b"hello")
    h2 = compute_sha256(b"hello")
    assert h1 == h2
    assert len(h1) == 64


def test_artifact_sha256_matches_content():
    with tempfile.TemporaryDirectory() as tmpdir:
        data = {"key": "value"}
        write_artifact("run_001", "test", data, base_dir=tmpdir)
        content = (Path(tmpdir) / "run_001" / "test.json").read_bytes()
        manifest = json.loads((Path(tmpdir) / "run_001" / "test.manifest.json").read_text())
        assert manifest["outputs"][0]["sha256"] == compute_sha256(content)
