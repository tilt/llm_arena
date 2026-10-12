// WCAG AA for the color tokens in app.css, in both themes: text pairs reach 4.5:1, UI boundaries 3:1. The pairs are
// read from the stylesheet (which token a rule uses, what the token holds), so a new value or a rewired rule is checked.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("../app.css", import.meta.url), "utf8");

const escaped = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** The declarations of the first rule with exactly this selector. */
function rule(selector: string): Record<string, string> {
  const body = new RegExp(`(?:^|[{}])\\s*${escaped(selector)}\\s*\\{([^}]*)\\}`, "m").exec(css)?.[1];
  if (body === undefined) throw new Error(`app.css has no rule for ${selector}`);
  return Object.fromEntries([...body.matchAll(/([\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1]!, m[2]!.trim()]));
}

const LIGHT = rule(":root");
const DARK_BY_PREFERENCE = rule(':root:where(:not([data-theme="light"]))');
const DARK_BY_ATTRIBUTE = rule(':root[data-theme="dark"]');
// A dark block only overrides: whatever it leaves out keeps the light value.
const THEMES: [string, Record<string, string>][] = [["light", LIGHT], ["dark", { ...LIGHT, ...DARK_BY_ATTRIBUTE }]];

const SURFACES = ["--page", "--surface-1", "--surface-2", "--surface-3"];

/** The token a rule's property points at: `color: var(--accent)` gives `--accent`. */
function tokenOf(selector: string, property: string): string {
  const value = rule(selector)[property] ?? "";
  const token = /var\((--[\w-]+)\)/.exec(value)?.[1];
  if (!token) throw new Error(`${selector} { ${property}: ${value} } names no token`);
  return token;
}

function luminance(hex: string): number {
  const full = /^#[0-9a-f]{3}$/i.test(hex) ? hex.replace(/[0-9a-f]/gi, "$&$&") : hex;
  if (!/^#[0-9a-f]{6}$/i.test(full)) throw new Error(`not a hex color: ${hex}`);
  const [r, g, b] = [1, 3, 5].map((i) => {
    const channel = parseInt(full.slice(i, i + 2), 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

/** WCAG 2 contrast ratio of two hex colors. */
function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light! + 0.05) / (dark! + 0.05);
}

function ratio(theme: Record<string, string>, foreground: string, background: string): number {
  for (const token of [foreground, background]) if (!theme[token]) throw new Error(`app.css defines no ${token}`);
  return contrast(theme[foreground]!, theme[background]!);
}

describe("the WCAG formula", () => {
  it("matches the reference values", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2);  // the well-known gray just under AA
    expect(contrast("#fff", "#000")).toBeCloseTo(21, 5);
  });
});

describe("the dark theme", () => {
  it("is the same under prefers-color-scheme and under data-theme", () => {
    expect(DARK_BY_PREFERENCE).toEqual(DARK_BY_ATTRIBUTE);
  });
});

describe.each(THEMES)("contrast in the %s theme", (_name, theme) => {
  it.each(["--text-primary", "--text-secondary", "--text-muted"].flatMap((text) => SURFACES.map((surface) => [text, surface])))(
    "%s on %s reaches 4.5:1", (text, surface) => {
      expect(ratio(theme, text!, surface!)).toBeGreaterThanOrEqual(4.5);
    });

  // Links and link-like buttons sit on every surface, and on the note background (a .note with a link in it).
  it.each([["a", "color"], ["button.link", "color"]].flatMap(([selector, property]) =>
    [...SURFACES, "--warn-bg"].map((surface) => [selector, tokenOf(selector!, property!), surface])))(
    "link text (%s: %s) on %s reaches 4.5:1", (_selector, token, surface) => {
      expect(ratio(theme, token!, surface!)).toBeGreaterThanOrEqual(4.5);
    });

  it.each([".pill.on", "button.primary", "a.button"].map((selector) =>
    [selector, tokenOf(selector, "color"), tokenOf(selector, "background")]))(
    "%s: %s on its %s fill reaches 4.5:1", (_selector, ink, fill) => {
      expect(ratio(theme, ink!, fill!)).toBeGreaterThanOrEqual(4.5);
    });

  it.each(SURFACES.map((surface) => [tokenOf(":focus-visible", "outline"), surface]))(
    "the focus ring (%s) against %s reaches 3:1", (ring, surface) => {
      expect(ratio(theme, ring!, surface!)).toBeGreaterThanOrEqual(3);
    });
});
