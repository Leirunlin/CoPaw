import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SkillDetail, SkillSpec } from "../../../api/types";

const hoisted = vi.hoisted(() => {
  const form = { resetFields: vi.fn(), setFieldsValue: vi.fn() };
  const message = { error: vi.fn(), success: vi.fn(), warning: vi.fn() };
  const api = { getSkill: vi.fn(), listSkillPoolSkills: vi.fn() };
  return { form, message, api };
});

vi.mock("@agentscope-ai/design", () => ({
  Form: { useForm: () => [hoisted.form] },
  Modal: { confirm: vi.fn() },
}));
vi.mock("../../../api", () => ({ default: hoisted.api }));
vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: hoisted.message }),
}));
vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => ({ selectedAgent: "agent-1" }),
}));
vi.mock("../../../stores/uploadLimitStore", () => ({
  useUploadLimitStore: { getState: () => ({ uploadMaxSizeMb: null }) },
}));
vi.mock("../../../hooks/useProgressiveRender", () => ({
  useProgressiveRender: (items: unknown[]) => ({
    visibleItems: items,
    hasMore: false,
    sentinelRef: { current: null },
  }),
}));
vi.mock("../../../api/modules/skill", () => ({
  invalidateSkillCache: vi.fn(),
}));
vi.mock("../../../utils/error", () => ({ parseErrorDetail: vi.fn() }));
vi.mock("../../../utils/scanError", () => ({
  checkScanWarnings: vi.fn(),
  showScanErrorModal: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("./components", () => ({
  useConflictRenameModal: () => ({
    showConflictRenameModal: vi.fn(),
    conflictRenameModal: null,
  }),
}));
vi.mock("./useSkillFilter", () => ({
  useSkillFilter: (skills: SkillSpec[]) => ({
    searchQuery: "",
    setSearchQuery: vi.fn(),
    searchTags: [],
    setSearchTags: vi.fn(),
    allTags: [],
    filteredSkills: skills,
  }),
}));
vi.mock("./useSkills", () => ({
  useSkills: () => ({
    skills: [],
    providerSkills: [],
    loading: false,
    uploading: false,
    importing: false,
    createSkill: vi.fn(),
    uploadSkill: vi.fn(),
    importFromHub: vi.fn(),
    cancelImport: vi.fn(),
    toggleEnabled: vi.fn(),
    deleteSkill: vi.fn(),
    refreshSkills: vi.fn(),
    hardRefresh: vi.fn(),
  }),
}));

import { useSkillsPage } from "./useSkillsPage";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const summary = (name: string): SkillSpec => ({
  name,
  source: "customized",
});

const detail = (name: string): SkillDetail => ({
  ...summary(name),
  content: `---\nname: ${name}\ndescription: test\n---`,
  config: {},
});

describe("useSkillsPage detail loading", () => {
  beforeEach(() => vi.clearAllMocks());

  it("closes the drawer and reports a detail load failure", async () => {
    hoisted.api.getSkill.mockRejectedValueOnce(new Error("load failed"));
    const { result } = renderHook(() => useSkillsPage());

    await act(async () => {
      await result.current.handleEdit(summary("broken"));
    });

    expect(result.current.drawerOpen).toBe(false);
    expect(result.current.drawerLoading).toBe(false);
    expect(hoisted.message.error).toHaveBeenCalledWith("load failed");
  });

  it("ignores a stale detail response after a newer skill was opened", async () => {
    const first = deferred<SkillDetail>();
    const second = deferred<SkillDetail>();
    hoisted.api.getSkill
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => useSkillsPage());

    act(() => {
      void result.current.handleEdit(summary("first"));
      void result.current.handleEdit(summary("second"));
    });
    await act(async () => second.resolve(detail("second")));
    await act(async () => first.resolve(detail("first")));

    expect(result.current.editingSkill?.name).toBe("second");
    expect(result.current.editingSkillName).toBe("second");
    expect(result.current.drawerLoading).toBe(false);
  });
});
