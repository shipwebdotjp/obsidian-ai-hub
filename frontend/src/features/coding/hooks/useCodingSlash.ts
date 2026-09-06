import { useEffect, useMemo, useState, type MutableRefObject } from "react";
import {
  getSlashCandidates,
  type SlashCandidate,
  type SlashInvocation,
} from "../../../api/coding";

interface UseCodingSlashOptions {
  selectedSessionIdRef: MutableRefObject<string | null>;
  /** パレット表示判定の入力元（プロンプト下書き draft）。 */
  inputContent: string;
  /** 候補確定時に入力欄をクリアするためのコールバック。 */
  clearInput: () => void;
}

/** スラッシュ呼び出し候補パレットの状態と取得処理を管理する。 */
export function useCodingSlash({
  selectedSessionIdRef,
  inputContent,
  clearInput,
}: UseCodingSlashOptions) {
  const [slashInvocation, setSlashInvocation] = useState<SlashInvocation | null>(null);
  const [slashCandidates, setSlashCandidates] = useState<SlashCandidate[]>([]);
  const [hasSkillsTool, setHasSkillsTool] = useState(true);
  const [slashPaletteIndex, setSlashPaletteIndex] = useState(0);

  const refreshSlashCandidates = async (sessionId: string) => {
    try {
      const res = await getSlashCandidates(sessionId);
      if (selectedSessionIdRef.current !== sessionId) return;
      setSlashCandidates(res.candidates);
      setHasSkillsTool(res.has_skills_tool);
      if (!res.has_skills_tool) setSlashInvocation(null);
    } catch {
      if (selectedSessionIdRef.current !== sessionId) return;
      setSlashCandidates([]);
      setHasSkillsTool(true);
    }
  };

  /** セッション切替時の候補取得（選択セッションの移動ガード付き）。 */
  const loadForSession = (sessionId: string) => {
    const requestSessionId = sessionId;
    return getSlashCandidates(requestSessionId)
      .then((res) => {
        if (selectedSessionIdRef.current !== requestSessionId) return;
        setSlashCandidates(res.candidates);
        setHasSkillsTool(res.has_skills_tool);
        if (!res.has_skills_tool) setSlashInvocation(null);
      })
      .catch(() => {
        if (selectedSessionIdRef.current !== requestSessionId) return;
        setSlashCandidates([]);
        setHasSkillsTool(true);
      });
  };

  const resetForEmptySession = () => {
    setSlashCandidates([]);
    setHasSkillsTool(true);
    setSlashInvocation(null);
  };

  const slashQuery = useMemo(() => {
    if (slashInvocation) return null;
    return inputContent.startsWith("/") ? inputContent.slice(1) : null;
  }, [inputContent, slashInvocation]);

  const filteredCandidates = useMemo(() => {
    if (slashQuery === null) return [];
    const q = slashQuery.toLowerCase();
    return slashCandidates.filter((c) => c.name.toLowerCase().includes(q));
  }, [slashCandidates, slashQuery]);

  const showSlashPalette = slashQuery !== null;

  useEffect(() => {
    setSlashPaletteIndex(0);
  }, [slashQuery, slashCandidates]);

  const handleSelectCandidate = (cand: SlashCandidate) => {
    setSlashInvocation({ kind: "skill", name: cand.name });
    clearInput();
  };

  return {
    slashInvocation,
    setSlashInvocation,
    slashCandidates,
    hasSkillsTool,
    slashPaletteIndex,
    setSlashPaletteIndex,
    slashQuery,
    filteredCandidates,
    showSlashPalette,
    refreshSlashCandidates,
    loadForSession,
    resetForEmptySession,
    handleSelectCandidate,
  };
}
