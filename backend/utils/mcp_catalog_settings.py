"""The settings of an MCP catalog entry: their one shape, and the check
of what an admin fills against it.

A setting is an environment variable of the pod, or, with ``flag``, a
switch that adds one argument. Names come from the catalog entry only:
a deploy cannot add a variable of its own, so nothing reaches the pod
that the entry's reviewer did not see.
"""

from utils.instance_settings import valid_env_name

TRUE_VALUES = ("true", "1", "yes", "on")
# A value of one of these runs code of its author's choice in the pod.
LOADER_NAMES = frozenset(
    {
        "PATH",
        "NODE_OPTIONS",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONHOME",
        "BASH_ENV",
        "ENV",
        "JAVA_TOOL_OPTIONS",
        "PERL5OPT",
        "RUBYOPT",
    }
)
MAX_VALUE = 4096


class SettingsError(ValueError):
    """What an admin filled does not fit the entry; safe to show."""


def normal_setting(item: dict) -> dict:
    """One setting of a catalog entry in its stored shape."""
    name = str(item.get("name") or "")
    if not valid_env_name(name):
        raise SettingsError(f"{name!r} is no usable setting name")
    if name.upper() in LOADER_NAMES or name.upper().startswith("LD_"):
        raise SettingsError(
            f"{name} changes how the image's programs are loaded; it is "
            "no setting of an MCP server"
        )
    secret = bool(item.get("secret"))
    flag = item.get("flag")
    if secret and flag:
        raise SettingsError(f"{name}: a switch has no secret value")
    default = item.get("default")
    return {
        "name": name,
        "label": str(item.get("label") or name),
        "help": str(item.get("help") or ""),
        "secret": secret,
        "required": bool(item.get("required")),
        "flag": str(flag) if flag else None,
        # A secret never has a default: the catalog is served to members.
        "default": None if secret or default is None else str(default),
    }


def is_on(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def split_settings(
    schema: list[dict],
    given: dict[str, str],
    *,
    kept_secrets: frozenset[str] = frozenset(),
) -> tuple[dict[str, str], dict[str, str]]:
    """``(plain, secret)`` values of a deploy or a settings change,
    checked against the entry. ``kept_secrets`` are secret settings
    that already have a value: leaving one out keeps it."""
    known = {s["name"]: s for s in schema}
    unknown = sorted(set(given) - set(known))
    if unknown:
        raise SettingsError(
            f"This server has no setting named {', '.join(unknown)}"
        )
    plain: dict[str, str] = {}
    secret: dict[str, str] = {}
    for name, setting in known.items():
        value = given.get(name)
        if value is not None and not isinstance(value, str):
            raise SettingsError(f"{name} must be text")
        value = (value or "").strip()
        if len(value) > MAX_VALUE:
            raise SettingsError(f"{name} is too long")
        if "\n" in value or "\r" in value:
            raise SettingsError(f"{name} must be one line")
        if not value and not setting["secret"]:
            value = setting.get("default") or ""
        if not value:
            if setting["required"] and name not in kept_secrets:
                raise SettingsError(f"{setting['label']} is required")
            continue
        (secret if setting["secret"] else plain)[name] = value
    return plain, secret


def render_args(
    args: list[str], schema: list[dict], plain: dict[str, str], **places: str
) -> list[str]:
    """The container's arguments: the entry's, with ``{host}``,
    ``{port}`` and ``{path}`` filled, plus the flag of each switch that
    is on. A switch is never an environment variable."""
    rendered = []
    for arg in args:
        for key, value in places.items():
            arg = arg.replace(f"{{{key}}}", value)
        rendered.append(arg)
    for setting in schema:
        if setting.get("flag") and is_on(plain.get(setting["name"])):
            rendered.append(setting["flag"])
    return rendered


def env_values(schema: list[dict], plain: dict[str, str]) -> dict[str, str]:
    """The plain environment of the pod: every filled setting that is
    no switch."""
    flags = {s["name"] for s in schema if s.get("flag")}
    return {k: v for k, v in plain.items() if k not in flags}
