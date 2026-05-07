"""Dashboard widget registry — built-ins and plugin widgets share this shape.

The registry is an in-memory map keyed by (plugin, widget_id). Built-ins
register at boot via core/dashboard_builtins/. Plugin widgets register
when the plugin loader processes their manifest. Both go through
register_widget(spec) — same contract.

Used by:
  - GET /api/dashboard/widgets/available  — picker catalog
  - dashboard.js host — fetches render_url for each user-placed panel
"""
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class WidgetSpec:
    """Declares a dashboard panel widget. Minimal V1 surface — fields will
    grow as the API adds capabilities (mood signals, etc.)."""
    plugin: str            # "core" for built-ins, plugin name otherwise
    widget_id: str         # unique within plugin
    name: str
    render_url: str        # browser fetches this for the render() function
    description: str = ""
    icon: str = ""
    sizes: list[str] = field(default_factory=lambda: ["1x1"])
    default_size: str = "1x1"
    multi_instance: bool = False
    settings_schema: list = field(default_factory=list)  # field defs auto-rendered as a settings form
    api_version: int = 1

    def to_public_dict(self) -> dict:
        """Shape sent to the frontend picker catalog."""
        return asdict(self)


# plugin_name -> widget_id -> spec
_registry: dict[str, dict[str, WidgetSpec]] = {}


def register_widget(spec: WidgetSpec) -> None:
    """Add a widget to the registry. Re-registering replaces the prior entry
    (so plugin hot-reload swaps cleanly). Warns on overwrite so cross-plugin
    name collisions are visible instead of silent. 2026-05-07."""
    bucket = _registry.setdefault(spec.plugin, {})
    if spec.widget_id in bucket:
        prev = bucket[spec.widget_id]
        # Same render_url is just a hot-reload — quiet. Different render_url
        # under same key suggests a collision worth surfacing.
        if prev.render_url != spec.render_url:
            logger.warning(
                f"[widgets] {spec.plugin}.{spec.widget_id} re-registered with "
                f"different render_url (was {prev.render_url!r}, now "
                f"{spec.render_url!r}) — possible plugin name collision"
            )
    bucket[spec.widget_id] = spec


def get_widget(plugin: str, widget_id: str) -> Optional[WidgetSpec]:
    return _registry.get(plugin, {}).get(widget_id)


def list_widgets() -> list[WidgetSpec]:
    """All registered widgets, in registration order within each plugin.
    Built-ins typically appear first because they register at app boot."""
    return [s for plug in _registry.values() for s in plug.values()]


def unregister_plugin_widgets(plugin: str) -> None:
    """Drop all widgets for a plugin. Called when a plugin unloads."""
    _registry.pop(plugin, None)
