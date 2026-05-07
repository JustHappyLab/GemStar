"""Factor expression engine — safe evaluation of LLM-authored factor formulas.

CALLING SPEC:
    result = compute_factor_expression(
        expr: str,
        df: pd.DataFrame,         # must have ts_code + trade_date + raw fields
        allowed_fields: set[str],
    ) -> pd.Series
        Returns a Series aligned with df.index containing the factor values.
        Time-series operators are applied per ts_code group.

    validate_expression(expr, allowed_fields) -> None
        Raises ValueError if the expression uses disallowed names or syntax.

SECURITY:
    Expressions are parsed with ast and walked node-by-node.  Only a fixed
    whitelist of node types, operators, function names, and identifiers is
    accepted.  No attribute access, no subscripting, no comprehensions, no
    keyword arguments — pure prefix expressions over the allowed namespace.

SIDE EFFECTS:
    None — pure function of (expr, df).
"""

from __future__ import annotations

import ast

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Whitelist of AST nodes the parser accepts.  Anything else is rejected.
# ---------------------------------------------------------------------------
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


# ---------------------------------------------------------------------------
# Time-series operators (applied per ts_code group).
# Each takes a pd.Series (values for one stock, sorted by trade_date) and
# returns a pd.Series aligned to the same index.
# ---------------------------------------------------------------------------

def _ts_mean(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=int(window), min_periods=max(2, int(window) // 2)).mean()


def _ts_std(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=int(window), min_periods=max(2, int(window) // 2)).std()


def _ts_max(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=int(window), min_periods=2).max()


def _ts_min(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=int(window), min_periods=2).min()


def _ts_sum(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=int(window), min_periods=2).sum()


def _ts_delta(series: pd.Series, window: int) -> pd.Series:
    return series - series.shift(int(window))


def _ts_pct_change(series: pd.Series, window: int) -> pd.Series:
    return series.pct_change(periods=int(window))


def _ts_delay(series: pd.Series, window: int) -> pd.Series:
    return series.shift(int(window))


def _ts_rank(series: pd.Series, window: int) -> pd.Series:
    """Rolling rank scaled to [0, 1]; last value's percentile within window."""
    w = int(window)
    return series.rolling(window=w, min_periods=2).rank(pct=True)


def _ts_zscore(series: pd.Series, window: int) -> pd.Series:
    w = int(window)
    mean = series.rolling(window=w, min_periods=max(2, w // 2)).mean()
    std = series.rolling(window=w, min_periods=max(2, w // 2)).std()
    return (series - mean) / std.replace(0.0, np.nan)


# Time-series ops dispatch: name -> (callable, expects two-series? )
_TS_UNARY_OPS = {
    "ts_mean": _ts_mean,
    "ts_std": _ts_std,
    "ts_max": _ts_max,
    "ts_min": _ts_min,
    "ts_sum": _ts_sum,
    "ts_delta": _ts_delta,
    "ts_pct_change": _ts_pct_change,
    "ts_delay": _ts_delay,
    "ts_rank": _ts_rank,
    "ts_zscore": _ts_zscore,
}


def _ts_corr(a: pd.Series, b: pd.Series, window: int) -> pd.Series:
    w = int(window)
    return a.rolling(window=w, min_periods=max(2, w // 2)).corr(b)


_TS_BINARY_OPS = {
    "ts_corr": _ts_corr,
}


# ---------------------------------------------------------------------------
# Element-wise operators (no group context required).
# ---------------------------------------------------------------------------

def _abs_op(s: pd.Series) -> pd.Series:
    return s.abs()


def _log_op(s: pd.Series) -> pd.Series:
    return np.log(s.where(s > 0, np.nan))


def _sign_op(s: pd.Series) -> pd.Series:
    return np.sign(s)


def _sqrt_op(s: pd.Series) -> pd.Series:
    return np.sqrt(s.where(s >= 0, np.nan))


def _clip_op(s: pd.Series, lower: float, upper: float) -> pd.Series:
    return s.clip(lower=float(lower), upper=float(upper))


def _where_op(cond: pd.Series, a: pd.Series, b: pd.Series) -> pd.Series:
    return pd.Series(np.where(cond, a, b), index=cond.index)


_ELEMENT_OPS = {
    "abs": _abs_op,
    "log": _log_op,
    "sign": _sign_op,
    "sqrt": _sqrt_op,
    "clip": _clip_op,
    "where": _where_op,
}


# ---------------------------------------------------------------------------
# Cross-sectional operator (per trade_date group).
# ---------------------------------------------------------------------------

_CS_OPS = {"cs_rank"}  # handled specially in evaluator


# ---------------------------------------------------------------------------
# Public registry of all callable function names (for validation + prompt).
# ---------------------------------------------------------------------------

ALLOWED_FUNCTIONS = (
    set(_TS_UNARY_OPS)
    | set(_TS_BINARY_OPS)
    | set(_ELEMENT_OPS)
    | _CS_OPS
)


# ---------------------------------------------------------------------------
# Validation: walk AST, ensure only whitelisted nodes/names appear.
# ---------------------------------------------------------------------------

def validate_expression(expr: str, allowed_fields: set[str]) -> None:
    """Raise ValueError if expr uses any non-whitelisted construct."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Expression syntax error: {exc}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(
                f"Disallowed AST node: {type(node).__name__}"
            )
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Only direct function calls are allowed")
            if node.func.id not in ALLOWED_FUNCTIONS:
                raise ValueError(f"Unknown function: {node.func.id}")
            if node.keywords:
                raise ValueError("Keyword arguments are not allowed")
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            raise ValueError("Names may only be read, not assigned")


# ---------------------------------------------------------------------------
# Evaluator: walk AST, build pd.Series result.
# ---------------------------------------------------------------------------

class _Evaluator:
    """Recursive evaluator over a panel DataFrame (ts_code + trade_date + cols)."""

    def __init__(self, df: pd.DataFrame, allowed_fields: set[str]) -> None:
        self._df = df
        self._allowed = allowed_fields

    def _get_field(self, name: str) -> pd.Series:
        if name not in self._allowed:
            raise ValueError(f"Unknown field: {name}")
        if name not in self._df.columns:
            raise ValueError(f"Field not present in data: {name}")
        return self._df[name]

    def _ts_apply(self, fn, series: pd.Series, window: int) -> pd.Series:
        """Apply unary time-series op per ts_code group."""
        result = series.groupby(self._df["ts_code"], sort=False).transform(
            lambda s: fn(s, window)
        )
        return result

    def _ts_apply_binary(self, fn, a: pd.Series, b: pd.Series, window: int) -> pd.Series:
        """Apply binary time-series op (e.g. ts_corr) per ts_code group."""
        groups = self._df["ts_code"]
        out = pd.Series(np.nan, index=self._df.index, dtype=float)
        for code, idx in self._df.groupby(groups, sort=False).indices.items():
            out.iloc[idx] = fn(a.iloc[idx], b.iloc[idx], window).values
        return out

    def _cs_rank(self, series: pd.Series) -> pd.Series:
        """Cross-sectional rank in [0, 1] per trade_date."""
        return series.groupby(self._df["trade_date"], sort=False).transform(
            lambda s: s.rank(pct=True)
        )

    def _eval_constant(self, node: ast.Constant) -> int | float:
        if not isinstance(node.value, (int, float)):
            raise ValueError(f"Only numeric constants allowed, got {type(node.value).__name__}")
        return node.value

    def _eval_call(self, node: ast.Call) -> pd.Series:
        name = node.func.id  # already validated to be ast.Name
        args = node.args

        if name in _TS_UNARY_OPS:
            if len(args) != 2:
                raise ValueError(f"{name} expects 2 args (series, window)")
            series = self._eval(args[0])
            window = self._eval(args[1])
            if not isinstance(window, (int, float)):
                raise ValueError(f"{name} window must be a numeric constant")
            if isinstance(series, pd.Series):
                return self._ts_apply(_TS_UNARY_OPS[name], series, int(window))
            raise ValueError(f"{name} requires a series argument")

        if name in _TS_BINARY_OPS:
            if len(args) != 3:
                raise ValueError(f"{name} expects 3 args (series_a, series_b, window)")
            a = self._eval(args[0])
            b = self._eval(args[1])
            window = self._eval(args[2])
            if not isinstance(a, pd.Series) or not isinstance(b, pd.Series):
                raise ValueError(f"{name} requires two series arguments")
            return self._ts_apply_binary(_TS_BINARY_OPS[name], a, b, int(window))

        if name == "cs_rank":
            if len(args) != 1:
                raise ValueError("cs_rank expects 1 arg")
            series = self._eval(args[0])
            if not isinstance(series, pd.Series):
                raise ValueError("cs_rank requires a series argument")
            return self._cs_rank(series)

        if name in _ELEMENT_OPS:
            evaluated = [self._eval(a) for a in args]
            return _ELEMENT_OPS[name](*evaluated)

        raise ValueError(f"Unknown function: {name}")

    def _eval_binop(self, node: ast.BinOp) -> pd.Series:
        left = self._eval(node.left)
        right = self._eval(node.right)
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right
        if isinstance(op, ast.Mod):
            return left % right
        if isinstance(op, ast.Pow):
            return left ** right
        raise ValueError(f"Unsupported binary op: {type(op).__name__}")

    def _eval_unaryop(self, node: ast.UnaryOp) -> pd.Series:
        operand = self._eval(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")

    def _eval_compare(self, node: ast.Compare) -> pd.Series:
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ValueError("Only single-operator comparisons are supported")
        left = self._eval(node.left)
        right = self._eval(node.comparators[0])
        op = node.ops[0]
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.LtE):
            return left <= right
        if isinstance(op, ast.Gt):
            return left > right
        if isinstance(op, ast.GtE):
            return left >= right
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        raise ValueError(f"Unsupported comparison: {type(op).__name__}")

    def _eval(self, node: ast.AST):
        if isinstance(node, ast.Expression):
            return self._eval(node.body)
        if isinstance(node, ast.Constant):
            return self._eval_constant(node)
        if isinstance(node, ast.Name):
            return self._get_field(node.id)
        if isinstance(node, ast.Call):
            return self._eval_call(node)
        if isinstance(node, ast.BinOp):
            return self._eval_binop(node)
        if isinstance(node, ast.UnaryOp):
            return self._eval_unaryop(node)
        if isinstance(node, ast.Compare):
            return self._eval_compare(node)
        raise ValueError(f"Unsupported node: {type(node).__name__}")

    def run(self, expr: str) -> pd.Series:
        tree = ast.parse(expr, mode="eval")
        result = self._eval(tree)
        if not isinstance(result, pd.Series):
            raise ValueError("Expression did not produce a Series")
        return result.replace([np.inf, -np.inf], np.nan)


def compute_factor_expression(
    expr: str,
    df: pd.DataFrame,
    allowed_fields: set[str],
) -> pd.Series:
    """Compute one factor expression over a panel DataFrame.

    Args:
        expr: Pure-prefix factor expression using whitelisted ops/fields.
        df: Panel DataFrame sorted by (ts_code, trade_date).
            Must contain ``ts_code``, ``trade_date``, and the referenced fields.
        allowed_fields: Set of field names the expression may reference.

    Returns:
        A pd.Series aligned with df.index containing the computed factor values.

    Raises:
        ValueError on parse, validation, or runtime errors.
    """
    if "ts_code" not in df.columns or "trade_date" not in df.columns:
        raise ValueError("df must contain ts_code and trade_date columns")
    validate_expression(expr, allowed_fields)
    evaluator = _Evaluator(df, allowed_fields)
    return evaluator.run(expr)
