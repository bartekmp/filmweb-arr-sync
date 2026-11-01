import re
from urllib.parse import quote

import requests
from requests.utils import check_header_validity


def redact_secret(text: str, secret: str) -> str:
    """Redact credentials before truncation, including URL-encoded copies."""
    if not secret:
        return text
    for value in sorted({secret, quote(secret, safe="")}, key=len, reverse=True):
        text = re.sub(re.escape(value), "[REDACTED]", text, flags=re.IGNORECASE)
    return text


def validate_api_key(api_key: str) -> None:
    """Reject invalid header values without echoing them in requests errors."""
    try:
        check_header_validity(("X-Api-Key", api_key))
        api_key.encode("latin-1")
    except (requests.exceptions.InvalidHeader, UnicodeEncodeError):
        raise requests.exceptions.InvalidHeader("Invalid API key header value") from None


def raise_for_status(response: requests.Response, secret: str) -> None:
    """Keep HTTP error metadata while redacting credentials echoed in the reason."""
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise requests.HTTPError(
            redact_secret(str(exc), secret), response=exc.response, request=exc.request
        ) from None
