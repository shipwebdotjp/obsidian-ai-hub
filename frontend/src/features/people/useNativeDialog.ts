import { useEffect, type RefObject } from "react";

/**
 * Minimal native-dialog behavior shared by the people modals.
 *
 * - Opens with `showModal()` on mount (guarded with `!dialog.open`, same as
 *   `DeletePersonDialog`).
 * - Moves initial focus to `[data-autofocus]` or the first focusable control.
 * - Restores focus to the element that was focused before opening, on unmount.
 *
 * Callers wire `onClose` to the dialog `onClose` event and add an explicit
 * Escape `onKeyDown` so the behavior is also observable under jsdom, where
 * the native cancel/close sequence does not run.
 */
export function useNativeDialog(
  dialogRef: RefObject<HTMLDialogElement | null>,
  onClose: () => void,
  openFlag: boolean = true,
) {
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || dialog.open) return;
    const trigger =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    const autofocusTarget =
      dialog.querySelector<HTMLElement>("[data-autofocus]");
    const firstControl = dialog.querySelector<HTMLElement>(
      "input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])"
    );
    (autofocusTarget ?? firstControl)?.focus();
    return () => {
      if (dialog.open) {
        dialog.close();
      }
      trigger?.focus();
    };
    // Re-run only when the open flag flips (conditionally rendered dialogs);
    // dialog identity and onClose are stable for one open session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openFlag]);
}
