"""Made tools: a saved web request an agent can call.

A made tool is one file in ``~/.whyline/tools/<name>.toml``. It names a web
address with ``{input}`` places, the headers, query and JSON body to send, and
which part of the answer to hand back. Before a call the tool must have been
accepted (its hash stored), the host must resolve to a public address, and the
credential's value never appears in anything returned.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlsplit

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
INPUT_TYPES = ("string", "number", "boolean")
RISKS = ("reads", "writes", "spends")
TIMEOUT = 15
MAX_BYTES = 200_000
MAX_REDIRECTS = 5
ERROR_CHARS = 500

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_PLACE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]+$")
_FORBIDDEN_HEADERS = {"host", "content-length"}


class MadeToolError(ValueError):
    """A made tool is invalid, not accepted, or refused to run."""


@dataclass
class ToolInput:
    name: str
    type: str = "string"
    about: str = ""
    required: bool = True


@dataclass
class MadeTool:
    name: str
    about: str = ""
    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    body: str = ""
    inputs: list[ToolInput] = field(default_factory=list)
    credential: str = ""
    credential_in: str = ""
    pick: str = ""
    risk: str = "reads"
    accepted_hash: str = ""


# --- storage ---------------------------------------------------------------


def tools_dir() -> Path:
    return Path.home() / ".whyline" / "tools"


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name))


def _path(name: str) -> Path:
    if not valid_name(name):
        raise MadeToolError(f"Bad tool name: {name!r}")
    return tools_dir() / f"{name}.toml"


def _q(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _dump(tool: MadeTool) -> str:
    lines = [
        f"name = {_q(tool.name)}",
        f"about = {_q(tool.about)}",
        f"method = {_q(tool.method)}",
        f"url = {_q(tool.url)}",
        f"body = {_q(tool.body)}",
        f"credential = {_q(tool.credential)}",
        f"credential_in = {_q(tool.credential_in)}",
        f"pick = {_q(tool.pick)}",
        f"risk = {_q(tool.risk)}",
        f"accepted_hash = {_q(tool.accepted_hash)}",
    ]
    for table, values in (("headers", tool.headers), ("query", tool.query)):
        lines += ["", f"[{table}]"]
        lines += [f"{_q(k)} = {_q(v)}" for k, v in values.items()]
    for item in tool.inputs:
        lines += [
            "",
            "[[inputs]]",
            f"name = {_q(item.name)}",
            f"type = {_q(item.type)}",
            f"about = {_q(item.about)}",
            f"required = {'true' if item.required else 'false'}",
        ]
    return "\n".join(lines) + "\n"


def _text(raw: dict, key: str, default: str = "") -> str:
    value = raw.get(key, default)
    return value if isinstance(value, str) else default


def _strings(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, str)}


def _parse(raw: dict) -> MadeTool:
    inputs = []
    for item in raw.get("inputs", []):
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            inputs.append(
                ToolInput(
                    name=item["name"],
                    type=_text(item, "type", "string"),
                    about=_text(item, "about"),
                    required=item.get("required", True) is not False,
                )
            )
    return MadeTool(
        name=_text(raw, "name"),
        about=_text(raw, "about"),
        method=_text(raw, "method", "GET"),
        url=_text(raw, "url"),
        headers=_strings(raw.get("headers")),
        query=_strings(raw.get("query")),
        body=_text(raw, "body"),
        inputs=inputs,
        credential=_text(raw, "credential"),
        credential_in=_text(raw, "credential_in"),
        pick=_text(raw, "pick"),
        risk=_text(raw, "risk", "reads"),
        accepted_hash=_text(raw, "accepted_hash"),
    )


def load(name: str) -> MadeTool | None:
    try:
        raw = tomllib.loads(_path(name).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, MadeToolError):
        return None
    tool = _parse(raw)
    return tool if tool.name == name else None


def load_all() -> list[MadeTool]:
    found = []
    try:
        files = sorted(tools_dir().glob("*.toml"))
    except OSError:
        return []
    for path in files:
        tool = load(path.stem)
        if tool is not None:
            found.append(tool)
    return found


def save(tool: MadeTool) -> Path:
    path = _path(tool.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(tool), encoding="utf-8")
    return path


def remove(name: str) -> bool:
    path = _path(name)
    if not path.exists():
        return False
    path.unlink()
    return True


def tool_hash(tool: MadeTool) -> str:
    data = asdict(tool)
    data.pop("accepted_hash", None)
    text = json.dumps(data, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def accept(name: str) -> MadeTool:
    tool = load(name)
    if tool is None:
        raise MadeToolError(f"No tool named {name!r}")
    tool = replace(tool, accepted_hash=tool_hash(tool))
    save(tool)
    return tool


def accepted(tool: MadeTool) -> bool:
    return bool(tool.accepted_hash) and tool.accepted_hash == tool_hash(tool)


# --- validation ------------------------------------------------------------


def _body_strings(node: object):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _body_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _body_strings(value)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _used_places(tool: MadeTool) -> set[str]:
    texts = [tool.url, *tool.headers.values(), *tool.query.values()]
    texts += [*tool.headers, *tool.query]
    if tool.body.strip():
        try:
            texts += list(_body_strings(json.loads(tool.body)))
        except ValueError:
            texts.append(tool.body)
    used: set[str] = set()
    for text in texts:
        used.update(_PLACE.findall(text))
    return used


def validate(tool: MadeTool) -> None:
    """Raise MadeToolError for the first thing wrong with the tool."""
    if not valid_name(tool.name):
        raise MadeToolError("The name needs lowercase letters, digits, - or _.")
    if tool.method not in METHODS:
        raise MadeToolError(f"The method must be one of {', '.join(METHODS)}.")
    if tool.risk not in RISKS:
        raise MadeToolError(f"The risk must be one of {', '.join(RISKS)}.")
    if tool.method != "GET" and tool.risk == "reads":
        raise MadeToolError(f"{tool.method} changes things: the risk must be writes or higher.")

    parts = urlsplit(tool.url)
    if parts.scheme != "https":
        raise MadeToolError("The URL must start with https://.")
    host = (parts.hostname or "").lower() if "{" not in parts.netloc else ""
    if not host:
        raise MadeToolError("The URL needs a fixed host, with no {input} in it.")
    if _is_ip_literal(host):
        raise MadeToolError("The host must be a name, not an IP address.")
    if host == "localhost" or host.endswith(".localhost"):
        raise MadeToolError("The host must not be localhost.")
    if "{credential}" in parts.path:
        raise MadeToolError("A credential must not be placed in the URL path.")

    declared: set[str] = set()
    for item in tool.inputs:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item.name):
            raise MadeToolError(f"Bad input name: {item.name!r}.")
        if item.name in declared:
            raise MadeToolError(f"The input {item.name!r} is declared twice.")
        if item.type not in INPUT_TYPES:
            raise MadeToolError(f"The input {item.name!r} must be string, number or boolean.")
        declared.add(item.name)
    undeclared = sorted(_used_places(tool) - declared)
    if undeclared:
        raise MadeToolError(f"Used but not declared as an input: {', '.join(undeclared)}.")

    for name in tool.headers:
        if name.lower() in _FORBIDDEN_HEADERS:
            raise MadeToolError(f"The header {name} cannot be set.")
        if not _HEADER_NAME.match(name):
            raise MadeToolError(f"Bad header name: {name!r}.")

    if tool.body.strip():
        try:
            json.loads(tool.body)
        except ValueError as exc:
            raise MadeToolError(f"The body is not valid JSON: {exc}") from exc

    if tool.credential or tool.credential_in:
        kind, _, where = tool.credential_in.partition(":")
        if kind not in ("header", "query") or not where:
            raise MadeToolError("credential_in must be header:<Name> or query:<name>.")
        if not tool.credential:
            raise MadeToolError("credential_in is set but no credential is named.")
        if kind == "header" and (
            where.lower() in _FORBIDDEN_HEADERS or not _HEADER_NAME.match(where)
        ):
            raise MadeToolError(f"The header {where} cannot be set.")


# --- calling ---------------------------------------------------------------


def _coerce(item: ToolInput, value: object) -> object:
    if item.type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
    elif item.type == "number":
        if isinstance(value, bool):
            pass
        elif isinstance(value, (int, float)):
            return value
        elif isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                try:
                    number = float(value)
                except ValueError:
                    number = None
                if number is not None and number == number and abs(number) != float("inf"):
                    return number
    elif isinstance(value, str):
        return value
    raise MadeToolError(f"The input {item.name!r} must be a {item.type}.")


def _arguments(tool: MadeTool, args: dict) -> dict[str, object]:
    known = {item.name: item for item in tool.inputs}
    extra = sorted(set(args) - set(known))
    if extra:
        raise MadeToolError(f"Unknown input: {', '.join(extra)}.")
    values: dict[str, object] = {}
    for item in tool.inputs:
        if args.get(item.name) is None:
            if item.required:
                raise MadeToolError(f"The input {item.name!r} is required.")
            continue
        values[item.name] = _coerce(item, args[item.name])
    return values


def _text_of(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _fill(template: str, values: dict[str, object], encode: Callable[[str], str]) -> str:
    return _PLACE.sub(lambda m: encode(_text_of(values.get(m.group(1), ""))), template)


def _fill_json(node: object, values: dict[str, object]) -> object:
    if isinstance(node, str):
        whole = _PLACE.fullmatch(node)
        if whole:
            return values.get(whole.group(1))
        return _fill(node, values, lambda s: s)
    if isinstance(node, dict):
        return {_fill(str(k), values, lambda s: s): _fill_json(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill_json(v, values) for v in node]
    return node


def _public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


def _check_host(host: str, resolve: Callable[[str], list[str]]) -> str:
    if not host or _is_ip_literal(host) or host == "localhost" or host.endswith(".localhost"):
        raise MadeToolError(f"Refused: {host or 'no host'} is not a public host name.")
    try:
        addresses = list(resolve(host))
    except OSError as exc:
        raise MadeToolError(f"Could not find {host}: {exc}") from exc
    if not addresses:
        raise MadeToolError(f"Could not find {host}.")
    for address in addresses:
        if not _public(address):
            raise MadeToolError(f"Refused: {host} points at a private or reserved address.")
    return addresses[0]


def _scrub(text: str, secret: str) -> str:
    if not secret:
        return text
    for form in {secret, quote(secret, safe=""), quote(secret), json.dumps(secret)[1:-1]}:
        if form:
            text = text.replace(form, "[credential]")
    return text


def _pick(data: object, path: str) -> object:
    for part in path.split("."):
        if isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        elif isinstance(data, dict) and part in data:
            data = data[part]
        else:
            raise MadeToolError(f"Nothing at {path!r} in the answer.")
    return data


def _render(data: object) -> str:
    return data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)


def default_resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


def default_request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    *,
    timeout: float,
    max_bytes: int,
    address: str,
) -> tuple[int, dict[str, str], bytes]:
    """Send one request to the checked address; never follows a redirect."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or 443
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    raw = socket.create_connection((address, port), timeout=timeout)
    try:
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
    except Exception:
        raw.close()
        raise
    conn = http.client.HTTPSConnection(host, port, timeout=timeout)
    conn.sock = sock
    try:
        sent = {"Host": parts.netloc, **headers}
        conn.request(method, target, body=body, headers=sent)
        response = conn.getresponse()
        data = response.read(max_bytes)
        return response.status, {k.lower(): v for k, v in response.getheaders()}, data
    finally:
        conn.close()


def call(
    tool: MadeTool,
    args: dict,
    *,
    get_credential: Callable[[str], str | None],
    resolve: Callable[[str], list[str]] = default_resolve,
    request: Callable[..., tuple[int, dict[str, str], bytes]] = default_request,
) -> str:
    """Run an accepted made tool and return the picked part as text."""
    if not accepted(tool):
        raise MadeToolError(f"{tool.name} has changed or was never accepted: accept it first.")
    validate(tool)
    values = _arguments(tool, args)

    url = _fill(tool.url, values, lambda s: quote(s, safe=""))
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host != (urlsplit(tool.url).hostname or "").lower():
        raise MadeToolError("Refused: the host changed while filling the URL.")

    query = {
        _fill(k, values, lambda s: s): _fill(v, values, lambda s: s) for k, v in tool.query.items()
    }
    headers = {k: _fill(v, values, lambda s: s) for k, v in tool.headers.items()}
    secret = ""
    if tool.credential:
        secret = get_credential(tool.credential) or ""
        if not secret:
            raise MadeToolError(f"The credential {tool.credential!r} is not stored.")
        kind, _, where = tool.credential_in.partition(":")
        if kind == "header":
            headers[where] = secret
        else:
            query[where] = secret
    for name, value in headers.items():
        if "\r" in value or "\n" in value:
            raise MadeToolError(f"The header {name} has a line break in it.")

    body = None
    if tool.body.strip():
        filled = _fill_json(json.loads(tool.body), values)
        body = json.dumps(filled, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    if query:
        sep = "&" if parts.query else "?"
        url = url + sep + urlencode(query, quote_via=quote)

    try:
        for _ in range(MAX_REDIRECTS + 1):
            address = _check_host(urlsplit(url).hostname or "", resolve)
            status, reply, data = request(
                tool.method,
                url,
                headers,
                body,
                timeout=TIMEOUT,
                max_bytes=MAX_BYTES,
                address=address,
            )
            if status in (301, 302, 303, 307, 308) and reply.get("location"):
                target = urljoin(url, reply["location"])
                new = urlsplit(target)
                if new.scheme != "https" or (new.hostname or "").lower() != host:
                    raise MadeToolError("Refused: the answer redirects to another host.")
                url = target
                if status in (301, 302, 303) and tool.method != "GET":
                    raise MadeToolError("Refused: the answer redirects a request that changes things.")
                continue
            break
        else:
            raise MadeToolError("Refused: too many redirects.")

        data = data[:MAX_BYTES]
        text = _scrub(data.decode("utf-8", errors="replace"), secret)
        if not 200 <= status < 300:
            return f"HTTP {status} {text[:ERROR_CHARS]}"
        if not tool.pick:
            return text
        try:
            return _scrub(_render(_pick(json.loads(text), tool.pick)), secret)
        except ValueError as exc:
            if isinstance(exc, MadeToolError):
                raise
            raise MadeToolError("The answer is not JSON, so nothing can be picked.") from None
    except MadeToolError as exc:
        raise MadeToolError(_scrub(str(exc), secret)) from None
    except Exception as exc:
        raise MadeToolError(f"The request failed: {_scrub(type(exc).__name__, secret)}") from None
