import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const srcDir = import.meta.dirname;
const css = readFileSync(join(srcDir, "index.css"), "utf8");

function sourceFiles(): string[] {
  return readdirSync(srcDir, { recursive: true, encoding: "utf8" })
    .filter((path) => /\.(ts|tsx|css)$/.test(path))
    .filter((path) => !path.includes(".test."));
}

describe("Blossom theme", () => {
  it.each([
    ["navy", "#001d3d"],
    ["clay", "#efeeed"],
    ["terracotta", "#dc634b"],
    ["white", "#ffffff"],
    ["success", "#1f7a4d"],
    ["error", "#b42318"],
  ])("defines the %s colour as %s", (name, value) => {
    expect(css).toMatch(new RegExp(`--color-${name}:\\s*${value};`, "i"));
  });

  it("defines a neutral grey scale from 50 to 900", () => {
    for (const step of [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]) {
      expect(css).toMatch(new RegExp(`--color-grey-${String(step)}:\\s*#[0-9a-f]{6};`, "i"));
    }
  });

  it("drops Tailwind's default palette so only Blossom colours exist", () => {
    expect(css).toMatch(/--color-\*:\s*initial;/);
  });

  it("self-hosts its fonts instead of calling a font service", () => {
    expect(css).toContain("@fontsource-variable/inter");
    expect(css).toContain("@fontsource-variable/source-serif-4");
    expect(css).not.toMatch(/fonts\.googleapis\.com/);
  });

  it("never uses Terracotta for text, because it fails contrast for normal text", () => {
    const forbidden = ["text", "terracotta"].join("-");
    const offenders = sourceFiles().filter((path) =>
      readFileSync(join(srcDir, path), "utf8").includes(forbidden),
    );

    expect(offenders).toEqual([]);
  });
});

describe("Motion", () => {
  it("stops every animation and transition when Luis asks for reduced motion", () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    expect(css).toMatch(/transition-duration: 0\.01ms !important/);
    expect(css).toMatch(/animation-duration: 0\.01ms !important/);
  });

  it("says on every class that moves what happens with reduced motion", () => {
    const moves = /\b(transition|animate-[a-z]+)\b/;
    const saysSo = /motion-(safe|reduce):/;
    const offenders = sourceFiles()
      .filter((path) => path.endsWith(".tsx"))
      .flatMap((path) =>
        readFileSync(join(srcDir, path), "utf8")
          .split("\n")
          .filter((line) => line.includes("className") || line.includes('"'))
          .filter((line) => moves.test(line) && !saysSo.test(line))
          .map((line) => `${path}: ${line.trim()}`),
      );

    expect(offenders).toEqual([]);
  });
});
