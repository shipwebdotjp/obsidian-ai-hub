import { act, renderHook } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { usePagination } from "../usePagination";

describe("usePagination", () => {
  it("computes offset from page and limit", () => {
    const { result } = renderHook(() => usePagination("key", 50));

    expect(result.current.page).toBe(1);
    expect(result.current.offset).toBe(0);
    expect(result.current.totalPages).toBe(1);

    act(() => {
      result.current.setTotal(120);
    });
    act(() => {
      result.current.setPage(3);
    });
    expect(result.current.page).toBe(3);
    expect(result.current.offset).toBe(100);
  });

  it("resets to the first page when the reset key changes", () => {
    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => usePagination(key, 50),
      { initialProps: { key: "candidate" } },
    );

    act(() => {
      result.current.setTotal(120);
      result.current.setPage(2);
    });
    expect(result.current.page).toBe(2);
    expect(result.current.totalPages).toBe(3);

    rerender({ key: "approved" });
    expect(result.current.page).toBe(1);
    expect(result.current.total).toBe(0);
  });

  it("clamps to the last page when the total shrinks", () => {
    const { result } = renderHook(() => usePagination("key", 50));

    act(() => {
      result.current.setTotal(120);
    });
    act(() => {
      result.current.setPage(3);
    });
    expect(result.current.page).toBe(3);

    act(() => {
      result.current.setTotal(60);
    });
    expect(result.current.page).toBe(2);
    expect(result.current.offset).toBe(50);
  });
});
