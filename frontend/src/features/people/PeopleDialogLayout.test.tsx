import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, test, expect, vi, beforeEach } from "vitest";
import DeleteAliasDialog from "./DeleteAliasDialog";
import DeletePersonDialog from "./DeletePersonDialog";
import MergePreviewDialog from "./MergePreviewDialog";
import { PersonDetail } from "./types";
import { Person } from "../../api/types";

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true;
  });
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false;
  });
});

const mockPersonDetail: PersonDetail = {
  person_id: "p1",
  display_name: "山田太郎",
  normalized_name: "山田太郎",
  vault_id: null,
  aliases: [{ normalized_name: "たろう", display_name: "タロウ" }],
  summary_count: 1,
  summaries: [],
  relation_counts: {
    summaries: 1,
    aliases: 1,
    assignments: 0,
    subject_relations: 0,
    object_relations: 0,
    evidence: 0,
  },
};

const mockPerson: Person = {
  person_id: "p1",
  display_name: "山田太郎",
  normalized_name: "山田太郎",
  vault_id: null,
  aliases: [],
  summary_count: 1,
};

describe("People Modals Safari height fix - Layout and behavior tests", () => {
  describe("DeleteAliasDialog", () => {
    test("does not contain fixed or inset-0 on dialog element and does not contain h-full on inner container", () => {
      render(
        <DeleteAliasDialog
          aliasToDelete={{ normalized_name: "たろう", display_name: "タロウ" }}
          selectedPerson={mockPersonDetail}
          loading={false}
          onCancel={vi.fn()}
          onConfirm={vi.fn()}
        />
      );

      const dialog = screen.getByRole("dialog");
      expect(dialog.className).not.toContain("fixed");
      expect(dialog.className).not.toContain("inset-0");
      expect(dialog.className).toContain("m-auto");

      const innerContainer = dialog.firstElementChild as HTMLElement;
      expect(innerContainer.className).not.toContain("h-full");
      expect(innerContainer.className).toContain("flex flex-col");
    });

    test("calls showModal on mount and handles cancel and confirm buttons", () => {
      const onCancel = vi.fn();
      const onConfirm = vi.fn();

      render(
        <DeleteAliasDialog
          aliasToDelete={{ normalized_name: "たろう", display_name: "タロウ" }}
          selectedPerson={mockPersonDetail}
          loading={false}
          onCancel={onCancel}
          onConfirm={onConfirm}
        />
      );

      expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalled();

      fireEvent.click(screen.getByRole("button", { name: "キャンセル" }));
      expect(onCancel).toHaveBeenCalledTimes(1);

      fireEvent.click(screen.getByRole("button", { name: "削除する" }));
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });
  });

  describe("DeletePersonDialog", () => {
    test("does not contain fixed or inset-0 on dialog element and does not contain h-full on inner container", () => {
      render(
        <DeletePersonDialog
          personToDelete={mockPersonDetail}
          loading={false}
          onCancel={vi.fn()}
          onConfirm={vi.fn()}
        />
      );

      const dialog = screen.getByRole("dialog");
      expect(dialog.className).not.toContain("fixed");
      expect(dialog.className).not.toContain("inset-0");
      expect(dialog.className).toContain("m-auto");

      const innerContainer = dialog.firstElementChild as HTMLElement;
      expect(innerContainer.className).not.toContain("h-full");
      expect(innerContainer.className).toContain("flex flex-col");
    });

    test("calls showModal on mount and handles cancel and confirm buttons", () => {
      const onCancel = vi.fn();
      const onConfirm = vi.fn();

      render(
        <DeletePersonDialog
          personToDelete={mockPersonDetail}
          loading={false}
          onCancel={onCancel}
          onConfirm={onConfirm}
        />
      );

      expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalled();

      fireEvent.click(screen.getByRole("button", { name: "キャンセル" }));
      expect(onCancel).toHaveBeenCalledTimes(1);

      fireEvent.click(screen.getByRole("button", { name: "本当に完全に削除する" }));
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });
  });

  describe("MergePreviewDialog", () => {
    test("does not contain fixed or inset-0 on dialog element, keeps max-h-[85vh], and uses explicit flex container on inner div", () => {
      render(
        <MergePreviewDialog
          mergeFromPerson={mockPerson}
          mergeToPerson={null}
          previewLoading={false}
          previewData={null}
          mergeModalError={null}
          loading={false}
          onCloseModal={vi.fn()}
          onExecuteMerge={vi.fn()}
        />
      );

      const dialog = screen.getByRole("dialog", { hidden: true });
      expect(dialog.className).not.toContain("fixed");
      expect(dialog.className).not.toContain("inset-0");
      expect(dialog.className).toContain("max-h-[85vh]");

      const innerContainer = dialog.firstElementChild as HTMLElement;
      expect(innerContainer.className).not.toContain("h-full");
      expect(innerContainer.className).toContain("max-h-[85vh]");
      expect(innerContainer.className).toContain("flex flex-col");

      // Check body container
      const body = innerContainer.children[1] as HTMLElement;
      expect(body.className).toContain("overflow-y-auto");
      expect(body.className).toContain("flex-1");
      expect(body.className).toContain("min-h-0");
    });

    test("handles cancel button click", () => {
      const onCloseModal = vi.fn();

      render(
        <MergePreviewDialog
          mergeFromPerson={mockPerson}
          mergeToPerson={null}
          previewLoading={false}
          previewData={null}
          mergeModalError={null}
          loading={false}
          onCloseModal={onCloseModal}
          onExecuteMerge={vi.fn()}
        />
      );

      fireEvent.click(screen.getByRole("button", { name: "キャンセル", hidden: true }));
      expect(onCloseModal).toHaveBeenCalledTimes(1);
    });
  });
});
