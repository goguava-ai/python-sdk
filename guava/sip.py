from dataclasses import dataclass, field
from urllib.parse import quote

# Characters allowed unescaped in each component, per RFC 3261 section 25.1.
_MARK = "-_.!~*'()"
_USER_SAFE = _MARK + "&=+$,;?/"
_PARAM_SAFE = _MARK + "[]/:&+$"
_HEADER_SAFE = _MARK + "[]/?:+$"


@dataclass
class SipUri:
    host: str
    user: str | None = None

    uri_params: dict[str, str | None] = field(default_factory=dict)
    headers: dict[str, str | None] = field(default_factory=dict)

    def __str__(self) -> str:
        url = "sip:"
        if self.user is not None:
            url += quote(self.user, safe=_USER_SAFE) + "@"
        url += self.host

        for name, value in self.uri_params.items():
            url += ";" + quote(name, safe=_PARAM_SAFE)
            if value is not None:
                url += "=" + quote(value, safe=_PARAM_SAFE)

        # Headers always need an "=", so a None value renders as "name=".
        if self.headers:
            url += "?" + "&".join(
                f"{quote(name, safe=_HEADER_SAFE)}={quote('' if value is None else str(value), safe=_HEADER_SAFE)}"
                for name, value in self.headers.items()
            )

        return url
