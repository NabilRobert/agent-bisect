"""Secret stripping before anything is taped (threat T1).

Built on tracefork's `Redactor`: the same filters run on what is stored
and on what is matched at replay, so a stripped tape still replays (the
replayed agent reads `REDACTED` where the recording saw the secret, and
its next request is stripped the same way before it is compared).

Juku's per-call `_meta` delegation token needs no pattern: the tool seam
never puts `_meta` in a frame (`tools.py`).
"""

import re

from tracefork.redact import Redactor, regex_redactor, secret_value_redactor

# Key formats worth catching even when no env var names them; a subset of
# gitleaks' rules, which CI also runs over the repo.
SECRET_PATTERNS = (
    rb"sk-[A-Za-z0-9_\-]{20,}",  # OpenAI-style and most "sk-" provider keys
    rb"(?i)bearer\s+[A-Za-z0-9._~+/=\-]{16,}",  # bearer tokens in bodies or tool arguments
    rb"AKIA[0-9A-Z]{16}",  # AWS access key ids
    rb"gh[pousr]_[A-Za-z0-9]{36}",  # GitHub tokens
    rb"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",  # JWTs
)

# Env vars whose literal values must never reach a tape.
SECRET_ENV_VARS = ("OPENAI_API_KEY", "SUMOPOD_API_KEY", "ANTHROPIC_API_KEY", "GATEWAY_KEY")


def build_redactor() -> Redactor:
    """Strip key-shaped strings and known secret env values from requests and responses."""
    filters = (
        *(regex_redactor(re.compile(pattern)) for pattern in SECRET_PATTERNS),
        secret_value_redactor(SECRET_ENV_VARS),
    )
    return Redactor(request_filters=filters, response_filters=filters)


def strip_text(redactor: Redactor, text: str) -> str:
    """The same stripping, for text this repo stores beside the tape (run records)."""
    return redactor.apply_response(text.encode()).decode()
