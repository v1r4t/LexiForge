import type { Results } from '../types';
import { AlertTriangle, BarChart3, TrendingDown } from 'lucide-react';

interface ResultsSummaryProps {
  results: Results;
}

function pickContrast(results: Results, kind: 'h1' | 'h2') {
  const byKind = results.contrasts.find((c) => c.kind === kind);
  if (byKind) return byKind;
  // Fallback for exports without an explicit kind.
  const needle = kind === 'h1' ? /recall/i : /insertion/i;
  return results.contrasts.find((c) => needle.test(c.name));
}

const isNegative = (value: number) => value < 0;

export default function ResultsSummary({ results }: ResultsSummaryProps) {
  const h1 = pickContrast(results, 'h1');
  const h2 = pickContrast(results, 'h2');

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
      <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-gray-600">Reported contrasts</h3>
          <BarChart3 className="w-5 h-5 text-blue-600" />
        </div>
        <div className="text-2xl font-bold text-gray-900 mb-1">
          {results.contrasts.length}
        </div>
        <p className="text-xs text-gray-500">
          {results.is_sample ? 'sample values — not results' : 'from scored output'}
        </p>
      </div>

      {h1 && (
        <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-gray-600">H1: term recall</h3>
            <TrendingDown className="w-5 h-5 text-red-600" />
          </div>
          <div
            className={`text-2xl font-bold mb-1 ${
              isNegative(h1.delta_pp) ? 'text-red-600' : 'text-gray-900'
            }`}
          >
            {h1.delta_pp > 0 ? '+' : ''}
            {h1.delta_pp.toFixed(1)} pp
          </div>
          <p className="text-xs text-gray-500">
            {typeof h1.ci_low === 'number' && typeof h1.ci_high === 'number'
              ? `CI [${h1.ci_low.toFixed(1)}, ${h1.ci_high.toFixed(1)}]`
              : 'no interval in export'}
            {typeof h1.n_calls === 'number' ? ` · n=${h1.n_calls} calls` : ''}
          </p>
        </div>
      )}

      {h2 && (
        <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-gray-600">H2: insertions</h3>
            <AlertTriangle className="w-5 h-5 text-orange-600" />
          </div>
          <div className="text-2xl font-bold text-gray-900 mb-1">
            {h2.delta_pp > 0 ? '+' : ''}
            {h2.delta_pp.toFixed(2)}
          </div>
          <p className="text-xs text-gray-500">
            {h2.unit ?? 'per utterance'}
            {typeof h2.p_holm === 'number' ? ` · p=${h2.p_holm.toFixed(4)}` : ''}
          </p>
        </div>
      )}
    </div>
  );
}
