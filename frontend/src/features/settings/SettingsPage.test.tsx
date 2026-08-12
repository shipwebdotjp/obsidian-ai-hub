import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import SettingsPage from "./SettingsPage";

vi.mock("../../api/client", () => ({
  getToken: vi.fn(),
  setToken: vi.fn(),
  clearToken: vi.fn(),
  listMemories: vi.fn(),
  AUTH_EXPIRED_EVENT: "auth:expired",
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import {
  getToken,
  setToken,
  clearToken,
  listMemories,
  ApiError,
} from "../../api/client";

const mockGetToken = vi.mocked(getToken);
const mockSetToken = vi.mocked(setToken);
const mockClearToken = vi.mocked(clearToken);
const mockListMemories = vi.mocked(listMemories);

beforeEach(() => {
  vi.clearAllMocks();
  mockGetToken.mockReturnValue("");
  mockListMemories.mockResolvedValue({ items: [], total: 0 });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SettingsPage", () => {
  it("prefills the input with the stored token", () => {
    mockGetToken.mockReturnValue("existing-token");
    render(<SettingsPage />);
    expect(screen.getByLabelText("API token")).toHaveValue("existing-token");
  });

  it("saves and validates the token", async () => {
    render(<SettingsPage />);
    await userEvent.type(screen.getByLabelText("API token"), "new-token");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(mockSetToken).toHaveBeenCalledWith("new-token");
    expect(mockListMemories).toHaveBeenCalledWith({ status: "candidate" });
    await waitFor(() => {
      expect(screen.getByText("トークンを保存しました")).toBeInTheDocument();
    });
  });

  it("clears the token and shows the error when validation fails", async () => {
    mockListMemories.mockRejectedValue(new ApiError(401, "Unauthorized"));
    render(<SettingsPage />);
    await userEvent.type(screen.getByLabelText("API token"), "bad-token");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => {
      expect(mockClearToken).toHaveBeenCalled();
      expect(screen.getByText("Unauthorized")).toBeInTheDocument();
    });
  });

  it("clears the token and dispatches auth:expired when トークンを削除 is clicked", async () => {
    const dispatchSpy = vi
      .spyOn(window, "dispatchEvent")
      .mockImplementation(() => true);
    vi.spyOn(window, "confirm").mockImplementation(() => true);
    render(<SettingsPage />);
    await userEvent.click(
      screen.getByRole("button", { name: "トークンを削除" }),
    );
    expect(mockClearToken).toHaveBeenCalled();
    expect(dispatchSpy).toHaveBeenCalledWith(
      expect.objectContaining({ type: "auth:expired" }),
    );
  });
});
