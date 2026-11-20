"""Search the public MCP registry for connectors that are not in the catalogue.

Nothing here is checked by whyline: every result has ``checked = ""`` and no tool
risks, so the four-part screen shows it as not checked and the Test fills the rest.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from whyline.tools.catalogue import _VAR, Credential, Entry

# The registry's search endpoint: GET /v0/servers?search=<text>&limit=<n>, answering
# {"servers": [{"server": {name, description, repository, packages, remotes}}]}.
# Written from the registry's published API documentation on 2026-11-20; the builder
# had no network access to re-check it live, so verify against the docs.
REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0/servers"
TIMEOUT = 10
HEADING = "From the public registry · not checked by whyline"
REMOTE_REFUSAL = "needs a browser sign-in, which whyline can't do yet"

_error = ""


def last_error() -> str:
    """Why the last search returned nothing because it failed; empty if it did not fail."""
    return _error


def _get(url: str, *, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https registry URL
        return json.loads(response.read().decode("utf-8"))


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.rsplit("/", 1)[-1].lower()).strip("-") or "server"


def _entry(server: dict) -> Entry | None:
    name = str(server.get("name", ""))
    if not name:
        return None
    repository = server.get("repository") or {}
    source = str(repository.get("url") or f"{REGISTRY_URL}?search={urllib.parse.quote(name)}")
    base = dict(name=_slug(name), title=name, about=str(server.get("description", "")),
                tools=(), source=source, checked="")

    for package in server.get("packages") or []:
        identifier = str(package.get("identifier", ""))
        if (package.get("transport") or {}).get("type", "stdio") != "stdio" or not identifier:
            continue
        kind = package.get("registryType")
        if kind == "npm":
            command, args = "npx", ("-y", identifier)
        elif kind == "pypi":
            command, args = "uvx", (identifier,)
        else:
            continue
        creds = []
        for var in package.get("environmentVariables") or []:
            var_name = str(var.get("name", ""))
            if not _VAR.match(var_name):
                reason = f"needs a setting named {var_name!r}, which whyline can't store"
                return Entry(command="", args=(), credentials=(), refused=reason, **base)
            creds.append(Credential(var_name, str(var.get("description") or var_name), ""))
        return Entry(command=command, args=args, credentials=tuple(creds), **base)
    if server.get("remotes"):
        return Entry(command="", args=(), credentials=(), refused=REMOTE_REFUSAL, **base)
    return None


def search(text: str, *, get=_get, limit: int = 20) -> list[Entry]:
    """Registry results for ``text``. Any failure gives an empty list and sets
    ``last_error()``; nothing is cached."""
    global _error
    _error = ""
    query = urllib.parse.urlencode({"search": text.strip(), "limit": limit})
    try:
        data = get(f"{REGISTRY_URL}?{query}", timeout=TIMEOUT)
        entries = [_entry(item.get("server", item)) for item in data.get("servers", [])]
    except Exception as error:  # the reason is shown, whatever went wrong
        _error = f"The public registry could not be searched: {str(error) or type(error).__name__}"
        return []
    return [e for e in entries if e is not None][:limit]
