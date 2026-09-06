import { useEffect, useState } from "react";
import { listCodingProjects, type CodingProjectItem } from "../../../api/coding";
import { selectValidProjects } from "../utils/codingSelectors";

interface UseCodingProjectsOptions {
  onError: (message: string | null) => void;
}

/** プロジェクト一覧の取得と選択状態を管理する。 */
export function useCodingProjects({ onError }: UseCodingProjectsOptions) {
  const [projects, setProjects] = useState<CodingProjectItem[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [loadingProjects, setLoadingProjects] = useState(true);

  const loadProjects = async () => {
    setLoadingProjects(true);
    onError(null);
    try {
      const data = await listCodingProjects();
      setProjects(data);
      const valid = selectValidProjects(data);
      if (valid.length > 0) {
        if (selectedProjectId === null || !valid.some((v) => v.project.project_id === selectedProjectId)) {
          setSelectedProjectId(valid[0].project.project_id);
        }
      } else {
        setSelectedProjectId(null);
      }
    } catch (e: any) {
      onError(e.message || "プロジェクト一覧の取得に失敗しました");
    } finally {
      setLoadingProjects(false);
    }
  };

  // Load projects on mount
  useEffect(() => {
    loadProjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    projects,
    selectedProjectId,
    setSelectedProjectId,
    loadingProjects,
    loadProjects,
  };
}
