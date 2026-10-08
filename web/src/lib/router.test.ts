import { describe, expect, it } from "vitest";

import { parse } from "./router.svelte";

describe("hash router", () => {
  it("routes the experiment workspace and its suite templates", () => {
    expect(parse("#/experiments")).toEqual({ name: "experiments", template: undefined });
    expect(parse("#/experiments/classic_benchmarks")).toEqual({ name: "experiments", template: "classic_benchmarks" });
  });

  it("keeps old build links working as an experiments alias", () => {
    expect(parse("#/build")).toEqual({ name: "experiments", template: undefined });
    expect(parse("#/build/critic_study")).toEqual({ name: "experiments", template: "critic_study" });
  });
});
