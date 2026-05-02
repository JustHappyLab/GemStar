"""External text sanitizer — strips HTML, markdown links, and injection patterns.

CALLING SPEC:
    sanitize(text, max_length=4000) -> str
        1. Strip HTML tags (<script>, <iframe>, <a>, etc.)
        2. Strip markdown links [text](url) -> text
        3. Strip instruction-injection patterns
        4. Length-truncate to max_length
        5. Wrap result in <external_text>...</external_text>

SIDE EFFECTS:
    None. Pure function.
"""

import re

# Dangerous tags with content — remove tag AND everything inside.
_DANGEROUS_TAG_RE: re.Pattern[str] = re.compile(
    r"<(script|iframe|style|object|embed|applet|form)\b[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)

# Remaining HTML tags — strip the tags but keep inner text.
_HTML_TAG_RE: re.Pattern[str] = re.compile(r"<[^>]+>")

# Markdown links — [text](url) -> text.
_MD_LINK_RE: re.Pattern[str] = re.compile(r"\[([^\]]*)\]\([^)]*\)")

# Injection patterns — case-insensitive.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"override\s+(your\s+)?instructions", re.IGNORECASE),
    re.compile(r"new\s+instructions\s*:", re.IGNORECASE),
    re.compile(r"act\s+as\s+if\s+you\s+are", re.IGNORECASE),
    re.compile(r"pretend\s+you\s+(are|were|have)", re.IGNORECASE),
]


def _strip_injections(text: str) -> str:
    """Remove lines that match injection patterns."""
    lines = text.split("\n")
    clean: list[str] = []
    for line in lines:
        if any(pat.search(line) for pat in _INJECTION_PATTERNS):
            continue
        clean.append(line)
    return "\n".join(clean)


def sanitize(text: str, max_length: int = 4000) -> str:
    """Sanitize untrusted text for safe consumption by an LLM.

    Args:
        text: Raw external text.
        max_length: Maximum character length of the cleaned body.

    Returns:
        Cleaned text wrapped in <external_text>...</external_text> tags.
    """
    # 1a. Remove dangerous tags and their content.
    cleaned = _DANGEROUS_TAG_RE.sub("", text)
    # 1b. Strip remaining HTML tags.
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    # 2. Strip markdown links.
    cleaned = _MD_LINK_RE.sub(r"\1", cleaned)
    # 3. Strip injection patterns.
    cleaned = _strip_injections(cleaned)
    # 4. Collapse excessive whitespace.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    # 5. Length-truncate.
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    # 6. Wrap.
    return f"<external_text>\n{cleaned}\n</external_text>"
