import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HealthcareImportDialog from "./HealthcareImportDialog";

vi.mock("../../api/client", () => ({
  importHealthcareZip: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { ApiError, importHealthcareZip } from "../../api/client";
import type { HealthcareImportResponse } from "../../api/types";

const mockImport = vi.mocked(importHealthcareZip);

const successResult: HealthcareImportResponse = {
  import_id: "himp_test",
  status: "succeeded",
  source: "/tmp/export.zip",
  stats: {
    records: 100,
    workouts: 5,
    activity_summaries: 2,
    ecg_files: 1,
    ignored_duplicates: 90,
    metadata_entries: 3,
    hrv_beats: 0,
    records_inserted: 10,
    workouts_inserted: 3,
    activity_summaries_inserted: 2,
  },
};

function renderDialog(overrides: Partial<{
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}> = {}) {
  const onClose = overrides.onClose ?? vi.fn();
  const onImported = overrides.onImported ?? vi.fn();
  render(
    <HealthcareImportDialog
      open={overrides.open ?? true}
      onClose={onClose}
      onImported={onImported}
    />,
  );
  return { onClose, onImported };
}

describe("HealthcareImportDialog", () => {
  beforeEach(() => {
    mockImport.mockReset();
  });

  it("does not render when closed", () => {
    renderDialog({ open: false });
    expect(screen.queryByTestId("healthcare-import-dialog")).not.toBeInTheDocument();
  });

  it("disables import until a file or path is provided", async () => {
    renderDialog();
    const submit = screen.getByTestId("healthcare-import-submit");
    expect(submit).toBeDisabled();

    const file = new File(["zip-bytes"], "export.zip", { type: "application/zip" });
    await userEvent.upload(screen.getByTestId("healthcare-import-file-input"), file);
    expect(submit).toBeEnabled();
  });

  it("uploads the selected file and shows the differential result", async () => {
    mockImport.mockResolvedValue(successResult);
    const { onImported } = renderDialog();

    const file = new File(["zip-bytes"], "export.zip", { type: "application/zip" });
    await userEvent.upload(screen.getByTestId("healthcare-import-file-input"), file);
    await userEvent.click(screen.getByTestId("healthcare-import-submit"));

    await waitFor(() => expect(mockImport).toHaveBeenCalledWith({ file }));
    const result = await screen.findByTestId("healthcare-import-result");
    expect(result.textContent).toContain("15");
    expect(result.textContent).toContain("90");
    expect(onImported).toHaveBeenCalledTimes(1);
  });

  it("supports dropping a zip onto the dropzone", () => {
    const { onImported } = renderDialog();
    const file = new File(["zip-bytes"], "export.zip", { type: "application/zip" });
    fireEvent.drop(screen.getByTestId("healthcare-import-dropzone"), {
      dataTransfer: { files: [file] },
    });
    expect(screen.getByTestId("healthcare-import-dropzone").textContent).toContain("export.zip");
    expect(onImported).not.toHaveBeenCalled();
  });

  it("imports from a server-side path", async () => {
    mockImport.mockResolvedValue(successResult);
    renderDialog();

    await userEvent.click(screen.getByText("サーバー上のパスを指定"));
    await userEvent.type(
      screen.getByTestId("healthcare-import-path-input"),
      "/Users/me/Downloads/export.zip",
    );
    await userEvent.click(screen.getByTestId("healthcare-import-submit"));

    await waitFor(() =>
      expect(mockImport).toHaveBeenCalledWith({ path: "/Users/me/Downloads/export.zip" }),
    );
  });

  it("shows an error message when import fails", async () => {
    mockImport.mockRejectedValue(new ApiError(400, "export.xml が zip 内に見つかりません"));
    renderDialog();

    const file = new File(["zip-bytes"], "export.zip", { type: "application/zip" });
    await userEvent.upload(screen.getByTestId("healthcare-import-file-input"), file);
    await userEvent.click(screen.getByTestId("healthcare-import-submit"));

    const error = await screen.findByTestId("healthcare-import-error");
    expect(error.textContent).toContain("export.xml");
  });

  it("closes via the close button", async () => {
    const { onClose } = renderDialog();
    await userEvent.click(screen.getByLabelText("閉じる"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
