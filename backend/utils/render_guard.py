"""One rule in front of every values template: no string with a line
break.

The templates are YAML text. A value that matters is written with
``tojson``; the rest (names, quantities, flags from the platform's own
tables) is written as it is. On one line such a value can at worst break
the YAML or turn its own key into a mapping; with a line break it starts
new keys, which is how a value once set ``image`` and
``securityContext`` on a release. Refusing the line break at the render
step covers every template and every route at once, including a value
that was stored before a route validated it.
"""

# str.splitlines() boundaries, which is also what YAML treats as breaks.
_BREAKS = "\n\r\x0b\x0c\x1c\x1d\x1e\x85  "


def has_line_break(value: str) -> bool:
    return any(ch in value for ch in _BREAKS)


def refuse_line_breaks(context, path: str = "") -> None:
    """Walk a template context; ``ValueError`` names the first string
    (key or value) that holds a line break."""
    if isinstance(context, str):
        if has_line_break(context):
            raise ValueError(f"{path or 'a value'} contains a line break")
    elif isinstance(context, dict):
        for key, value in context.items():
            refuse_line_breaks(key, f"{path}.{key}".lstrip("."))
            refuse_line_breaks(value, f"{path}.{key}".lstrip("."))
    elif isinstance(context, (list, tuple, set, frozenset)):
        for index, value in enumerate(context):
            refuse_line_breaks(value, f"{path}[{index}]")
