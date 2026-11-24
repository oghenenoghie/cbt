import type { PracticalTable } from "@/lib/types";

import styles from "./Practical.module.css";

/**
 * A practical's table of readings or results (ADR 0006 decision 8). It holds no answers, so
 * staff and student screens both show it. Wide tables scroll inside their frame, not the page.
 */
export function PracticalTableView({ table }: { table: PracticalTable | null | undefined }) {
  if (!table) return null;
  return (
    <div className={styles.tableWrap} tabIndex={0} role="region" aria-label="Table of readings">
      <table className={styles.table}>
        <thead>
          <tr>
            {table.columns.map((column, index) => (
              <th key={index} scope="col">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, r) => (
            <tr key={r}>
              {row.map((cell, c) => (
                <td key={c}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
