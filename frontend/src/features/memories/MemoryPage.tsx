import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import MemoryList from "./MemoryList";
import MemoryDetailPanel from "./MemoryDetailPanel";
import MasterDetailLayout from "../../components/MasterDetailLayout";
import { ToastStack, useToasts } from "../../components/Toast";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { DEFAULT_LIST_RATIO } from "../../hooks/usePaneResize";
import type { Memory, MemoryDetail, MemoryStatus, Person } from "../../api/types";
import { getMemoryOptions, listPeople, renderCopilotProfile } from "../../api/client";

export default function MemoryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialPersonId = searchParams.get("person_id") || "";

  const [status, setStatus] = useState<MemoryStatus>("candidate");
  const [queryInput, setQueryInput] = useState("");
  const debouncedQuery = useDebouncedValue(queryInput, 500);
  const [kind, setKind] = useState("");
  const [topic, setTopic] = useState("");
  const [personId, setPersonId] = useState(initialPersonId);
  useEffect(() => {
    setPersonId(searchParams.get("person_id") || "");
  }, [searchParams]);
  const [peopleOptions, setPeopleOptions] = useState<Person[]>([]);
  const [kindsOptions, setKindsOptions] = useState<string[]>([]);
  const [topicsOptions, setTopicsOptions] = useState<string[]>([]);
  const [isRendering, setIsRendering] = useState(false);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectedMemory, setSelectedMemory] = useState<Memory | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const { toasts, notify } = useToasts();

  const handleRefresh = useCallback(() => setRefreshKey((v) => v + 1), []);
  const selectedMemoryId = selectedMemory?.memory_id ?? null;

  useEffect(() => {
    if (!selectedMemory) setMobileDetailOpen(false);
  }, [selectedMemory]);

  const onChanged = useCallback((memory: MemoryDetail | null) => {
    if (memory === null) {
      setSelectedMemory(null);
    }
    handleRefresh();
  }, [handleRefresh]);

  // Fetch filter options and people list once on page load
  useEffect(() => {
    getMemoryOptions()
      .then((res) => {
        setKindsOptions(res.kinds);
        setTopicsOptions(res.topics);
      })
      .catch((err) => {
        console.error("Failed to fetch memory options:", err);
      });

    listPeople()
      .then((res) => {
        setPeopleOptions(res);
      })
      .catch((err) => {
        console.error("Failed to fetch people:", err);
      });
  }, []);

  // Reset list selection and single selection when any filter changes
  useEffect(() => {
    setSelectedMemory(null);
    setSelected(new Set());
  }, [status, debouncedQuery, kind, topic, personId]);

  const handlePersonFilterChange = (newPersonId: string) => {
    setPersonId(newPersonId);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (newPersonId) {
        next.set("person_id", newPersonId);
      } else {
        next.delete("person_id");
      }
      return next;
    });
  };

  const showRightPanel = status === "candidate" || status === "approved" || status === "rejected" || status === "superseded" || status === "expired";

  const handleRenderCopilotProfile = async () => {
    const confirmed = window.confirm(
      "Copilotプロファイルを生成します。LLMによる生成処理が実行され、Vault内の7つの生成ファイルが上書きされます。よろしいですか？"
    );
    if (!confirmed) return;

    setIsRendering(true);
    try {
      const res = await renderCopilotProfile();
      notify(`${res.updated_files.length} 個のファイルを更新しました`, "info");
    } catch (err: any) {
      const msg = err?.message || "Copilotプロファイルの生成に失敗しました";
      notify(msg, "error");
    } finally {
      setIsRendering(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white p-3 sm:gap-3 sm:p-4">
        <h1 className="text-base font-semibold">メモリ</h1>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as MemoryStatus)}
          aria-label="ステータスフィルター"
          className="cursor-pointer rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="candidate">候補</option>
          <option value="approved">承認済み</option>
          <option value="rejected">却下済み</option>
          <option value="expired">期限切れ</option>
          <option value="superseded">置換済み</option>
        </select>
        <input
          type="search"
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          aria-label="メモリ検索"
          placeholder="検索 (本文 / タグ)"
          className="w-full min-w-0 cursor-pointer rounded border border-slate-300 px-2 py-1 text-sm sm:w-auto sm:flex-1"
        />
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          aria-label="種別フィルター"
          className="cursor-pointer rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">種別: すべて</option>
          {kindsOptions.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <select
          value={personId}
          onChange={(e) => handlePersonFilterChange(e.target.value)}
          aria-label="人物フィルター"
          className="cursor-pointer rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">人物: すべて</option>
          {peopleOptions.map((p) => (
            <option key={p.person_id} value={p.person_id}>
              {p.display_name}
            </option>
          ))}
        </select>
        <select
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          aria-label="トピックフィルター"
          className="cursor-pointer rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">トピック: すべて</option>
          {topicsOptions.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setRefreshKey((v) => v + 1)}
          className="cursor-pointer rounded border border-slate-300 px-3 py-1 text-sm"
        >
          再読み込み
        </button>
        <button
          type="button"
          onClick={handleRenderCopilotProfile}
          disabled={isRendering}
          className="cursor-pointer rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isRendering ? "生成中…" : "プロファイル生成"}
        </button>
      </header>
      <MasterDetailLayout
        mobileOpen={mobileDetailOpen}
        onBack={() => {
          setMobileDetailOpen(false);
          setSelectedMemory(null);
        }}
        mobileTitle="メモリ詳細"
        paneOptions={{
          defaultSize: DEFAULT_LIST_RATIO,
          minSize: 280,
          minOther: 360,
          storageKey: "memory",
        }}
        list={
          <MemoryList
            status={status}
            query={debouncedQuery}
            topic={topic}
            kind={kind}
            personId={personId}
            selectedIds={selected}
            selectedMemoryId={selectedMemoryId}
            onSelectionChange={setSelected}
            onSelect={(m) => {
              setSelectedMemory(m);
              setMobileDetailOpen(true);
            }}
            refreshKey={refreshKey}
            notify={notify}
          />
        }
        detail={
          selectedMemory ? (
            showRightPanel ? (
              <MemoryDetailPanel
                memoryId={selectedMemory.memory_id}
                status={status}
                peopleOptions={peopleOptions}
                onChanged={onChanged}
                notify={notify}
              />
            ) : (
              <p className="p-6 text-sm text-slate-500">
                このステータスの記憶は読み取り専用です。
              </p>
            )
          ) : (
            <p className="p-6 text-sm text-slate-500">一覧から候補を選択してください。</p>
          )
        }
      />
      <ToastStack toasts={toasts} />
    </div>
  );
}
