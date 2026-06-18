"""Shared safety helpers for the feishu-meeting-workflow scripts.

Patterns here are deliberately narrow. Earlier versions matched the bare word
"secret"/"credentials"/"cookie" anywhere in a path, which refused legitimate
working directories (e.g. `secret-projects/`) and blanked meeting excerpts that
merely discussed a "secret" roadmap. These helpers instead target real
credential FILES (by basename) and real secret VALUE shapes.

All scripts run with their own directory on sys.path[0], so `from _safety import ...`
resolves whether a script is executed directly or imported by the self-test.
"""

from __future__ import annotations

import re
from pathlib import Path

# Credential files, matched against the final path component only.
SECRET_FILE_RE = re.compile(
    r"""(?ix)
    ^(
        \.env(\.[\w.-]+)?
      | .+\.(pem|key|p12|pfx|keystore|jks)
      | (id_rsa|id_dsa|id_ecdsa|id_ed25519)(\.pub)?
      | \.(netrc|npmrc|pypirc|pgpass|htpasswd)
      | (secrets?|credentials?|client[_-]?secret|app[_-]?secret|service[-_]?account)
            \.(json|ya?ml|yml|txt|ini|conf|cfg|env)
      | cookies?\.(txt|json|sqlite)
    )$
    """,
)

# Real secret VALUE shapes that must never land in generated/public content.
SECRET_CONTENT_RE = re.compile(
    r"""(?ix)
    (app|client)[_-]?secret\s*[:=]
  | (access|refresh|tenant|user)[_-]?token\s*[:=]
  | authorization:\s*bearer\s
  | -----BEGIN[A-Z ]+PRIVATE\ KEY-----
  | \bpass(word|wd)\s*[:=]\s*\S
  | \bauthcode=
  | \bAKIA[0-9A-Z]{16}\b
  | \b(?:u|t)-[A-Za-z0-9_]{20,}\b
    """,
)

# Token-ish shapes to remove from captured CLI error/diagnostic text before display.
_SCRUB_RES = [
    re.compile(
        r"(?i)((?:app|client)[_-]?secret|appSecret|(?:access|refresh|tenant|user)[_-]?token)"
        r"\"?\s*[:=]\s*\"?[^\"'\s,}]+"
    ),
    re.compile(r"(?i)authorization:\s*bearer\s+\S+"),
    re.compile(r"\b(?:u|t)-[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bauthcode=[^&\s\"']+"),
    re.compile(r"\b(?:cli|oc|om|ou)_[A-Za-z0-9_-]+\b"),
]


def is_secret_file(path: str | Path) -> bool:
    """True if the path's basename looks like a known credential file."""
    return bool(SECRET_FILE_RE.match(Path(str(path)).name))


def has_secret_content(text: str) -> bool:
    """True if the text contains a real secret value shape (not just the word 'secret')."""
    return bool(SECRET_CONTENT_RE.search(text or ""))


def scrub(text: str) -> str:
    """Redact token/secret value shapes from arbitrary text for safe display."""
    out = text or ""
    for pattern in _SCRUB_RES:
        out = pattern.sub("[redacted]", out)
    return out
