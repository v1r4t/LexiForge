import type { Token, TokenStatus } from '../types';
import { AlertCircle, ArrowDown, ArrowUp, CheckCircle } from 'lucide-react';

interface TranscriptComparisonProps {
  transcripts: Record<string, Token[]>;
  conditions?: string[];
}

const STATUS_STYLES: Record<TokenStatus, string> = {
  same: 'bg-green-100 text-green-800',
  missed: 'bg-red-100 text-red-800',
  recovered: 'bg-blue-100 text-blue-800',
  inserted: 'bg-orange-100 text-orange-800',
};

const CONDITION_STYLES: Record<string, string> = {
  baseline: 'gray',
  oracle: 'green',
  'oracle-200': 'green',
  'oracle-minimal': 'green',
  adaptive: 'blue',
  'adaptive-200': 'blue',
  mismatched: 'red',
  'mismatched-200': 'red',
};

const CONDITION_LABELS: Record<string, string> = {
  baseline: 'Baseline (no context)',
  mismatched: 'Mismatched (irrelevant list)',
  'mismatched-200': 'Mismatched-200 (irrelevant list)',
  adaptive: 'Adaptive (selected)',
  'adaptive-200': 'Adaptive-200 (selected + padding)',
  oracle: 'Oracle (relevant)',
  'oracle-200': 'Oracle-200 (relevant + padding)',
  'oracle-minimal': 'Oracle-minimal (spoken terms only)',
  'static-head-200': 'Static head-200 (fixed list)',
  'random-200': 'Random-200',
  dilution: 'Dilution',
  'near-miss': 'Near-miss',
};

function statusIcon(status: TokenStatus) {
  switch (status) {
    case 'same':
      return <CheckCircle className="w-3 h-3" />;
    case 'missed':
      return <AlertCircle className="w-3 h-3" />;
    case 'recovered':
      return <ArrowUp className="w-3 h-3" />;
    case 'inserted':
      return <ArrowDown className="w-3 h-3" />;
    default:
      return null;
  }
}

function labelFor(condition: string) {
  return CONDITION_LABELS[condition] ?? condition;
}

export default function TranscriptComparison({
  transcripts,
  conditions,
}: TranscriptComparisonProps) {
  const order = conditions && conditions.length ? conditions : Object.keys(transcripts);
  const present = order.filter((c) => transcripts[c]);
  const missing = order.filter((c) => !transcripts[c]);

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="px-6 py-4 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900">Transcript Comparison</h2>
        <p className="text-sm text-gray-500 mt-1">
          Token-level view across the conditions present in this dataset
        </p>
      </div>
      <div className="divide-y divide-gray-200">
        {present.map((condition) => {
          const tokens = transcripts[condition] ?? [];
          return (
            <div key={condition} className="p-6">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-gray-900">
                  {labelFor(condition)}
                  {CONDITION_STYLES[condition] && (
                    <span className="ml-2 text-xs font-normal text-gray-400">
                      ({CONDITION_STYLES[condition]} arm)
                    </span>
                  )}
                </h3>
                <span className="text-xs text-gray-500">{tokens.length} tokens</span>
              </div>
              {tokens.length === 0 ? (
                <p className="text-sm text-gray-500 italic">No transcript recorded for this condition.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {tokens.map((token, idx) => (
                    <span
                      key={`${condition}-${idx}`}
                      className={`inline-flex items-center space-x-1 px-2 py-1 rounded-md text-xs font-medium ${
                        STATUS_STYLES[token.status] ?? 'bg-gray-100 text-gray-800'
                      }`}
                      title={token.status}
                    >
                      {statusIcon(token.status)}
                      <span>{token.text}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {missing.length > 0 && (
          <div className="p-6">
            <p className="text-sm text-gray-500">
              Not run for this call: {missing.map(labelFor).join(', ')}
            </p>
          </div>
        )}
      </div>
      <div className="px-6 py-4 bg-gray-50 border-t border-gray-200">
        <div className="flex flex-wrap items-center gap-4 text-xs">
          <div className="flex items-center space-x-1">
            <CheckCircle className="w-3 h-3 text-green-600" />
            <span className="text-gray-600">Same — unchanged text</span>
          </div>
          <div className="flex items-center space-x-1">
            <ArrowUp className="w-3 h-3 text-blue-600" />
            <span className="text-gray-600">Recovered — glossary term present and in reference</span>
          </div>
          <div className="flex items-center space-x-1">
            <ArrowDown className="w-3 h-3 text-orange-600" />
            <span className="text-gray-600">Inserted — glossary term absent from reference</span>
          </div>
          <div className="flex items-center space-x-1">
            <AlertCircle className="w-3 h-3 text-red-600" />
            <span className="text-gray-600">Missed — reference term not produced</span>
          </div>
        </div>
      </div>
    </div>
  );
}
