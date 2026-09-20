"""The rules for an instance's own CLI arguments and environment
variables, shared by the create route and the settings route.

The values end up in the rendered Helm values and on the engine's
command line. The templates write every one of them as a JSON string, so
a value cannot add keys to the values; these rules cover what escaping
does not: names that are not names, and names the platform owns.
"""

import re

from utils.render_guard import has_line_break

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Set by the platform from Secrets. The charts append the instance's own
# variables after them and Kubernetes takes the last of a repeated name,
# so a user value would replace the workload credential (the gateway and
# LiteLLM then get 401, and an in-cluster caller gets in with a key of
# the user's choice) or the hub token.
RESERVED_ENV = frozenset({"VLLM_API_KEY", "HF_TOKEN", "HF_API_TOKEN"})

# The same credential as a vLLM argument.
RESERVED_ARGS = frozenset({"api-key"})

# Rendered into the chart's `config` block under these exact names, not
# as CLI arguments: another spelling would reach the command line next
# to the chart's own flag, and the row would not say what is served.
CONFIG_ARGS = {"max-model-len": "max_model_len", "port": "port"}


def valid_env_name(name: str) -> bool:
    """The one rule for a variable's name, also for names that come
    from outside (an imported MCP catalog entry)."""
    return bool(_ENV_NAME.match(name))


def canonical_arg(name: str) -> str:
    """One spelling per argument: no leading dashes, ``-`` for ``_``,
    lower case -- ``--max_model_len`` and ``max-model-len`` are one."""
    return name.strip().lstrip("-").replace("_", "-").lower()


def validate_settings(args: dict[str, str], env_vars: dict[str, str]) -> None:
    """Raise ``ValueError`` with a sentence for the user."""
    for kind, values in (("argument", args), ("variable", env_vars)):
        for name, value in values.items():
            if has_line_break(value):
                raise ValueError(
                    f"The value of the {kind} {name} contains a line break"
                )
    for name, value in args.items():
        if not name or re.search(r"\s", name):
            raise ValueError(
                f"'{name}' is not an argument name: no spaces, not empty"
            )
        canonical = canonical_arg(name)
        if canonical in RESERVED_ARGS:
            raise ValueError(f"The argument {name} is set by the platform")
        exact = CONFIG_ARGS.get(canonical)
        if exact is not None:
            if name != exact:
                raise ValueError(f"Set {exact} in its own row, not as {name}")
            if not value.isdigit():
                raise ValueError(f"{exact} is a whole number")
    for name in env_vars:
        if not _ENV_NAME.match(name):
            raise ValueError(f"'{name}' is not an environment variable name")
        if name in RESERVED_ENV:
            raise ValueError(
                f"The environment variable {name} is set by the platform"
            )
