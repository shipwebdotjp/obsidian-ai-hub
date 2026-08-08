import type {
  DashboardBrowseResponse,
  DashboardDayDetailsResponse,
  SummaryDetail,
  SummaryUpdatePayload,
  EditOptionsResponse,
  Person,
  MissingSummaryTarget,
} from "../../api/types";
import { BrowseList } from "./BrowseList";
import { DetailPanel } from "./DetailPanel";

export function BrowseTab({
  year,
  month,
  setYear,
  setMonth,
  data,
  loading,
  error,
  selectedSummary,
  selectedDay,
  detailLoading,
  detailError,
  mobileDetailOpen,
  setMobileDetailOpen,
  onOpenSummary,
  isEditing,
  editForm,
  setEditForm,
  editOptions,
  allPeople,
  editSaving,
  editError,
  onSave,
  onCancel,
  onStartEdit,
  onRequestDelete,
  onShowDayDetail,
  selectedMissingTarget,
  onOpenMissingTarget,
  generationSaving,
  generationError,
  onGenerate,
  onRequestRegenerate,
}: {
  year: string;
  month: string;
  setYear: (y: string) => void;
  setMonth: (m: string) => void;
  data: DashboardBrowseResponse | null;
  loading: boolean;
  error: string | null;
  selectedSummary: SummaryDetail | null;
  selectedDay: DashboardDayDetailsResponse | null;
  detailLoading: boolean;
  detailError: string | null;
  mobileDetailOpen: boolean;
  setMobileDetailOpen: (open: boolean) => void;
  onOpenSummary: (summaryId: string) => void;
  isEditing: boolean;
  editForm: SummaryUpdatePayload;
  setEditForm: (f: SummaryUpdatePayload) => void;
  editOptions: EditOptionsResponse | null;
  allPeople: Person[];
  editSaving: boolean;
  editError: string | null;
  onSave: () => void;
  onCancel: () => void;
  onStartEdit: () => void;
  onRequestDelete: () => void;
  onShowDayDetail: (targetDate: string) => void;
  selectedMissingTarget: MissingSummaryTarget | null;
  onOpenMissingTarget: (target: MissingSummaryTarget) => void;
  generationSaving: boolean;
  generationError: string | null;
  onGenerate: () => void;
  onRequestRegenerate: () => void;
}) {
  return (
    <div className="flex h-full flex-col lg:flex-row">
      {/* Left lists column */}
      <div
        className={`flex h-full w-full flex-col border-slate-200 bg-white lg:w-1/2 lg:border-r ${
          mobileDetailOpen ? "hidden" : "flex"
        } lg:flex`}
      >
        <BrowseList
          year={year}
          month={month}
          setYear={setYear}
          setMonth={setMonth}
          data={data}
          loading={loading}
          error={error}
          onOpenSummary={onOpenSummary}
          onShowDayDetail={onShowDayDetail}
          onOpenMissingTarget={onOpenMissingTarget}
        />
      </div>

      {/* Right details column */}
      <DetailPanel
        selectedSummary={selectedSummary}
        selectedDay={selectedDay}
        detailLoading={detailLoading}
        detailError={detailError}
        mobileDetailOpen={mobileDetailOpen}
        onCloseMobile={() => setMobileDetailOpen(false)}
        isEditing={isEditing}
        editForm={editForm}
        setEditForm={setEditForm}
        editOptions={editOptions}
        allPeople={allPeople}
        editSaving={editSaving}
        editError={editError}
        onSave={onSave}
        onCancel={onCancel}
        onStartEdit={onStartEdit}
        onRequestDelete={onRequestDelete}
        onShowDayDetail={onShowDayDetail}
        selectedMissingTarget={selectedMissingTarget}
        generationSaving={generationSaving}
        generationError={generationError}
        onGenerate={onGenerate}
        onRequestRegenerate={onRequestRegenerate}
      />
    </div>
  );
}
