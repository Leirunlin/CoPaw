import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PoolSkillDetail, PoolSkillSpec } from "../../../api/types";

const hoisted = vi.hoisted(() => {
  const form = { resetFields: vi.fn(), setFieldsValue: vi.fn() };
  const message = { error: vi.fn(), success: vi.fn(), warning: vi.fn() };
  const api = {
    listSkillPoolSkills: vi.fn(),
    listSkillWorkspaces: vi.fn(),
    getPoolBuiltinNotice: vi.fn(),
    getPoolSkill: vi.fn(),
  };
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
vi.mock("../../../api/modules/skill", () => ({
  invalidateSkillCache: vi.fn(),
}));
vi.mock("../../../stores/uploadLimitStore", () => ({
  useUploadLimitStore: { getState: () => ({ uploadMaxSizeMb: null }) },
}));
vi.mock("../../../utils/error", () => ({ parseErrorDetail: vi.fn() }));
vi.mock("../../../utils/scanError", () => ({
  handleScanError: vi.fn(),
  checkScanWarnings: vi.fn(),
}));
vi.mock("../../../utils/agentDisplayName", () => ({
  getAgentDisplayName: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));
vi.mock("../../Agent/Skills/components", () => ({
  parseFrontmatter: vi.fn(),
  useConflictRenameModal: () => ({
    showConflictRenameModal: vi.fn(),
    conflictRenameModal: null,
  }),
}));
vi.mock("../../Agent/Skills/useSkillFilter", () => ({
  useSkillFilter: (skills: PoolSkillSpec[]) => ({
    searchQuery: "",
    setSearchQuery: vi.fn(),
    searchTags: [],
    setSearchTags: vi.fn(),
    allTags: [],
    filteredSkills: skills,
  }),
}));

import { useSkillPool } from "./useSkillPool";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const summary = (name: string): PoolSkillSpec => ({
  name,
  source: "customized",
});

const detail = (name: string): PoolSkillDetail => ({
  ...summary(name),
  content: `---\nname: ${name}\ndescription: test\n---`,
  config: {},
});

describe("useSkillPool detail loading", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.api.listSkillPoolSkills.mockResolvedValue([]);
    hoisted.api.listSkillWorkspaces.mockResolvedValue([]);
    hoisted.api.getPoolBuiltinNotice.mockResolvedValue(null);
  });

  it("closes the drawer and reports a detail load failure", async () => {
    hoisted.api.getPoolSkill.mockRejectedValueOnce(new Error("load failed"));
    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.openEdit(summary("broken"));
    });

    expect(result.current.mode).toBeNull();
    expect(result.current.detailLoading).toBe(false);
    expect(hoisted.message.error).toHaveBeenCalledWith("load failed");
  });

  it("ignores a stale detail response after a newer skill was opened", async () => {
    const first = deferred<PoolSkillDetail>();
    const second = deferred<PoolSkillDetail>();
    hoisted.api.getPoolSkill
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => useSkillPool());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      void result.current.openEdit(summary("first"));
      void result.current.openEdit(summary("second"));
    });
    await act(async () => second.resolve(detail("second")));
    await act(async () => first.resolve(detail("first")));

    expect(result.current.activeSkill?.name).toBe("second");
    expect(result.current.detailSkillName).toBe("second");
    expect(result.current.detailLoading).toBe(false);
  });
});
