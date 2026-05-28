from AppKit import NSWorkspace
from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID

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

def main():
    info = get_active_window_info()
    print(info)

if __name__ == "__main__":
    main()