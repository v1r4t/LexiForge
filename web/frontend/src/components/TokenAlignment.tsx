import { useMemo } from 'react';
import { ArrowRight, Minus, Plus } from 'lucide-react';
import { alignTokens, summarize } from '../lib/align';
import type { Token } from '../types';

interface TokenAlignmentProps {
  transcripts: Record<string, Token[]>;
  baselineKey?: string;
}

const STATUS_TEXT: Record<string, string> = {
  same: 'text-gray-700',
  recovered: 'text-blue-700',
  inserted: 'text-orange-700',
  missed: 'text-red-700',
};

export default function TokenAlignment({
  transcripts,
  baselineKey = 'baseline',
}: TokenAlignmentProps) {
  const baseline = transcripts[baselineKey];
  const others = Object.entries(transcripts).filter(([key]) => key !== baselineKey);

  const rowsByCondition = useMemo(
    () =>
      others.map(([condition, tokens]) => ({
        condition,
        rows: baseline ? alignTokens(baseline, tokens) : [],
        summary: baseline ? summarize(alignTokens(baseline, tokens)) : { missing: 0, extra: 0 },
      })),
    [baseline, others],
  );

  if (!baseline) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-2">Alignment to baseline</h2>
        <p className="text-sm text-gray-500">
          This dataset has no <code className="font-mono">{baselineKey}</code> condition, so there
          is nothing to align against.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="px-6 py-4 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900">Alignment to baseline</h2>
        <p className="text-sm text-gray-500 mt-1">
          Word-level diff. <span className="text-red-700">Struck</span> words were lost;{' '}
          <span className="text-orange-700">added</span> words were not in baseline.
        </p>
      </div>
      <div className="divide-y divide-gray-200">
        {rowsByCondition.map(({ condition, rows, summary }) => (
          <div key={condition} className="p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-gray-900 flex items-center gap-2">
                <span className="text-gray-500">baseline</span>
                <ArrowRight className="w-3 h-3 text-gray-400" />
                <span>{condition}</span>
              </h3>
              <div className="flex items-center gap-3 text-xs">
                <span className="inline-flex items-center gap-1 text-red-700">
                  <Minus className="w-3 h-3" />
                  {summary.missing} lost
                </span>
                <span className="inline-flex items-center gap-1 text-orange-700">
                  <Plus className="w-3 h-3" />
                  {summary.extra} added
                </span>
              </div>
            </div>

            {rows.length === 0 ? (
              <p className="text-sm text-gray-500 italic">No transcript for this condition.</p>
            ) : (
              <div className="flex flex-wrap items-center gap-x-2 gap-y-2 text-sm">
                {rows.map((row, index) => {
                  if (row.op === 'equal') {
                    return (
                      <span
                        key={`${condition}-${index}`}
                        className={`${STATUS_TEXT[row.status ?? 'same'] ?? 'text-gray-700'}`}
                      >
                        {row.other}
                      </span>
                    );
                  }
                  if (row.op === 'missing') {
                    return (
                      <span
                        key={`${condition}-${index}`}
                        className="rounded bg-red-50 px-1 text-red-700 line-through decoration-red-400"
                        title="In baseline, missing here"
                      >
                        {row.baseline}
                      </span>
                    );
                  }
                  return (
                    <span
                      key={`${condition}-${index}`}
                      className="rounded bg-orange-50 px-1 text-orange-700"
                      title="Not present in baseline"
                    >
                      {row.other}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
