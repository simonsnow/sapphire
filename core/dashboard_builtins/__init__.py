"""Built-in dashboard widgets.

Each widget is the metadata declaration here + a render module in web/.
register_all() is called at app boot from api_fastapi.py. To add a new
built-in: add another WidgetSpec below + matching web/{slug}.js render
module + bump nothing else.

Built-ins use plugin="core" so they can't collide with any user plugin name.
Render modules are served at /core-widgets/ via static mount.
"""
from core.dashboard_widgets import WidgetSpec, register_widget


_BUILTINS = [
    WidgetSpec(
        plugin="core", widget_id="system",
        name="System",
        description="Disk usage, memory, restart and shutdown.",
        icon="⚙️",
        sizes=["1x1"],
        default_size="1x1",
        render_url="/core-widgets/system.js",
    ),
    WidgetSpec(
        plugin="core", widget_id="updates",
        name="Updates",
        description="Sapphire version status and plugin updates.",
        icon="↗️",
        sizes=["1x1"],
        default_size="1x1",
        render_url="/core-widgets/updates.js",
    ),
    WidgetSpec(
        plugin="core", widget_id="backups",
        name="Backups",
        description="Backup count, size, schedule, quick actions.",
        icon="\U0001f4be",
        sizes=["1x1"],
        default_size="1x1",
        render_url="/core-widgets/backups.js",
    ),
    WidgetSpec(
        plugin="core", widget_id="maintenance",
        name="Maintenance",
        description="Uptime, app status, cleanup tools.",
        icon="\U0001f527",
        sizes=["1x1"],
        default_size="1x1",
        render_url="/core-widgets/maintenance.js",
    ),
    WidgetSpec(
        plugin="core", widget_id="mini-spotlight",
        name="Plugin Spotlight",
        description="Three randomly-rotating featured plugins.",
        icon="\U0001f6cd️",
        sizes=["1x1", "1x2", "1x4"],
        default_size="1x1",
        render_url="/core-widgets/mini-spotlight.js",
    ),
]


def register_all() -> None:
    """Register all built-in widgets with the central registry. Idempotent —
    safe to call multiple times (registry replaces prior entries)."""
    for spec in _BUILTINS:
        register_widget(spec)
