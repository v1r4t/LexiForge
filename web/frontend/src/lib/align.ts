import type { Token } from '../types';

export type DiffOp = 'equal' | 'missing' | 'extra';

export interface AlignedRow {
  op: DiffOp;
  baseline: string | null;
  other: string | null;
  status?: Token['status'];
}

/**
 * Longest-common-subsequence alignment of two token lists.
 *
 * Used to answer the question the token chips cannot: which words did this
 * condition lose or invent relative to baseline. `missing` means the baseline
 * word is absent here; `extra` means this condition produced a word baseline
 * did not.
 */
export function alignTokens(baseline: Token[], other: Token[]): AlignedRow[] {
  const a = baseline.map((t) => t.text);
  const b = other.map((t) => t.text);

  const n = a.length;
  const m = b.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));

  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const rows: AlignedRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ op: 'equal', baseline: a[i], other: b[j], status: other[j]?.status });
      i += 1;
      j += 1;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      rows.push({ op: 'missing', baseline: a[i], other: null });
      i += 1;
    } else {
      rows.push({ op: 'extra', baseline: null, other: b[j], status: other[j]?.status });
      j += 1;
    }
  }
  while (i < n) {
    rows.push({ op: 'missing', baseline: a[i], other: null });
    i += 1;
  }
  while (j < m) {
    rows.push({ op: 'extra', baseline: null, other: b[j], status: other[j]?.status });
    j += 1;
  }
  return rows;
}

export function summarize(rows: AlignedRow[]): { missing: number; extra: number } {
  return rows.reduce(
    (acc, row) => {
      if (row.op === 'missing') acc.missing += 1;
      if (row.op === 'extra') acc.extra += 1;
      return acc;
    },
    { missing: 0, extra: 0 },
  );
}
