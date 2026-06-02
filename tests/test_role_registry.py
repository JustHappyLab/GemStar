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
            "provider": "claude_code",
            "skills": ["analyze_market"],
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
        assert cfg.provider == "claude_code"
        assert cfg.skills == []
        assert cfg.timeout == 120

    def test_custom(self):
        cfg = RoleConfig(
            name="engineer",
            description="Code engineer",
            provider="claude_code",
            skills=["write_code", "fix_bug"],
            timeout=600,
        )
        assert cfg.provider == "claude_code"
        assert len(cfg.skills) == 2
        assert cfg.timeout == 600

    def test_rejects_unknown_fields(self):
        with pytest.raises(Exception, match="approval"):
            RoleConfig(name="engineer", approval=True)


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

        mock_result = AgentResult(output='{"regime": "bullish"}', provider="claude_code", duration_seconds=1.0)
        with patch.object(reg, "get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.execute.return_value = mock_result
            mock_get.return_value = mock_provider

            result = reg.execute_role("macro_analyst", {"task": "evaluate market"})

        assert result.output == '{"regime": "bullish"}'
        mock_provider.execute.assert_called_once()
        mock_get.assert_called_once_with("claude_code", timeout=120)
        call_args = mock_provider.execute.call_args
        assert call_args[0][0] == "evaluate market"
        assert "system" in call_args[1]["context"]
        assert "market analyst" in call_args[1]["context"]["system"].lower()
        assert call_args[1]["context"]["json_schema"]["type"] == "object"
        assert "regime" in call_args[1]["context"]["json_schema"]["properties"]

    def test_execute_builds_array_schema_from_items_schema_ref(self, tmp_roles_dir, tmp_skills_dir):
        skill_dir = tmp_skills_dir / "generate_tickets"
        skill_dir.mkdir()
        (skill_dir / "prompt.txt").write_text("Return tickets.")
        (skill_dir / "schema.json").write_text(
            json.dumps({
                "type": "array",
                "items_schema_ref": "src.schemas.research.ResearchTicketV1",
                "format": "json",
            })
        )
        role_file = tmp_roles_dir / "research_analyst.yaml"
        role_file.write_text(
            yaml.dump({
                "name": "research_analyst",
                "provider": "claude_code",
                "skills": ["generate_tickets"],
                "timeout": 120,
            })
        )
        reg = RoleRegistry(roles_dir=tmp_roles_dir, skills_dir=tmp_skills_dir)

        mock_result = AgentResult(output="[]", provider="claude_code", duration_seconds=1.0)
        with patch.object(reg, "get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.execute.return_value = mock_result
            mock_get.return_value = mock_provider

            reg.execute_role("research_analyst", {"task": "generate"})

        schema = mock_provider.execute.call_args[1]["context"]["json_schema"]
        assert schema["type"] == "array"
        assert "ticket_id" in schema["items"]["properties"]

    def test_execute_appends_context_system_prompt(self, tmp_roles_dir, tmp_skills_dir, sample_role, sample_skill):
        reg = RoleRegistry(roles_dir=tmp_roles_dir, skills_dir=tmp_skills_dir)

        mock_result = AgentResult(output="{}", provider="claude_code", duration_seconds=1.0)
        with patch.object(reg, "get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.execute.return_value = mock_result
            mock_get.return_value = mock_provider

            reg.execute_role("macro_analyst", {"task": "evaluate market", "system": "Return a strict object."})

        system = mock_provider.execute.call_args[1]["context"]["system"]
        assert "market analyst" in system.lower()
        assert "Return a strict object." in system

    def test_execute_emits_events(self, tmp_roles_dir, tmp_skills_dir, sample_role, sample_skill):
        events = []
        reg = RoleRegistry(
            roles_dir=tmp_roles_dir,
            skills_dir=tmp_skills_dir,
            event_callback=lambda e: events.append(e),
        )

        mock_result = AgentResult(output="ok", provider="claude_code", duration_seconds=0.5)
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
            mock_provider.execute.side_effect = RuntimeError("provider down")
            mock_get.return_value = mock_provider

            with pytest.raises(RuntimeError, match="provider down"):
                reg.execute_role("macro_analyst", {"task": "test"})

        assert len(events) == 2
        assert events[0].event_type == "started"
        assert events[1].event_type == "failed"

    def test_load_unknown_provider_raises(self, tmp_roles_dir, tmp_skills_dir):
        role_file = tmp_roles_dir / "bad.yaml"
        role_file.write_text(yaml.dump({"name": "bad_role", "provider": "unknown_provider", "skills": []}))

        with pytest.raises(Exception, match="provider"):
            RoleRegistry(roles_dir=tmp_roles_dir, skills_dir=tmp_skills_dir)

    def test_unknown_override_role_raises(self, tmp_roles_dir, tmp_skills_dir, sample_role):
        with pytest.raises(KeyError, match="unknown role"):
            RoleRegistry(
                roles_dir=tmp_roles_dir,
                skills_dir=tmp_skills_dir,
                overrides={"typo_role": {"provider": "claude_code"}},
            )

    def test_cli_provider_uses_role_timeout(self, tmp_roles_dir, tmp_skills_dir):
        role_file = tmp_roles_dir / "engineer.yaml"
        role_file.write_text(yaml.dump({
            "name": "engineer",
            "provider": "claude_code",
            "skills": [],
            "timeout": 777,
        }))
        reg = RoleRegistry(roles_dir=tmp_roles_dir, skills_dir=tmp_skills_dir)

        provider = reg.get_provider("claude_code", timeout=reg.get_role("engineer").timeout)

        assert provider._timeout == 777


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
