"""Path policy checks for engineering agents.

CALLING SPEC:
    decision = validate_changed_paths(
        role="bugfix",
        changed_paths=["src/data/fetcher.py"],
        allowed_paths=config.engineering.bugfix.allowed_paths,
        forbidden_paths=config.engineering.forbidden_paths,
        repo_root=Path.cwd(),
    )
    decision.raise_for_violations()

SIDE EFFECTS:
    None.  This module only validates path strings.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class PathPolicyViolation:
    """A single path policy violation."""

    role: str
    path: str
    reason: str
    pattern: str | None = None


@dataclass(frozen=True)
class PathPolicyDecision:
    """Result of checking a role's changed paths against its policy."""

    role: str
    changed_paths: tuple[str, ...]
    violations: tuple[PathPolicyViolation, ...]

    @property
    def allowed(self) -> bool:
        return not self.violations

    def raise_for_violations(self) -> None:
        """Raise ValueError if any changed path violates the policy."""
        if self.allowed:
            return
        details = "; ".join(
            f"{v.path}: {v.reason}" + (f" ({v.pattern})" if v.pattern else "")
            for v in self.violations
        )
        raise ValueError(f"Engineering path policy rejected role '{self.role}': {details}")


def validate_changed_paths(
    role: str,
    changed_paths: Iterable[str | Path],
    allowed_paths: Iterable[str],
    forbidden_paths: Iterable[str],
    repo_root: str | Path | None = None,
) -> PathPolicyDecision:
    """Validate changed paths for an engineering role.

    Forbidden patterns always win over allowed patterns.  Paths outside
    ``repo_root`` are rejected because engineering agents must only modify the
    current repository.
    """
    normalized = tuple(
        _normalize_repo_path(path, repo_root=Path(repo_root) if repo_root else None)
        for path in changed_paths
    )
    allowed = tuple(_normalize_pattern(p) for p in allowed_paths)
    forbidden = tuple(_normalize_pattern(p) for p in forbidden_paths)

    violations: list[PathPolicyViolation] = []
    for path in normalized:
        if not path:
            violations.append(PathPolicyViolation(role, path, "empty path"))
            continue
        if path.startswith("../") or path.startswith("/"):
            violations.append(PathPolicyViolation(role, path, "outside repository"))
            continue

        forbidden_match = _first_match(path, forbidden)
        if forbidden_match is not None:
            violations.append(
                PathPolicyViolation(role, path, "forbidden path", forbidden_match)
            )
            continue

        allowed_match = _first_match(path, allowed)
        if allowed_match is None:
            violations.append(PathPolicyViolation(role, path, "not in allowed paths"))

    return PathPolicyDecision(role, normalized, tuple(violations))


def validate_engineering_changes(
    config: Any,
    role: str,
    changed_paths: Iterable[str | Path],
    repo_root: str | Path | None = None,
) -> PathPolicyDecision:
    """Validate changed paths using ``GemStarConfig.engineering`` settings."""
    engineering = config.engineering
    try:
        role_policy = getattr(engineering, role)
    except AttributeError as exc:
        raise KeyError(f"Unknown engineering role: {role}") from exc
    return validate_changed_paths(
        role=role,
        changed_paths=changed_paths,
        allowed_paths=role_policy.allowed_paths,
        forbidden_paths=engineering.forbidden_paths,
        repo_root=repo_root,
    )


def _normalize_repo_path(path: str | Path, repo_root: Path | None) -> str:
    raw = str(path).replace("\\", "/").strip()
    if not raw:
        return ""

    p = Path(raw)
    if p.is_absolute():
        if repo_root is None:
            return p.as_posix()
        root = repo_root.resolve()
        resolved = p.resolve()
        try:
            raw = resolved.relative_to(root).as_posix()
        except ValueError:
            raw = "../" + resolved.as_posix().lstrip("/")

    while raw.startswith("./"):
        raw = raw[2:]
    return posixpath.normpath(raw)


def _normalize_pattern(pattern: str) -> str:
    pattern = pattern.replace("\\", "/").strip()
    while pattern.startswith("./"):
        pattern = pattern[2:]
    return pattern


def _first_match(path: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if fnmatchcase(path, pattern):
            return pattern
    return None
