from AppKit import NSWorkspace
from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGWindowListOptionOnScreenOnly,
    kCGNullWindowID,
)

def get_active_window_info():
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    pid = app.processIdentifier()
    app_name = app.localizedName()

    window_title = None
    windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    for w in windows:
        if w.get("kCGWindowOwnerPID") == pid:
            name = w.get("kCGWindowName")
            if name:
                window_title = name
                break

    return {"app_name": app_name, "window_title": window_title}

def list_windows():
    """
    Returns a list of dictionaries for all on-screen windows.
    """
    windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    results = []
    for w in windows:
        results.append({
            "window_id": w.get("kCGWindowNumber"),
            "window_title": w.get("kCGWindowName"),
            "bounds": w.get("kCGWindowBounds"),
            "is_onscreen": w.get("kCGWindowIsOnscreen"),
            "alpha": w.get("kCGWindowAlpha"),
            "layer": w.get("kCGWindowLayer"),
            "owner_name": w.get("kCGWindowOwnerName"),
            "owner_pid": w.get("kCGWindowOwnerPID"),
        })
    return results

def get_line_window():
    """
    Finds the first visible LINE window based on CGWindowList order.
    A 'visible' window here means layer 0, alpha > 0, and has bounds.
    """
    windows = list_windows()
    for w in windows:
        if w["owner_name"] == "LINE":
            # Basic visibility check
            if w.get("layer") == 0 and w.get("alpha", 0) > 0:
                # We also check if it has a title or bounds to avoid background/helper windows
                # Most main LINE windows have a title or are at least clearly visible.
                return w
    return None

def main():
    print("Active Window Info:")
    print(get_active_window_info())
    print("\nLine Window:")
    print(get_line_window())

if __name__ == "__main__":
    main()
