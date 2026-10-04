import type { components } from "../../api/schema";
import { copy } from "../../copy/en";
import { formatMoney } from "../../lib/format";

type FeeDay = components["schemas"]["FeeDayView"];

/** The fee day in posting order: the fee row has a Terracotta marker, the deposit a green one. */
export function EvidenceDay({ day }: { day: FeeDay }) {
  const { columns } = copy.evidence;
  return (
    <div className="space-y-3">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-grey-600">
            <th scope="col" className="w-14 py-1 pl-3 font-medium">
              {columns.order}
            </th>
            <th scope="col" className="py-1 font-medium">
              {columns.description}
            </th>
            <th scope="col" className="py-1 text-right font-medium">
              {columns.amount}
            </th>
            <th scope="col" className="py-1 pr-1 text-right font-medium">
              {columns.balance}
            </th>
          </tr>
        </thead>
        <tbody>
          {day.rows.map((row) => (
            <tr key={row.position} className="border-t border-grey-200">
              <td
                className={`border-l-4 py-2 pl-3 tabular-nums ${
                  row.is_fee
                    ? "border-terracotta"
                    : row.is_deposit
                      ? "border-success"
                      : "border-transparent"
                }`}
              >
                {row.position}
              </td>
              <td className="py-2 pr-3">
                {row.description}
                {row.is_fee && <span className="sr-only">{copy.evidence.feeRow}</span>}
                {row.is_deposit && <span className="sr-only">{copy.evidence.depositRow}</span>}
              </td>
              <td
                className={`py-2 text-right tabular-nums ${row.is_deposit ? "text-success" : ""}`}
              >
                {formatMoney(row.amount)}
              </td>
              <td className="py-2 pr-1 text-right tabular-nums">
                {formatMoney(row.balance_after)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {day.summary && <p>{day.summary}</p>}
    </div>
  );
}
