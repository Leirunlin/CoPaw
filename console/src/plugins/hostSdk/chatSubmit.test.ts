import { describe, expect, it, vi } from "vitest";
import { bindChatSubmit, submitChat } from "./chatSubmit";

describe("plugin chat submission bridge", () => {
  const input = { query: " use 8 seeds ", agentId: "a", sessionId: "s" };
  it("rejects unavailable chat and invalid actions", async () => {
    await expect(submitChat("p", input)).rejects.toThrow("not ready");
    await expect(submitChat("p", { ...input, query: " " })).rejects.toThrow(
      "required",
    );
  });
  it("forwards a captured scope once, propagates admission errors and safely cleans up", async () => {
    const oldHandler = vi.fn();
    const old = bindChatSubmit(oldHandler);
    const handler = vi.fn();
    const active = bindChatSubmit(handler);
    old.dispose();
    await submitChat("p", input);
    expect(handler).toHaveBeenCalledExactlyOnceWith({
      ...input,
      query: "use 8 seeds",
    });
    expect(oldHandler).not.toHaveBeenCalled();
    handler.mockRejectedValueOnce(new Error("wrong session"));
    await expect(submitChat("p", input)).rejects.toThrow("wrong session");
    active.dispose();
    await expect(submitChat("p", input)).rejects.toThrow("not ready");
  });
});
