import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { resolvePageTitle } from "../constants/pageTitles";

/**
 * Keep the browser tab title in sync with the open screen.
 * Must be used inside a Router. Runs before any auth gating so the
 * standalone title is shown on the token prompt and error screens too.
 */
export function useDocumentTitle(): void {
  const { pathname } = useLocation();
  useEffect(() => {
    document.title = resolvePageTitle(pathname);
  }, [pathname]);
}
