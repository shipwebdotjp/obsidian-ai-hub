export const REVISION_STATUS_LABEL: Record<string, string> = {
  draft: "下書き",
  published: "公開",
  superseded: "旧版",
};

export function revisionStatusLabel(status: string): string {
  return REVISION_STATUS_LABEL[status] ?? status;
}
