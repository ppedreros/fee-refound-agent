import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, type Health } from "../api/client";
import { copy } from "../copy/en";
import { renderWithClient } from "../test/render";
import { Header } from "./Header";

vi.mock("../api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api/client")>();
  return { ...original, api: { health: vi.fn() } };
});

const health = vi.mocked(api.health);

function reports(jev: "live" | "replay", openai: "live" | "replay"): Health {
  return { status: "ok", database: "ok", provider_mode: { jev, openai }, version: "abc1234" };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("Header", () => {
  it("says, discreetly, when model answers come from recordings", async () => {
    health.mockResolvedValue(reports("replay", "replay"));

    renderWithClient(<Header />);

    const note = await screen.findByText(copy.app.replay);
    expect(note.closest("[title]")).toHaveAttribute("title", copy.app.replayTooltip);
    expect(screen.getByRole("heading", { level: 1, name: copy.app.title })).toBeInTheDocument();
  });

  it("says so when even one model answers from recordings", async () => {
    health.mockResolvedValue(reports("live", "replay"));

    renderWithClient(<Header />);

    expect(await screen.findByText(copy.app.replay)).toBeInTheDocument();
  });

  it("shows nothing extra when every model answers live", async () => {
    health.mockResolvedValue(reports("live", "live"));

    renderWithClient(<Header />);

    await vi.waitFor(() => {
      expect(health).toHaveBeenCalled();
    });
    expect(screen.queryByText(copy.app.replay)).toBeNull();
  });

  it("shows nothing extra when the health check fails", async () => {
    health.mockRejectedValue(new ApiError(copy.errors.unexpected, 503, null));

    renderWithClient(<Header />);

    await vi.waitFor(() => {
      expect(health).toHaveBeenCalled();
    });
    expect(screen.queryByText(copy.app.replay)).toBeNull();
  });
});
