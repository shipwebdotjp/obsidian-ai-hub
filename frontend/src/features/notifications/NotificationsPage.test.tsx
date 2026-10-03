import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { NotificationsPage } from "./NotificationsPage";
import * as clientModule from "../../api/client";

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof clientModule>();
  return {
    ...actual,
    listNotifications: vi.fn(),
    markNotificationAsRead: vi.fn(),
  };
});

const mockListNotifications = vi.mocked(clientModule.listNotifications);
const mockMarkNotificationAsRead = vi.mocked(clientModule.markNotificationAsRead);

const dummyNotification: clientModule.NotificationInboxItem = {
  notification_id: "ntf_001",
  event_type: "hitl",
  target_id: "hitl_123",
  category: "action_required",
  title: "【要確認】確認事項があります",
  body: "詳細な説明メッセージ",
  relative_link: "/hitl",
  created_at: "2026-03-31T10:00:00Z",
  read_at: null,
  web_push_status: "accepted",
  web_push_status_at: "2026-03-31T10:00:01Z",
  web_push_failure_reason: null,
  web_push_target_count: 1,
  web_push_success_count: 1,
  web_push_failure_count: 0,
  line_status: "accepted",
  line_status_at: "2026-03-31T10:00:01Z",
  line_failure_reason: null,
};

describe("NotificationsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders notification list and filters", async () => {
    mockListNotifications.mockResolvedValue({
      items: [dummyNotification],
      total: 1,
      page: 1,
      limit: 20,
    });

    render(
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("【要確認】確認事項があります")).toBeInTheDocument();
    });

    expect(screen.getByText("通知受信箱")).toBeInTheDocument();
    expect(screen.getByText("詳細な説明メッセージ")).toBeInTheDocument();
  });

  it("opens detail modal and marks notification as read", async () => {
    mockListNotifications.mockResolvedValue({
      items: [dummyNotification],
      total: 1,
      page: 1,
      limit: 20,
    });

    const readNotification = {
      ...dummyNotification,
      read_at: "2026-03-31T10:05:00Z",
    };
    mockMarkNotificationAsRead.mockResolvedValue(readNotification);

    render(
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("【要確認】確認事項があります")).toBeInTheDocument();
    });

    // Click list item to open detail
    await userEvent.click(screen.getByText("【要確認】確認事項があります"));

    await waitFor(() => {
      expect(mockMarkNotificationAsRead).toHaveBeenCalledWith("ntf_001");
    });

    expect(screen.getByText("外部チャネル配信結果")).toBeInTheDocument();
    expect(screen.getByText("対象画面を開く")).toBeInTheDocument();

    const link = screen.getByRole("link", { name: "対象画面を開く" });
    expect(link).toHaveAttribute("href", "/hitl");
  });

  it("filters notifications by status when buttons clicked", async () => {
    mockListNotifications.mockResolvedValue({
      items: [dummyNotification],
      total: 1,
      page: 1,
      limit: 20,
    });

    render(
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockListNotifications).toHaveBeenCalledWith(
        { status: "all", category: "all", page: 1, limit: 20 },
        expect.any(AbortSignal),
      );
    });

    const unreadButton = screen.getByRole("button", { name: "未読のみ" });
    await userEvent.click(unreadButton);

    await waitFor(() => {
      expect(mockListNotifications).toHaveBeenCalledWith(
        { status: "unread", category: "all", page: 1, limit: 20 },
        expect.any(AbortSignal),
      );
    });
  });
});
