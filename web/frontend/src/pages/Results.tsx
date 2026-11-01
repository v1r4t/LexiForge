import { useEffect, useState } from 'react';
import { BarChart3, Info } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { describeError, getResults } from '../lib/api';
import type { Results } from '../types';
import EmptyState from '../components/EmptyState';
import ResultsSummary from '../components/ResultsSummary';

function format(value: number | undefined, digits = 3): string {
  return typeof value === 'number' ? value.toFixed(digits) : '—';
}

export default function ResultsPage() {
  const [results, setResults] = useState<Results | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getResults()
      .then(setResults)
      .catch((err) => setError(describeError(err)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <EmptyState tone="error" title="Could not load results" detail={error} />
      </div>
    );
  }

  const contrasts = results?.contrasts ?? [];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Results</h1>
        <p className="text-gray-600">
          Paired differences across conditions. Inference lives in
          {' '}<code className="font-mono text-sm">lexiforge.analysis.inference</code>.
        </p>
      </div>

      {results?.is_sample && (
        <div className="mb-6 bg-amber-50 border border-amber-300 rounded-lg p-4 text-sm text-amber-900">
          <span className="font-semibold">Sample values.</span> These rows are
          hand-written placeholders, not measured output.
        </div>
      )}

      {results && <ResultsSummary results={results} />}

      {contrasts.length === 0 ? (
        <EmptyState
          title="No contrasts in this dataset"
          detail="Run lexiforge export-web after scoring; the exporter computes descriptive paired differences from scored recalls."
        />
      ) : (
        <>
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden mb-6">
            <div className="px-6 py-4 border-b border-gray-200">
              <h2 className="text-lg font-semibold text-gray-900">Paired differences</h2>
              <p className="text-sm text-gray-500 mt-1">
                {results?.is_sample
                  ? 'Placeholder deltas for dashboard layout'
                  : 'Descriptive differences from the exported dataset'}
              </p>
            </div>
            <div className="px-6 py-4 h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={contrasts.map((c) => ({
                    name: c.name.length > 32 ? `${c.name.slice(0, 29)}…` : c.name,
                    fullName: c.name,
                    delta_pp: c.delta_pp,
                    kind: c.kind,
                  }))}
                  margin={{ top: 5, right: 30, left: 20, bottom: 60 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="name" angle={-35} textAnchor="end" height={80} tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} label={{ value: 'Δ (pp)', angle: -90, position: 'insideLeft' }} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' }}
                    formatter={(value: number) => [`${value > 0 ? '+' : ''}${value.toFixed(3)} pp`, 'Δ']}
                    labelFormatter={(_, payload) => payload?.[0]?.payload?.fullName || ''}
                  />
                  <Bar dataKey="delta_pp" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Contrasts</h2>
            <p className="text-sm text-gray-500 mt-1">
              {results?.is_sample
                ? 'Placeholder rows'
                : 'Descriptive; Holm-corrected p-values appear only when exported by the analysis step'}
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {['Contrast', 'Kind', 'Δ', 'CI', 'p (Holm)', 'Verdict'].map((head) => (
                    <th
                      key={head}
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                    >
                      {head}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {contrasts.map((contrast, idx) => (
                  <tr key={`${contrast.name}-${idx}`} className="hover:bg-gray-50">
                    <td className="px-6 py-4 text-sm font-medium text-gray-900">
                      {contrast.name}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-xs text-gray-600">
                      {contrast.kind ?? '—'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <span
                        className={
                          contrast.delta_pp < 0
                            ? 'text-red-600'
                            : contrast.delta_pp > 0
                              ? 'text-green-600'
                              : 'text-gray-600'
                        }
                      >
                        {contrast.delta_pp > 0 ? '+' : ''}
                        {format(contrast.delta_pp)}
                      </span>
                      <span className="ml-1 text-xs text-gray-400">
                        {contrast.unit === 'pp' ? 'pp' : contrast.unit ?? ''}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {typeof contrast.ci_low === 'number' && typeof contrast.ci_high === 'number'
                        ? `[${format(contrast.ci_low)}, ${format(contrast.ci_high)}]`
                        : '—'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {format(contrast.p_holm, 4)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          contrast.verdict.toLowerCase().includes('support')
                            ? 'bg-green-100 text-green-800'
                            : contrast.verdict.toLowerCase().includes('reject')
                              ? 'bg-red-100 text-red-800'
                              : 'bg-yellow-100 text-yellow-800'
                        }`}
                      >
                        {contrast.verdict}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        </>
      )}

      <div className="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex items-start space-x-3">
          <Info className="w-5 h-5 text-blue-600 mt-0.5" />
          <div>
            <h3 className="text-sm font-medium text-blue-900">How to read this</h3>
            <p className="text-sm text-blue-700 mt-1">
              Primary inference is a paired sign-flip permutation across
              conversations, with a wild cluster bootstrap-t as a cross-check and
              Holm correction over the confirmatory family (H1, H2). The dashboard
              renders what the export supplies and never computes p-values itself.
              Values are shown with units as exported (pp or per utterance).
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
