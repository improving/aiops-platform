export type Cell = string | number | null | undefined;

function cell(value: Cell): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** RFC 4180: comma separated, CRLF line ends, quotes doubled. */
export function toCsv(headers: string[], rows: Cell[][]): string {
  rows.forEach((row, i) => {
    if (row.length !== headers.length) {
      throw new Error(
        `toCsv: row ${i} has ${row.length} cells, expected ${headers.length}`
      );
    }
  });
  return (
    [headers, ...rows].map((r) => r.map(cell).join(",")).join("\r\n") + "\r\n"
  );
}

/** Triggers a browser download of `text` as `filename`. */
export function downloadTextFile(
  filename: string,
  text: string,
  mime = "text/csv"
) {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
