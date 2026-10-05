import { render, screen, waitFor } from "@testing-library/react";
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
    markAllNotificationsAsRead: vi.fn(),
  };
});

const mockListNotifications = vi.mocked(clientModule.listNotifications);
const mockMarkNotificationAsRead = vi.mocked(clientModule.markNotificationAsRead);
const mockMarkAllNotificationsAsRead = vi.mocked(
  clientModule.markAllNotificationsAsRead,
);

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

function makeNotification(
  overrides: Partial<clientModule.NotificationInboxItem> &
    Pick<clientModule.NotificationInboxItem, "notification_id" | "title">,
): clientModule.NotificationInboxItem {
  return { ...dummyNotification, ...overrides };
}

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

  it("refreshes the unread badge after marking an opened notification as read", async () => {
    mockListNotifications.mockResolvedValue({
      items: [dummyNotification],
      total: 1,
      page: 1,
      limit: 20,
    });
    mockMarkNotificationAsRead.mockResolvedValue({
      ...dummyNotification,
      read_at: "2026-03-31T10:05:00Z",
    });
    const onUnreadCountChanged = vi.fn();

    render(
      <MemoryRouter>
        <NotificationsPage onUnreadCountChanged={onUnreadCountChanged} />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("【要確認】確認事項があります")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByText("【要確認】確認事項があります"));

    await waitFor(() => {
      expect(onUnreadCountChanged).toHaveBeenCalledTimes(1);
    });
  });

  it("marks all notifications as read, refetches the list, and refreshes the badge", async () => {
    mockListNotifications.mockResolvedValue({
      items: [dummyNotification],
      total: 1,
      page: 1,
      limit: 20,
    });
    mockMarkAllNotificationsAsRead.mockResolvedValue({ updated_count: 1 });
    const onUnreadCountChanged = vi.fn();

    render(
      <MemoryRouter>
        <NotificationsPage onUnreadCountChanged={onUnreadCountChanged} />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockListNotifications).toHaveBeenCalledTimes(1);
    });

    await userEvent.click(screen.getByTestId("notification-read-all"));

    await waitFor(() => {
      expect(mockMarkAllNotificationsAsRead).toHaveBeenCalledTimes(1);
      expect(onUnreadCountChanged).toHaveBeenCalledTimes(1);
      expect(mockListNotifications.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("returns to a valid page when the unread filter becomes empty after read-all", async () => {
    let readAllDone = false;
    mockListNotifications.mockImplementation(async (params) => {
      const total = readAllDone ? 0 : 21;
      return {
        items: readAllDone
          ? []
          : [makeNotification({ notification_id: "ntf_p1", title: "1ページ目" })],
        total,
        page: params?.page ?? 1,
        limit: 20,
      };
    });
    mockMarkAllNotificationsAsRead.mockImplementation(async () => {
      readAllDone = true;
      return { updated_count: 21 };
    });

    render(
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: "未読のみ" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "次へ" })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "次へ" }));

    await waitFor(() => {
      expect(mockListNotifications).toHaveBeenCalledWith(
        { status: "unread", category: "all", page: 2, limit: 20 },
        expect.any(AbortSignal),
      );
    });

    await userEvent.click(screen.getByTestId("notification-read-all"));

    await waitFor(() => {
      expect(mockListNotifications).toHaveBeenCalledWith(
        { status: "unread", category: "all", page: 1, limit: 20 },
        expect.any(AbortSignal),
      );
    });
  });

  it("navigates to the next notification within the page and marks it read", async () => {
    const newer = makeNotification({
      notification_id: "ntf_newer",
      title: "新しい通知",
    });
    const older = makeNotification({
      notification_id: "ntf_older",
      title: "古い通知",
    });
    mockListNotifications.mockResolvedValue({
      items: [newer, older],
      total: 2,
      page: 1,
      limit: 20,
    });
    mockMarkNotificationAsRead.mockImplementation(async (id) =>
      makeNotification({
        notification_id: id,
        title: id === "ntf_newer" ? "新しい通知" : "古い通知",
        read_at: "2026-03-31T10:05:00Z",
      }),
    );

    render(
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("新しい通知")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByText("新しい通知"));

    await waitFor(() => {
      expect(mockMarkNotificationAsRead).toHaveBeenCalledWith("ntf_newer");
    });

    expect(screen.getByTestId("notification-prev")).toBeDisabled();
    expect(screen.getByTestId("notification-next")).toBeEnabled();

    await userEvent.click(screen.getByTestId("notification-next"));

    await waitFor(() => {
      expect(mockMarkNotificationAsRead).toHaveBeenCalledWith("ntf_older");
    });

    expect(screen.getByTestId("notification-prev")).toBeEnabled();
    expect(screen.getByTestId("notification-next")).toBeDisabled();
  });

  it("keeps the latest notification in the modal when read responses resolve out of order", async () => {
    const newer = makeNotification({
      notification_id: "ntf_newer",
      title: "新しい通知",
    });
    const older = makeNotification({
      notification_id: "ntf_older",
      title: "古い通知",
    });
    mockListNotifications.mockResolvedValue({
      items: [newer, older],
      total: 2,
      page: 1,
      limit: 20,
    });

    const resolvers: Record<string, (value: clientModule.NotificationInboxItem) => void> = {};
    mockMarkNotificationAsRead.mockImplementation(
      (id) =>
        new Promise<clientModule.NotificationInboxItem>((resolve) => {
          resolvers[id] = resolve;
        }),
    );

    render(
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("新しい通知")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByText("新しい通知"));
    await userEvent.click(screen.getByTestId("notification-next"));

    // Resolve the first request last; the modal must still show the older item.
    resolvers["ntf_older"]({
      ...older,
      read_at: "2026-03-31T10:05:00Z",
    });
    resolvers["ntf_newer"]({
      ...newer,
      read_at: "2026-03-31T10:05:00Z",
    });

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { level: 2, name: "古い通知" }),
      ).toBeInTheDocument();
    });
  });

  it("shows the notification content and an error when marking it read fails", async () => {
    mockListNotifications.mockResolvedValue({
      items: [dummyNotification],
      total: 1,
      page: 1,
      limit: 20,
    });
    mockMarkNotificationAsRead.mockRejectedValue(new Error("boom"));

    render(
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("【要確認】確認事項があります")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByText("【要確認】確認事項があります"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getAllByText("詳細な説明メッセージ").length).toBeGreaterThan(0);
  });
});
