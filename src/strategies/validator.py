"""Strategy validator — gate before backtesting.

CALLING SPEC:
    validate_strategy(yaml_path, pool_path) -> VerdictV1
    Schema-validates a strategy YAML, cross-checks factor references
    against the factor pool, and returns a VerdictV1 with blocking_issues
    if anything fails.

SIDE EFFECTS:
    None. Pure function.
"""

from pathlib import Path

from src.schemas.factor import FactorPoolV1
from src.schemas.strategy import StrategyConfigV1
from src.schemas.verdict import VerdictV1


def validate_strategy(
    yaml_path: str | Path,
    pool_path: str | Path,
    *,
    strategy_id: str = "",
) -> VerdictV1:
    """Validate a strategy YAML against schema and factor pool.

    Steps:
        1. Schema-parse the YAML via StrategyConfigV1.from_yaml.
        2. Load the factor pool via FactorPoolV1.load.
        3. For each factor in strategy.factors, check it is registered
           and has status in {active, candidate}.
        4. Return VerdictV1 with any blocking_issues.

    Args:
        yaml_path: Path to strategy_config YAML.
        pool_path: Path to factors/pool.json.
        strategy_id: Optional id to stamp on the verdict.

    Returns:
        VerdictV1 with recommended_state and blocking_issues.
    """
    blocking: list[str] = []

    # Step 1: schema-validate the YAML
    try:
        config = StrategyConfigV1.from_yaml(yaml_path)
    except Exception as exc:
        blocking.append(f"YAML schema validation failed: {exc}")
        return VerdictV1(
            strategy_id=strategy_id,
            recommended_state="rejected",
            blocking_issues=blocking,
        )

    # Step 2: load factor pool
    try:
        pool = FactorPoolV1.load(pool_path)
    except Exception as exc:
        blocking.append(f"Factor pool load failed: {exc}")
        return VerdictV1(
            strategy_id=strategy_id or config.name,
            recommended_state="rejected",
            blocking_issues=blocking,
        )

    # Step 3: empty factors check
    if not config.factors:
        blocking.append("Strategy has no factors defined (empty factors list).")
        return VerdictV1(
            strategy_id=strategy_id or config.name,
            recommended_state="rejected",
            blocking_issues=blocking,
        )

    # Step 4: validate each factor reference
    for fw in config.factors:
        if not pool.is_registered(fw.factor_id):
            blocking.append(
                f"Factor '{fw.factor_id}' not found in factor pool."
            )
        elif not pool.is_active_or_candidate(fw.factor_id):
            entry = pool.get(fw.factor_id)
            assert entry is not None  # guaranteed by is_registered
            blocking.append(
                f"Factor '{fw.factor_id}' has status '{entry.status}', "
                f"must be 'active' or 'candidate'."
            )

    recommended = "candidate" if not blocking else "rejected"

    return VerdictV1(
        strategy_id=strategy_id or config.name,
        recommended_state=recommended,
        blocking_issues=blocking,
    )
