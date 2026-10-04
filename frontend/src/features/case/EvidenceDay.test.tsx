import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { copy } from "../../copy/en";
import { anaReady } from "../../test/caseFixtures";
import { EvidenceDay } from "./EvidenceDay";

const day = anaReady.evidence.fee_day;
if (day === null) throw new Error("Ana's fixture has a fee day");

describe("What happened on the fee day", () => {
  it("lists the day's transactions in posting order", () => {
    render(<EvidenceDay day={day} />);

    const rows = screen.getAllByRole("row").slice(1); // the first row is the header
    expect(rows.map((row) => within(row).getAllByRole("cell")[0]?.textContent)).toEqual([
      "1",
      "2",
      "3",
    ]);
    expect(within(rows[0] ?? document.body).getByText("−$60")).toBeInTheDocument();
    expect(within(rows[2] ?? document.body).getByText("$1,325")).toBeInTheDocument();
  });

  it("marks the fee row and the deposit row", () => {
    render(<EvidenceDay day={day} />);

    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[1] ?? document.body).getByText(copy.evidence.feeRow)).toBeInTheDocument();
    expect(
      within(rows[2] ?? document.body).getByText(copy.evidence.depositRow),
    ).toBeInTheDocument();
    expect(within(rows[0] ?? document.body).queryByText(copy.evidence.feeRow)).toBeNull();
  });

  it("ends with what the balance would have been", () => {
    render(<EvidenceDay day={day} />);

    expect(
      screen.getByText(
        "If the paycheck had posted first, the balance would have stayed at $1,360.",
      ),
    ).toBeInTheDocument();
  });
});
