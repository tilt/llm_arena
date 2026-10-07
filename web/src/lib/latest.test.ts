import { describe, expect, it } from "vitest";

import { newest } from "./latest";

describe("newest load wins", () => {
  it("lets only the most recent load apply its answer", async () => {
    const begin = newest();
    let shown = "";
    const load = async (value: string, delay: number) => {
      const current = begin();
      await new Promise((resolve) => setTimeout(resolve, delay));
      if (current()) shown = value;
    };
    // Run A is slow, run B was asked for later: B's answer must stay.
    await Promise.all([load("run-a", 20), load("run-b", 1)]);
    expect(shown).toBe("run-b");
  });

  it("invalidates a load when a new one begins without loading", () => {
    const begin = newest();
    const first = begin();
    expect(first()).toBe(true);
    begin(); // e.g. the form was closed
    expect(first()).toBe(false);
  });
});
