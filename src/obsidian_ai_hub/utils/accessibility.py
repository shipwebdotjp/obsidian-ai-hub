import json
import logging
import re

from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCopyAttributeNames,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    kAXChildrenAttribute,
    kAXDescriptionAttribute,
    kAXEnabledAttribute,
    kAXFocusedAttribute,
    kAXColumnsAttribute,
    kAXPositionAttribute,
    kAXRoleAttribute,
    kAXRowsAttribute,
    kAXSelectedChildrenAttribute,
    kAXSizeAttribute,
    kAXSubroleAttribute,
    kAXVisibleChildrenAttribute,
    kAXTitleAttribute,
    kAXValueAttribute,
    kAXWindowsAttribute,
)
from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGNullWindowID,
    kCGWindowListOptionOnScreenOnly,
)

logger = logging.getLogger(__name__)
INTERESTING_AX_ROLES = {
    "AXList",
    "AXOutline",
    "AXTable",
    "AXRow",
    "AXCell",
    "AXStaticText",
}
TARGET_AX_ROLES = {"AXRow"}
TEXT_AX_ATTRIBUTES = (kAXTitleAttribute, kAXValueAttribute, kAXDescriptionAttribute)
TRAVERSAL_AX_ATTRIBUTES = (
    kAXWindowsAttribute,
    kAXChildrenAttribute,
    kAXVisibleChildrenAttribute,
    kAXSelectedChildrenAttribute,
    kAXRowsAttribute,
    kAXColumnsAttribute,
)


def _convert_nsdictionary_to_python_dict(ns_dict):
    """
    Converts an Objective-C NSDictionary object to a standard Python dictionary.
    Recursively converts nested NSDictionaries.
    """
    if not hasattr(ns_dict, "allKeys") or not hasattr(ns_dict, "objectForKey_"):
        return ns_dict  # Not an NSDictionary, return as is

    py_dict = {}
    for key in ns_dict.allKeys():
        value = ns_dict.objectForKey_(key)
        py_dict[str(key)] = _convert_nsdictionary_to_python_dict(
            value
        )  # Recursive call
    return py_dict


def _convert_ax_value(value):
    """
    Convert common Objective-C / CoreFoundation values into JSON-friendly Python values.
    """
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if isinstance(value, (list, tuple)):
        return [_convert_ax_value(item) for item in value]

    if (
        hasattr(value, "__iter__")
        and hasattr(value, "__len__")
        and not isinstance(value, (str, bytes, bytearray, dict))
    ):
        try:
            items = list(value)
        except TypeError:
            items = None
        if items is not None:
            return [_convert_ax_value(item) for item in items]

    if hasattr(value, "allKeys") and hasattr(value, "objectForKey_"):
        return _convert_nsdictionary_to_python_dict(value)

    if hasattr(value, "x") and hasattr(value, "y") and not hasattr(value, "width"):
        return {"x": value.x, "y": value.y}

    if hasattr(value, "width") and hasattr(value, "height"):
        result = {"width": value.width, "height": value.height}
        if hasattr(value, "origin") and hasattr(value, "size"):
            result["origin"] = _convert_ax_value(value.origin)
            result["size"] = _convert_ax_value(value.size)
        return result

    return str(value)


def _copy_ax_attribute_value(element, attribute_name):
    """
    Safely read an accessibility attribute.
    PyObjC bindings typically return (error, value) when the out parameter is None.
    """
    try:
        result = AXUIElementCopyAttributeValue(element, attribute_name, None)
    except TypeError:
        result = AXUIElementCopyAttributeValue(element, attribute_name)

    if isinstance(result, tuple):
        if len(result) == 2:
            error, value = result
            if error == 0:
                return value
            return None
        if len(result) == 1:
            return result[0]

    if result == 0:
        return None

    return result


def _copy_ax_attribute_names(element):
    """
    Return the list of supported accessibility attributes for the element.
    """
    try:
        result = AXUIElementCopyAttributeNames(element, None)
    except TypeError:
        result = AXUIElementCopyAttributeNames(element)

    if isinstance(result, tuple):
        if len(result) == 2:
            error, names = result
            if error == 0:
                return names or []
            return []
        if len(result) == 1:
            return result[0] or []

    if result == 0:
        return []

    return result or []


def _to_python_ax_children(value):
    """
    Normalize AX attribute values like NSArray into plain Python lists.
    """
    if value is None:
        return []
    if isinstance(value, tuple):
        return [_convert_ax_value(item) for item in value]
    if isinstance(value, list):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        return [value]
    if hasattr(value, "__iter__") and hasattr(value, "__len__"):
        try:
            return list(value)
        except TypeError:
            return [value]
    return [value]


def _get_ax_role(element):
    """
    Read AXRole as a plain Python string when possible.
    """
    value = _copy_ax_attribute_value(element, kAXRoleAttribute)
    if value is None:
        return None
    converted = _convert_ax_value(value)
    return converted if isinstance(converted, str) else str(converted)


def _collect_ax_elements_by_role(
    element, target_roles, depth=0, max_depth=6, max_matches=200, visited=None
):
    """
    Traverse the AX tree and collect only elements whose AXRole matches target_roles.
    """
    if element is None:
        return []

    if visited is None:
        visited = set()

    element_id = id(element)
    if element_id in visited:
        return []

    visited.add(element_id)

    matches = []
    role = _get_ax_role(element)
    if role in target_roles:
        matches.append(element)
        if len(matches) >= max_matches:
            return matches

    if depth >= max_depth:
        return matches

    for child_attribute in TRAVERSAL_AX_ATTRIBUTES:
        children = _copy_ax_attribute_value(element, child_attribute)
        if not children:
            continue

        for child in _to_python_ax_children(children):
            matches.extend(
                _collect_ax_elements_by_role(
                    child,
                    target_roles=target_roles,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_matches=max_matches - len(matches),
                    visited=visited,
                )
            )
            if len(matches) >= max_matches:
                return matches[:max_matches]

    return matches


def _find_first_ax_element_by_role(
    element, target_roles, depth=0, max_depth=6, visited=None
):
    """
    Traverse the AX tree and return the first element whose AXRole matches target_roles.
    """
    if element is None:
        return None

    if visited is None:
        visited = set()

    element_id = id(element)
    if element_id in visited:
        return None

    visited.add(element_id)

    role = _get_ax_role(element)
    if role in target_roles:
        return element

    if depth >= max_depth:
        return None

    for child_attribute in TRAVERSAL_AX_ATTRIBUTES:
        children = _copy_ax_attribute_value(element, child_attribute)
        if not children:
            continue

        for child in _to_python_ax_children(children):
            found = _find_first_ax_element_by_role(
                child,
                target_roles=target_roles,
                depth=depth + 1,
                max_depth=max_depth,
                visited=visited,
            )
            if found is not None:
                return found

    return None


def _find_first_ax_row_with_text(element, depth=0, max_depth=8, visited=None):
    """
    Traverse the AX tree and return the first AXRow that yields any text fragments.
    """
    if element is None:
        return None, []

    if visited is None:
        visited = set()

    element_id = id(element)
    if element_id in visited:
        return None, []

    visited.add(element_id)

    role = _get_ax_role(element)
    if role == "AXRow":
        fragments = _extract_text_fragments(element, max_depth=max_depth)
        if fragments:
            return element, fragments

    if depth >= max_depth:
        return None, []

    for child_attribute in TRAVERSAL_AX_ATTRIBUTES:
        children = _copy_ax_attribute_value(element, child_attribute)
        if not children:
            continue

        for child in _to_python_ax_children(children):
            found_element, fragments = _find_first_ax_row_with_text(
                child,
                depth=depth + 1,
                max_depth=max_depth,
                visited=visited,
            )
            if found_element is not None:
                return found_element, fragments

    return None, []


def _extract_text_fragments(element, depth=0, max_depth=6, visited=None):
    """
    Gather text-like strings from an AX subtree.
    """
    if element is None:
        return []

    if visited is None:
        visited = set()

    element_id = id(element)
    if element_id in visited:
        return []

    visited.add(element_id)

    fragments = []
    for attribute_name in TEXT_AX_ATTRIBUTES:
        value = _copy_ax_attribute_value(element, attribute_name)
        if value is None:
            continue
        converted = _convert_ax_value(value)
        if isinstance(converted, str):
            text = converted.strip()
            if text:
                fragments.append(text)

    if depth >= max_depth:
        return fragments

    for child_attribute in TRAVERSAL_AX_ATTRIBUTES:
        children = _copy_ax_attribute_value(element, child_attribute)
        if not children:
            continue

        for child in _to_python_ax_children(children):
            fragments.extend(
                _extract_text_fragments(
                    child,
                    depth=depth + 1,
                    max_depth=max_depth,
                    visited=visited,
                )
            )

    return fragments


def _parse_ax_point_string(value):
    """
    Parse a stringified AXValue point like '... x:97.000000 y:156.000000 ...'.
    """
    converted = _convert_ax_value(value)
    if not isinstance(converted, str):
        return None

    match = re.search(r"x:([-\d.]+)\s+y:([-\d.]+)", converted)
    if not match:
        return None

    return {"x": float(match.group(1)), "y": float(match.group(2))}


def _parse_ax_size_string(value):
    """
    Parse a stringified AXValue size like '... w:489.000000 h:71.000000 ...'.
    """
    converted = _convert_ax_value(value)
    if not isinstance(converted, str):
        return None

    match = re.search(r"w:([-\d.]+)\s+h:([-\d.]+)", converted)
    if not match:
        return None

    return {"width": float(match.group(1)), "height": float(match.group(2))}


def _get_ax_geometry(element):
    """
    Return parsed position/size data when available.
    """
    position = _copy_ax_attribute_value(element, kAXPositionAttribute)
    size = _copy_ax_attribute_value(element, kAXSizeAttribute)
    point = _parse_ax_point_string(position)
    dimensions = _parse_ax_size_string(size)
    return {
        "x": point["x"] if point else None,
        "y": point["y"] if point else None,
        "width": dimensions["width"] if dimensions else None,
        "height": dimensions["height"] if dimensions else None,
    }


def _get_ax_text_signal_score(element, max_text_depth=8):
    """
    Score how likely this AXRow carries user-facing text.
    """
    score = 0

    for attribute_name in (
        "AXTitle",
        "AXValue",
        "AXDescription",
        "AXHelp",
        "AXSelectedText",
    ):
        value = _copy_ax_attribute_value(element, attribute_name)
        converted = _convert_ax_value(value)
        if isinstance(converted, str) and converted.strip():
            score += 3

    number_of_characters = _copy_ax_attribute_value(element, "AXNumberOfCharacters")
    if isinstance(number_of_characters, (int, float)) and number_of_characters > 0:
        score += 2

    for attribute_name in ("AXSelectedTextRange", "AXVisibleCharacterRange"):
        value = _copy_ax_attribute_value(element, attribute_name)
        converted = _convert_ax_value(value)
        if isinstance(converted, str):
            match = re.search(r"length:(\d+)", converted)
            if match and int(match.group(1)) > 0:
                score += 1

    fragments = _extract_text_fragments(element, max_depth=max_text_depth)
    if fragments:
        score += 4

    return score, fragments


def _rects_intersect(left, right, padding=0.0):
    """
    Return True when two rectangles intersect.
    Rectangles are dicts with x, y, width, height keys.
    """
    if not left or not right:
        return False

    left_x = left.get("x")
    left_y = left.get("y")
    left_w = left.get("width")
    left_h = left.get("height")
    right_x = right.get("x")
    right_y = right.get("y")
    right_w = right.get("width")
    right_h = right.get("height")

    if None in (left_x, left_y, left_w, left_h, right_x, right_y, right_w, right_h):
        return False

    left_right = left_x + left_w + padding
    right_right = right_x + right_w + padding
    left_bottom = left_y + left_h + padding
    right_bottom = right_y + right_h + padding

    return not (
        left_right < right_x - padding
        or right_right < left_x - padding
        or left_bottom < right_y - padding
        or right_bottom < left_y - padding
    )


def _select_best_ax_row(rows, max_text_depth=8):
    """
    Prefer the first visible AXRow that exposes text fragments.
    Falls back to the first visible AXRow, then the first collected AXRow.
    """
    if not rows:
        return None, []

    visible_rows = []
    fallback_rows = []
    sidebar_rows = []

    for row in rows:
        geometry = _get_ax_geometry(row)
        fallback_rows.append((row, geometry))

        y = geometry.get("y")
        height = geometry.get("height")
        if y is None or height is None:
            continue
        if y < 0 or height <= 0:
            continue
        visible_rows.append((row, geometry))
        x = geometry.get("x")
        width = geometry.get("width")
        if (
            x is not None
            and width is not None
            and x <= 550
            and width <= 700
            and 20 <= height <= 150
        ):
            sidebar_rows.append((row, geometry))

    if not visible_rows:
        visible_rows = fallback_rows

    candidate_rows = sidebar_rows if sidebar_rows else visible_rows
    candidate_rows = sorted(
        candidate_rows,
        key=lambda item: (
            item[1].get("y") if item[1].get("y") is not None else float("inf"),
            item[1].get("x") if item[1].get("x") is not None else float("inf"),
        ),
    )

    best_scored = None
    for row, _geometry in candidate_rows:
        score, fragments = _get_ax_text_signal_score(row, max_text_depth=max_text_depth)
        if score > 0:
            return row, list(dict.fromkeys(fragments))
        if best_scored is None:
            best_scored = (row, fragments)

    if best_scored is not None:
        row, fragments = best_scored
        return row, list(dict.fromkeys(fragments))

    first_row, _geometry = candidate_rows[0]
    return first_row, list(
        dict.fromkeys(_extract_text_fragments(first_row, max_depth=max_text_depth))
    )


def _summarize_ax_rows(rows, limit=10, max_text_depth=8):
    """
    Build a compact summary for a small number of AXRow candidates.
    """
    summaries = []
    visible_rows = []

    for row in rows:
        geometry = _get_ax_geometry(row)
        y = geometry.get("y")
        height = geometry.get("height")
        x = geometry.get("x")
        width = geometry.get("width")
        if y is None or height is None or y < 0 or height <= 0:
            continue
        if (
            x is not None
            and width is not None
            and x <= 550
            and width <= 700
            and 20 <= height <= 150
        ):
            visible_rows.append((row, geometry))

    if not visible_rows:
        fallback_rows = []
        for row in rows:
            geometry = _get_ax_geometry(row)
            if geometry.get("y") is not None:
                fallback_rows.append((row, geometry))
        visible_rows = fallback_rows[:limit]

    visible_rows = sorted(
        visible_rows,
        key=lambda item: (
            item[1].get("y") if item[1].get("y") is not None else float("inf"),
            item[1].get("x") if item[1].get("x") is not None else float("inf"),
        ),
    )

    for index, (row, geometry) in enumerate(visible_rows[:limit]):
        score, fragments = _get_ax_text_signal_score(row, max_text_depth=max_text_depth)
        summaries.append(
            {
                "index": index,
                "geometry": geometry,
                "text_signal_score": score,
                "text_fragments": list(dict.fromkeys(fragments))[:5],
                "repr": str(row),
            }
        )

    return summaries


def _describe_ax_element(element, depth=0, max_depth=2, max_children=20, visited=None):
    """
    Recursively describe an AXUIElement tree for debugging.
    """
    if visited is None:
        visited = set()

    element_id = id(element)
    if element_id in visited:
        return {"_cycle": True, "repr": str(element)}

    visited.add(element_id)

    attribute_names = _copy_ax_attribute_names(element)
    description = {
        "repr": str(element),
        "attribute_names": [_convert_ax_value(name) for name in attribute_names],
        "attributes": {},
    }

    for attribute_name in (
        kAXRoleAttribute,
        kAXSubroleAttribute,
        kAXTitleAttribute,
        kAXDescriptionAttribute,
        kAXValueAttribute,
        kAXEnabledAttribute,
        kAXFocusedAttribute,
        kAXPositionAttribute,
        kAXSizeAttribute,
    ):
        value = _copy_ax_attribute_value(element, attribute_name)
        if value is not None:
            description["attributes"][str(attribute_name)] = _convert_ax_value(value)

    role = description["attributes"].get(str(kAXRoleAttribute))
    if role in INTERESTING_AX_ROLES:
        description["_interesting_role"] = True

    if depth >= max_depth:
        return description

    for child_attribute in TRAVERSAL_AX_ATTRIBUTES:
        children = _copy_ax_attribute_value(element, child_attribute)
        if not children:
            continue

        children = _to_python_ax_children(children)

        child_items = []
        for child in list(children)[:max_children]:
            child_items.append(
                _describe_ax_element(
                    child,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_children=max_children,
                    visited=visited,
                )
            )

        description[str(child_attribute)] = child_items
        if len(children) > max_children:
            description[f"{str(child_attribute)}_truncated"] = (
                len(children) - max_children
            )

    return description


def get_active_window_info():
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    pid = app.processIdentifier()
    app_name = app.localizedName()

    window_title = None
    windows = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly, kCGNullWindowID
    )
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
    windows = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly, kCGNullWindowID
    )
    results = []
    for w in windows:
        results.append(
            {
                "window_id": w.get("kCGWindowNumber"),
                "window_title": w.get("kCGWindowName"),
                "bounds": _convert_nsdictionary_to_python_dict(
                    w.get("kCGWindowBounds")
                ),
                "is_onscreen": w.get("kCGWindowIsOnscreen"),
                "alpha": w.get("kCGWindowAlpha"),
                "layer": w.get("kCGWindowLayer"),
                "owner_name": w.get("kCGWindowOwnerName"),
                "owner_pid": w.get("kCGWindowOwnerPID"),
            }
        )
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


def get_line_accessibility_debug_info(line_window=None, max_depth=2, max_children=20):
    """
    Return a debug dump of LINE's accessibility tree.
    """
    if line_window is None:
        line_window = get_line_window()
    if not line_window:
        return None

    pid = line_window.get("owner_pid")
    if pid is None:
        return {
            "window": line_window,
            "error": "LINE window was found, but owner_pid is missing",
        }

    try:
        app_element = AXUIElementCreateApplication(pid)
        app_windows = _copy_ax_attribute_value(app_element, kAXWindowsAttribute)
        app_windows = _to_python_ax_children(app_windows)
        first_window_element = app_windows[0] if app_windows else None
        ax_rows = _collect_ax_elements_by_role(
            first_window_element,
            TARGET_AX_ROLES,
            max_depth=max_depth + 8,
            max_matches=150,
        )
        row_scan_summary = _summarize_ax_rows(
            ax_rows,
            limit=10,
            max_text_depth=max_depth + 10,
        )
        target_row_element, target_row_fragments = _select_best_ax_row(
            ax_rows,
            max_text_depth=max_depth + 10,
        )
        target_row_geometry = (
            _get_ax_geometry(target_row_element)
            if target_row_element is not None
            else None
        )
        target_row_children = []
        target_row_child_fragments = []
        if target_row_element is not None:
            children = _copy_ax_attribute_value(
                target_row_element, kAXChildrenAttribute
            )
            for child in _to_python_ax_children(children)[:max_children]:
                target_row_children.append(
                    _describe_ax_element(
                        child,
                        max_depth=max_depth + 2,
                        max_children=max_children,
                    )
                )
                target_row_child_fragments.extend(
                    _extract_text_fragments(
                        child,
                        max_depth=max_depth + 10,
                    )
                )
        static_text_elements = _collect_ax_elements_by_role(
            first_window_element,
            {"AXStaticText"},
            max_depth=max_depth + 10,
            max_matches=300,
        )
        associated_text_elements = []
        associated_text_fragments = []
        for text_element in static_text_elements:
            text_geometry = _get_ax_geometry(text_element)
            if not _rects_intersect(target_row_geometry, text_geometry, padding=8.0):
                continue
            text_fragments = _extract_text_fragments(
                text_element,
                max_depth=max_depth + 10,
            )
            if not text_fragments:
                continue
            associated_text_elements.append(
                {
                    "geometry": text_geometry,
                    "text_fragments": list(dict.fromkeys(text_fragments)),
                    "summary": _describe_ax_element(
                        text_element,
                        max_depth=max_depth + 2,
                        max_children=max_children,
                    ),
                }
            )
            associated_text_fragments.extend(text_fragments)
        app_accessibility = _describe_ax_element(
            app_element,
            max_depth=max_depth,
            max_children=max_children,
        )
        first_window_accessibility = (
            _describe_ax_element(
                first_window_element,
                max_depth=max_depth + 1,
                max_children=max_children,
            )
            if first_window_element is not None
            else None
        )
        target_row_accessibility = (
            _describe_ax_element(
                target_row_element,
                max_depth=max_depth + 4,
                max_children=max_children,
            )
            if target_row_element is not None
            else None
        )
    except Exception as exc:
        return {
            "window": line_window,
            "pid": pid,
            "error": f"Failed to inspect accessibility tree: {exc}",
        }

    return {
        "window": line_window,
        "pid": pid,
        "focus": {
            "window_count": len(app_windows) if "app_windows" in locals() else None,
            "first_window_repr": str(first_window_element)
            if "first_window_element" in locals() and first_window_element is not None
            else None,
            "row_count": len(ax_rows) if "ax_rows" in locals() else None,
            "target_row_found": target_row_element is not None
            if "target_row_element" in locals()
            else None,
        },
        "app_accessibility": app_accessibility,
        "first_window_accessibility": first_window_accessibility,
        "target_row_accessibility": target_row_accessibility,
        "target_row_text_fragments": list(dict.fromkeys(target_row_fragments))
        if "target_row_fragments" in locals()
        else None,
        "target_row_children_accessibility": target_row_children
        if "target_row_children" in locals()
        else None,
        "target_row_child_text_fragments": list(
            dict.fromkeys(target_row_child_fragments)
        )
        if "target_row_child_fragments" in locals()
        else None,
        "target_row_geometry": target_row_geometry
        if "target_row_geometry" in locals()
        else None,
        "target_row_associated_text_elements": associated_text_elements
        if "associated_text_elements" in locals()
        else None,
        "target_row_associated_text_fragments": list(
            dict.fromkeys(associated_text_fragments)
        )
        if "associated_text_fragments" in locals()
        else None,
        "row_scan_summary": row_scan_summary
        if "row_scan_summary" in locals()
        else None,
    }


def main():
    print("Active Window Info:")
    print(get_active_window_info())
    print("\nLine Window:")
    line_window = get_line_window()
    logger.debug(
        "Full accessibility info for LINE window: %s",
        json.dumps(line_window, ensure_ascii=False, indent=2)
        if line_window
        else "None",
    )

    print("\nLINE Accessibility Debug:")
    debug_info = get_line_accessibility_debug_info(line_window=line_window)
    logger.debug(
        "LINE accessibility debug dump: %s",
        json.dumps(debug_info, ensure_ascii=False, indent=2) if debug_info else "None",
    )


if __name__ == "__main__":
    # デバッグログを表示するためにレベルを変更
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    main()
