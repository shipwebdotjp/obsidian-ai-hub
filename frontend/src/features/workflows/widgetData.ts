import { useEffect, useState } from "react";
import { apiGet, listAgents, listPeople } from "../../api/client";
import type { Agent, Person } from "../../api/types";
import type { Project } from "../projects/types";

let projectsPromise: Promise<Project[]> | null = null;
let peoplePromise: Promise<Person[]> | null = null;
let agentsPromise: Promise<Agent[]> | null = null;

/** Drop a failed cache entry so a later call can retry. */
function cached<T>(
  current: Promise<T> | null,
  loader: () => Promise<T>,
  store: (next: Promise<T> | null) => void,
): Promise<T> {
  if (current) return current;
  const next = loader().catch((error: unknown) => {
    store(null);
    throw error;
  });
  store(next);
  return next;
}

export function loadProjects(): Promise<Project[]> {
  return cached(
    projectsPromise,
    () => apiGet<Project[]>("/api/v1/projects"),
    (next) => {
      projectsPromise = next;
    },
  );
}

export function loadPeople(): Promise<Person[]> {
  return cached(
    peoplePromise,
    () => listPeople(),
    (next) => {
      peoplePromise = next;
    },
  );
}

export function loadAgents(): Promise<Agent[]> {
  return cached(
    agentsPromise,
    () => listAgents().then((response) => response.agents),
    (next) => {
      agentsPromise = next;
    },
  );
}

/** Test hook: drop the module-level caches. */
export function resetWidgetCaches(): void {
  projectsPromise = null;
  peoplePromise = null;
  agentsPromise = null;
}

/**
 * Load one option list for a widget, exposing an error flag so a failed fetch
 * is distinguishable from an empty registry.
 */
export function useWidgetOptions<T>(
  loader: () => Promise<T[]>,
): { options: T[]; failed: boolean } {
  const [options, setOptions] = useState<T[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    loader()
      .then((items) => {
        if (alive) setOptions(items);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
    // The loader is a stable module-level function.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { options, failed };
}
