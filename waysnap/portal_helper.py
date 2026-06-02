#!/usr/bin/env python3
"""
WaySnap XDG Desktop Portal screenshot helper.

Runs as a subprocess so GLib's event loop does not conflict with Qt's.
Works on GNOME 42+, KDE Plasma 5.25+, and any compositor that ships
xdg-desktop-portal with a Screenshot backend.

Usage:  python3 portal_helper.py <output_path>
Exit:   0 — screenshot saved to <output_path>
        1 — failure (details on stderr)

Dependencies: python3-gi  (pre-installed on Ubuntu GNOME / Fedora GNOME / KDE)
"""

import shutil
import sys
from urllib.parse import unquote, urlparse

try:
    import gi
    gi.require_version("Gio",  "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib
except ImportError:
    print(
        "python3-gi not found — install with:  sudo apt install python3-gi",
        file=sys.stderr,
    )
    sys.exit(1)

if len(sys.argv) < 2:
    print("Usage: portal_helper.py <output_path>", file=sys.stderr)
    sys.exit(1)

out_path = sys.argv[1]
loop     = GLib.MainLoop()
saved    = [False]


def _on_response(_conn, _sender, _obj_path, _iface, _signal, params, _data):
    """Handle the portal's Response signal."""
    try:
        response_code, results = params.unpack()
        if response_code == 0 and "uri" in results:
            src = unquote(urlparse(results["uri"]).path)
            shutil.copy2(src, out_path)
            saved[0] = True
        elif response_code != 0:
            print(f"Portal denied/cancelled (code={response_code})", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"Response handler error: {exc}", file=sys.stderr)
    finally:
        loop.quit()


try:
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    # Build the expected request-handle object path.
    # Spec: /org/freedesktop/portal/desktop/request/{sender_token}/{handle_token}
    # sender_token = unique bus name with ':' stripped and '.' → '_'
    sender_tok = bus.get_unique_name().lstrip(":").replace(".", "_")
    handle_tok = "waysnap"
    expected_path = (
        f"/org/freedesktop/portal/desktop/request/{sender_tok}/{handle_tok}"
    )

    # Subscribe BEFORE calling Screenshot to avoid a race on the Response signal
    sub_id = bus.signal_subscribe(
        None,                              # match any sender
        "org.freedesktop.portal.Request",
        "Response",
        expected_path,
        None,
        Gio.DBusSignalFlags.NONE,
        _on_response,
        None,
    )

    proxy = Gio.DBusProxy.new_sync(
        bus,
        Gio.DBusProxyFlags.NONE,
        None,
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.Screenshot",
        None,
    )

    options = GLib.Variant(
        "a{sv}",
        {
            "handle_token": GLib.Variant("s", handle_tok),
            "interactive":  GLib.Variant("b", False),   # no area-picker dialog
        },
    )

    call_result = proxy.call_sync(
        "Screenshot",
        GLib.Variant("(sa{sv})", ("", options)),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )

    # The portal may return a slightly different handle path (older portal versions
    # may alter the token).  Re-subscribe on the actual handle to be safe.
    actual_path = call_result.unpack()[0]
    if actual_path != expected_path:
        print(
            f"Note: portal handle {actual_path!r} differs from expected "
            f"{expected_path!r}; re-subscribing",
            file=sys.stderr,
        )
        bus.signal_unsubscribe(sub_id)
        sub_id = bus.signal_subscribe(
            None,
            "org.freedesktop.portal.Request",
            "Response",
            actual_path,
            None,
            Gio.DBusSignalFlags.NONE,
            _on_response,
            None,
        )

    GLib.timeout_add_seconds(15, loop.quit)   # safety timeout
    loop.run()
    bus.signal_unsubscribe(sub_id)

except Exception as exc:  # noqa: BLE001
    print(f"Portal error: {exc}", file=sys.stderr)
    sys.exit(1)

sys.exit(0 if saved[0] else 1)
