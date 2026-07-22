export function money(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  return "$" + x.toLocaleString("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function pct(x: number): string {
  return Math.round(x * 100) + "%";
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

export function ym(year: number, month: number): string {
  return `${MONTHS[(month - 1) % 12]} ${year}`;
}

export function prettyDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-SG", { day: "2-digit", month: "short", year: "numeric" });
}

export function titleCase(s: string): string {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}
