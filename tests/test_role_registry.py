"""Tests for RoleRegistry, RoleConfig, SkillContent, and RoleEvent."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.llm.providers.base import AgentResult
from src.roles.config import RoleConfig
from src.roles.events import RoleEvent
from src.roles.registry import RoleRegistry, SkillContent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_roles_dir(tmp_path: Path) -> Path:
    d = tmp_path / "roles"
    d.mkdir()
    return d


@pytest.fixture
def tmp_skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def sample_skill(tmp_skills_dir: Path) -> Path:
    skill_dir = tmp_skills_dir / "analyze_market"
    skill_dir.mkdir()
    (skill_dir / "sop.md").write_text("# analyze_market\n\nEvaluate market regime.")
    (skill_dir / "prompt.txt").write_text("You are a market analyst. Respond with JSON.")
    (skill_dir / "schema.json").write_text(
        json.dumps({"type": "object", "schema_ref": "src.schemas.signal.MarketRegimeV1", "format": "json"})
    )
    return skill_dir


@pytest.fixture
def sample_role(tmp_roles_dir: Path) -> Path:
    role_file = tmp_roles_dir / "macro_analyst.yaml"
    role_file.write_text(
        yaml.dump({
            "name": "macro_analyst",
            "description": "Market regime assessment",
            "provider": "api",
            "skills": ["analyze_market"],
            "approval": False,
            "timeout": 120,
        })
    )
    return role_file


# ---------------------------------------------------------------------------
# RoleConfig
# ---------------------------------------------------------------------------


class TestRoleConfig:
    def test_defaults(self):
        cfg = RoleConfig(name="test")
        assert cfg.provider == "api"
        assert cfg.skills == []
        assert cfg.approval is False
        assert cfg.timeout == 120

    def test_custom(self):
        cfg = RoleConfig(
            name="engineer",
            description="Code engineer",
            provider="claude_code",
            skills=["write_code", "fix_bug"],
            approval=True,
            timeout=600,
        )
        assert cfg.provider == "claude_code"
        assert len(cfg.skills) == 2
        assert cfg.approval is True


# ---------------------------------------------------------------------------
# SkillContent
# ---------------------------------------------------------------------------


class TestSkillContent:
    def test_loads_all_files(self, sample_skill: Path):
        sc = SkillContent("analyze_market", sample_skill)
        assert "market analyst" in sc.prompt.lower()
        assert "analyze_market" in sc.sop
        assert sc.schema_ref == "src.schemas.signal.MarketRegimeV1"

    def test_missing_files_handled(self, tmp_path: Path):
        empty_dir = tmp_path / "empty_skill"
        empty_dir.mkdir()
        sc = SkillContent("empty", empty_dir)
        assert sc.sop == ""
        assert sc.prompt == ""
        assert sc.schema_ref is None


# ---------------------------------------------------------------------------
# RoleRegistry — loading
# ---------------------------------------------------------------------------


class TestRoleRegistryLoading:
    def test_loads_roles(self, tmp_roles_dir, tmp_skills_dir, sample_role, sample_skill):
        reg = RoleRegistry(roles_dir=tmp_roles_dir, skills_dir=tmp_skills_dir)
        assert "macro_analyst" in reg.list_roles()

    def test_loads_skills(self, tmp_roles_dir, tmp_skills_dir, sample_role, sample_skill):
        reg = RoleRegistry(roles_dir=tmp_roles_dir, skills_dir=tmp_skills_dir)
        assert "analyze_market" in reg._skills

    def test_empty_dirs(self, tmp_path):
        roles_d = tmp_path / "roles"
        skills_d = tmp_path / "skills"
        roles_d.mkdir()
        skills_d.mkdir()
        reg = RoleRegistry(roles_dir=roles_d, skills_dir=skills_d)
        assert reg.list_roles() == []

    def test_get_role_raises_on_missing(self, tmp_path):
        roles_d = tmp_path / "roles"
        skills_d = tmp_path / "skills"
        roles_d.mkdir()
        skills_d.mkdir()
        reg = RoleRegistry(roles_dir=roles_d, skills_dir=skills_d)
        with pytest.raises(KeyError, match="Role not found"):
            reg.get_role("nonexistent")


# ---------------------------------------------------------------------------
# RoleRegistry — execute_role
# ---------------------------------------------------------------------------


class TestRoleRegistryExecute:
    def test_execute_calls_provider(self, tmp_roles_dir, tmp_skills_dir, sample_role, sample_skill):
        reg = RoleRegistry(roles_dir=tmp_roles_dir, skills_dir=tmp_skills_dir)

        mock_result = AgentResult(output='{"regime": "bullish"}', provider="api", duration_seconds=1.0)
        with patch.object(reg, "get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.execute.return_value = mock_result
            mock_get.return_value = mock_provider

            result = reg.execute_role("macro_analyst", {"task": "evaluate market"})

        assert result.output == '{"regime": "bullish"}'
        mock_provider.execute.assert_called_once()
        call_args = mock_provider.execute.call_args
        assert call_args[0][0] == "evaluate market"
        assert "system" in call_args[1]["context"]
        assert "market analyst" in call_args[1]["context"]["system"].lower()

    def test_execute_emits_events(self, tmp_roles_dir, tmp_skills_dir, sample_role, sample_skill):
        events = []
        reg = RoleRegistry(
            roles_dir=tmp_roles_dir,
            skills_dir=tmp_skills_dir,
            event_callback=lambda e: events.append(e),
        )

        mock_result = AgentResult(output="ok", provider="api", duration_seconds=0.5)
        with patch.object(reg, "get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.execute.return_value = mock_result
            mock_get.return_value = mock_provider

            reg.execute_role("macro_analyst", {"task": "test"})

        assert len(events) == 2
        assert events[0].event_type == "started"
        assert events[1].event_type == "completed"
        assert events[0].role_name == "macro_analyst"

    def test_execute_emits_failed_event(self, tmp_roles_dir, tmp_skills_dir, sample_role, sample_skill):
        events = []
        reg = RoleRegistry(
            roles_dir=tmp_roles_dir,
            skills_dir=tmp_skills_dir,
            event_callback=lambda e: events.append(e),
        )

        with patch.object(reg, "get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.execute.side_effect = RuntimeError("API down")
            mock_get.return_value = mock_provider

            with pytest.raises(RuntimeError, match="API down"):
                reg.execute_role("macro_analyst", {"task": "test"})

        assert len(events) == 2
        assert events[0].event_type == "started"
        assert events[1].event_type == "failed"

    def test_execute_unknown_provider_raises(self, tmp_roles_dir, tmp_skills_dir):
        role_file = tmp_roles_dir / "bad.yaml"
        role_file.write_text(yaml.dump({"name": "bad_role", "provider": "unknown_provider", "skills": []}))
        reg = RoleRegistry(roles_dir=tmp_roles_dir, skills_dir=tmp_skills_dir)

        with pytest.raises(ValueError, match="Unknown provider"):
            reg.execute_role("bad_role", {"task": "test"})


# ---------------------------------------------------------------------------
# RoleEvent
# ---------------------------------------------------------------------------


class TestRoleEvent:
    def test_creation(self):
        e = RoleEvent(
            role_name="macro_analyst",
            event_type="started",
            message="Starting...",
            timestamp=datetime.now(),
        )
        assert e.role_name == "macro_analyst"
        assert e.event_type == "started"
        assert e.artifact is None
