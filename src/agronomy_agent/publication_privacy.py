"""Detect personal filesystem locations without retaining their values.

Hardware, performance measurements and public source URLs remain valid evidence.
"""
from __future__ import annotations

from html import unescape
from pathlib import Path
import re
from urllib.parse import unquote

# Split literals keep policy definitions from looking like disclosure examples.
_PREFIX = "/"
_PERSONAL_PATH = re.compile(
    r"(?:[A-Za-z]:/+" + "Users" + r"/+[^\s/<>\[\]{}?#&\"']+|"
    + _PREFIX + r"(?:Users|home)/[^\s/<>\[\]{}?#&\"']+|"
    + _PREFIX + r"Volumes/[^\s/<>\[\]{}?#&\"']+)(?:/|(?=[\s\"'<]|$))",
    re.IGNORECASE,
)
_WEB_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)


def personal_path_lines(content: bytes) -> list[int]:
    """Inspect text bytes, including JSON slash escapes, HTML and URL encoding."""
    lowered = content.lower()
    if not any(needle in lowered for needle in (b"users", b"volumes", b"home", b"\\u00", b"%")):
        return []
    text = content.decode("utf-8", errors="replace")
    # JSON often escapes slashes/backslashes or uses unicode escapes in strings.
    text = re.sub(r"\\u(00[0-7][0-9a-fA-F])", lambda m: chr(int(m[1], 16)), text)
    text = unquote(unescape(text)).replace("\\/", "/").replace("\\", "/")
    # A public URL's path is source provenance, not a machine filesystem path.
    def mask_source_url(match):
        value = match[0]
        end = min((i for i in (value.find("?"), value.find("#")) if i >= 0), default=len(value))
        # Only Linux-like source URL path segments are ambiguous. Never hide
        # a user profile or a filesystem path carried in a query/fragment.
        prefix = re.sub(r"/home/[^/?#]+", lambda m: " " * len(m[0]), value[:end], flags=re.IGNORECASE)
        return prefix + value[end:]
    text = _WEB_URL.sub(mask_source_url, text)
    return sorted({text.count("\n", 0, match.start()) + 1 for match in _PERSONAL_PATH.finditer(text)})


def require_public_paths(paths: list[Path], *, root: Path) -> None:
    """Check bytes selected for publication, including generated destination bytes."""
    failures = []
    for path in paths:
        lines = personal_path_lines(path.read_bytes())
        if lines:
            failures.append(f"personal_path:{path.relative_to(root).as_posix()}:{lines[0]}")
    if failures:
        raise ValueError("personal filesystem paths must stay private: " + ", ".join(failures[:20]))
