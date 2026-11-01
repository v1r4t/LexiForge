import { useEffect, useState } from 'react';
import { Activity, FileText, Phone } from 'lucide-react';
import { describeError, getCalls, getMeta, getResults } from '../lib/api';
import type { Call, Meta, Results } from '../types';
import CallList from '../components/CallList';
import ResultsSummary from '../components/ResultsSummary';
import EmptyState from '../components/EmptyState';

export default function Dashboard() {
  const [calls, setCalls] = useState<Call[]>([]);
  const [results, setResults] = useState<Results | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [callsData, resultsData, metaData] = await Promise.all([
          getCalls(),
          getResults(),
          getMeta(),
        ]);
        setCalls(callsData);
        setResults(resultsData);
        setMeta(metaData);
      } catch (err) {
        setError(describeError(err));
      } finally {
        setLoading(false);
      }
    };
    fetchData();
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
        <EmptyState
          tone="error"
          title="Could not load dashboard data"
          detail={error}
        />
      </div>
    );
  }

  const conditionCount = meta?.conditions.length ?? 0;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">LexiForge Dashboard</h1>
        <p className="text-gray-600">
          Vocabulary-risk testing for Gnani Prisma v3.0 on Hinglish banking speech recognition
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-gray-600">Total Calls</h3>
            <Phone className="w-5 h-5 text-blue-600" />
          </div>
          <div className="text-2xl font-bold text-gray-900 mb-1">{calls.length}</div>
          <p className="text-xs text-gray-500">Synthetic test cases</p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-gray-600">Conditions</h3>
            <Activity className="w-5 h-5 text-green-600" />
          </div>
          <div className="text-2xl font-bold text-gray-900 mb-1">{conditionCount}</div>
          <p className="text-xs text-gray-500">
            {meta?.conditions.length ? meta.conditions.join(', ') : 'none in dataset'}
          </p>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-gray-600">Data Source</h3>
            <FileText className="w-5 h-5 text-purple-600" />
          </div>
          <div className="text-2xl font-bold text-gray-900 mb-1 capitalize">
            {meta?.is_sample ? 'Sample' : meta?.data_source ?? 'unknown'}
          </div>
          <p className="text-xs text-gray-500">
            {meta?.is_sample ? 'illustrative, not measured' : 'exported from scored output'}
          </p>
        </div>
      </div>

      {results && results.contrasts.length > 0 && <ResultsSummary results={results} />}

      {calls.length === 0 ? (
        <EmptyState
          title="No calls in this dataset"
          detail="Add calls.json to web/data/ (or run lexiforge export-web) and the dashboard will pick it up without a restart."
        />
      ) : (
        <CallList calls={calls} />
      )}
    </div>
  );
}
