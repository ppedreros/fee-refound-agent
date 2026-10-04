import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { copy } from "../../copy/en";
import { feeAmbiguous } from "../../test/caseFixtures";
import { FeePicker } from "./FeePicker";

function renderPicker() {
  const onRun = vi.fn();
  render(<FeePicker view={feeAmbiguous} disabled={false} onRun={onRun} />);
  return { onRun };
}

describe("FeePicker", () => {
  it("shows one row per fee, told apart by the payment that caused it", () => {
    renderPicker();

    const picker = screen.getByRole("radiogroup", { name: copy.card.pickFee });
    expect(
      within(picker)
        .getAllByRole("radio")
        .map((radio) => radio.closest("label")?.textContent),
    ).toEqual(feeAmbiguous.candidates.map((candidate) => candidate.label));
  });

  it("can't check again until a fee is picked", () => {
    renderPicker();

    expect(screen.getByRole("button", { name: copy.actions.checkWithFee })).toBeDisabled();
  });

  it("checks again with the fee Luis picks", async () => {
    const user = userEvent.setup();
    const { onRun } = renderPicker();

    await user.click(screen.getByRole("radio", { name: /STREAMFLIX/ }));
    await user.click(screen.getByRole("button", { name: copy.actions.checkWithFee }));

    expect(onRun).toHaveBeenCalledWith(90904);
  });
});
