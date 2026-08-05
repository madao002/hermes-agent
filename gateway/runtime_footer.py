"""Gateway runtime-metadata footer.

Renders a compact footer showing runtime state.
appends it to the FINAL message of an agent turn when enabled.

Config (~/.hermes/config.yaml)::

    display:
      runtime_footer:
        enabled: true
        fields: [status, response_time, model, io_tokens, context_pct]

Per-platform overrides live under ``display.platforms.<platform>.runtime_footer``.

Available fields:
    status        — 已完成
    response_time — 耗时 44.9s
    model         — bare model id, vendor prefix dropped
    io_tokens     — ↑ out / ↓ in
    cache_io      — 缓存 read/write
    context_pct   — 上下文 used/max (pct%)
    latency       — wall-clock duration (22s, 1m05s)
    cwd           — home-relative working dir
    context       — used/max tokens (no percent)

This is a merged build: it keeps the upstream v0.20.0 signature
(``cwd`` / ``turn_seconds``) for gateway/run.py callers AND the enhanced
fields (``status`` / ``response_time`` / ``io_tokens`` / ``context_pct``)
used by the local Feishu card footer, so all surfaces render the same rich
footer line.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Optional

_DEFAULT_FIELDS: tuple[str, ...] = ("status", "response_time", "model", "io_tokens", "cache_io", "context_pct")
_SEP = " · "


def _model_short(model: Optional[str]) -> str:
    """Drop ``vendor/`` prefix for readability."""
    if not model:
        return ""
    return model.rsplit("/", 1)[-1]


def _fmt_k(v: float) -> str:
    """Format a number as k-suffixed string (e.g. 48800 → 48.8k)."""
    if v is None:
        return "?"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}m"
    if v >= 1_000:
        return f"{v / 1_000:.1f}k"
    return str(int(v))


def _format_latency(seconds: float) -> str:
    """Wall-clock duration as ``22s`` / ``1m05s``."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


def _home_relative_cwd(cwd: str) -> str:
    """Collapse the user's home prefix to ``~``; empty input → ``~``."""
    if not cwd:
        return "~"
    try:
        home = os.path.expanduser("~")
        p = os.path.abspath(cwd)
        if home and (p == home or p.startswith(home + os.sep)):
            return "~" + p[len(home):]
        return p
    except Exception:
        return cwd


def resolve_footer_config(
    user_config: dict[str, Any] | None,
    platform_key: str | None = None,
) -> dict[str, Any]:
    """Resolve effective runtime-footer config for *platform_key*.

    Merge order (later wins):
        1. Built-in defaults (enabled=False)
        2. ``display.runtime_footer``
        3. ``display.platforms.<platform_key>.runtime_footer``
    """
    resolved = {"enabled": False, "fields": list(_DEFAULT_FIELDS)}
    cfg = (user_config or {}).get("display") or {}

    global_cfg = cfg.get("runtime_footer")
    if isinstance(global_cfg, dict):
        if "enabled" in global_cfg:
            resolved["enabled"] = bool(global_cfg.get("enabled"))
        if isinstance(global_cfg.get("fields"), list) and global_cfg["fields"]:
            resolved["fields"] = [str(f) for f in global_cfg["fields"]]

    if platform_key:
        platforms = cfg.get("platforms") or {}
        plat_cfg = platforms.get(platform_key)
        if isinstance(plat_cfg, dict):
            plat_footer = plat_cfg.get("runtime_footer")
            if isinstance(plat_footer, dict):
                if "enabled" in plat_footer:
                    resolved["enabled"] = bool(plat_footer.get("enabled"))
                if isinstance(plat_footer.get("fields"), list) and plat_footer["fields"]:
                    resolved["fields"] = [str(f) for f in plat_footer["fields"]]

    return resolved


def format_runtime_footer(
    *,
    model: Optional[str],
    context_tokens: int,
    context_length: Optional[int],
    response_time: Optional[float] = None,
    output_tokens: Optional[int] = None,
    input_tokens: Optional[int] = None,
    cache_read_tokens: Optional[int] = None,
    cache_write_tokens: Optional[int] = None,
    cwd: Optional[str] = None,
    turn_seconds: Optional[float] = None,
    fields: Iterable[str] = _DEFAULT_FIELDS,
) -> str:
    """Render the footer line, or return "" if no fields have data.

    Fields are skipped silently when their underlying data is missing.
    """
    parts: list[str] = []
    for field in fields:
        if field == "status":
            parts.append("已完成")
        elif field == "response_time":
            if response_time is not None:
                parts.append(f"耗时 {response_time:.1f}s")
        elif field == "model":
            m = _model_short(model)
            if m:
                parts.append(m)
        elif field == "io_tokens":
            out_k = _fmt_k(output_tokens) if output_tokens else None
            in_k = _fmt_k(input_tokens) if input_tokens else None
            if out_k and out_k != "?":
                parts.append(f"↑ {out_k}")
            if in_k and in_k != "?":
                parts.append(f"↓ {in_k}")
        elif field == "cache_io":
            # Cache-hit utilization as a percent: cache_read / total prompt
            # (total = fresh input + cache read + cache write, mirroring
            # DeepSeek's prompt_tokens = hit + miss).
            _denom = (input_tokens or 0) + (cache_read_tokens or 0) + (cache_write_tokens or 0)
            if cache_read_tokens and _denom > 0:
                _cache_pct = max(0, min(100, round((cache_read_tokens / _denom) * 100)))
                parts.append(f"缓存 {_cache_pct}%")
        elif field == "context_pct":
            if context_length and context_length > 0 and context_tokens >= 0:
                ctx_k = _fmt_k(context_tokens)
                len_k = _fmt_k(context_length)
                pct = max(0, min(100, round((context_tokens / context_length) * 100)))
                parts.append(f"上下文 {ctx_k}/{len_k} ({pct}%)")
        elif field == "context":
            if context_length and context_length > 0 and context_tokens >= 0:
                ctx_k = _fmt_k(context_tokens)
                len_k = _fmt_k(context_length)
                parts.append(f"上下文 {ctx_k}/{len_k}")
        elif field == "latency":
            # Wall-clock turn duration. Skipped when the caller supplied no
            # timing (call sites that don't measure) or the value is negative.
            if turn_seconds is not None and turn_seconds >= 0:
                parts.append(_format_latency(turn_seconds))
        elif field == "cwd":
            rel = _home_relative_cwd(cwd or os.environ.get("TERMINAL_CWD", ""))
            if rel:
                parts.append(rel)
        # Unknown field names are silently ignored.

    if not parts:
        return ""
    return _SEP.join(parts)


def build_footer_line(
    *,
    user_config: dict[str, Any] | None,
    platform_key: str | None,
    model: Optional[str],
    context_tokens: int,
    context_length: Optional[int],
    response_time: Optional[float] = None,
    output_tokens: Optional[int] = None,
    input_tokens: Optional[int] = None,
    cache_read_tokens: Optional[int] = None,
    cache_write_tokens: Optional[int] = None,
    cwd: Optional[str] = None,
    turn_seconds: Optional[float] = None,
) -> str:
    """Top-level entry point used by gateway/run.py and tui_gateway.

    Returns the footer text (empty string when disabled or no data).  Callers
    append this to the final response themselves, preserving a single blank
    line of separation.

    ``turn_seconds`` / ``response_time`` both feed the timing fields — the
    former drives ``latency`` (compact ``1m05s``), the latter ``response_time``
    (``耗时 44.9s``).  Callers that don't measure leave them ``None`` and the
    corresponding fields are skipped.
    """
    cfg = resolve_footer_config(user_config, platform_key)
    if not cfg.get("enabled"):
        return ""
    return format_runtime_footer(
        model=model,
        context_tokens=context_tokens,
        context_length=context_length,
        response_time=response_time,
        output_tokens=output_tokens,
        input_tokens=input_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cwd=cwd,
        turn_seconds=turn_seconds,
        fields=cfg.get("fields") or _DEFAULT_FIELDS,
    )
