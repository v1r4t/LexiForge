import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { getMeta } from '../lib/api';
import type { Meta } from '../types';

/**
 * Always-on data provenance banner. A pre-registered study must never let a
 * reader mistake placeholder numbers for measured results, so the sample set
 * is labelled on every page rather than in a footnote.
 */
export default function SampleBanner() {
  const [meta, setMeta] = useState<Meta | null>(null);

  useEffect(() => {
    getMeta()
      .then(setMeta)
      .catch(() => setMeta(null));
  }, []);

  if (!meta) return null;

  if (meta.is_sample) {
    return (
      <div className="bg-amber-50 border-b border-amber-300">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" />
          <div className="text-sm text-amber-900">
            <span className="font-semibold">Illustrative sample data — not results.</span>{' '}
            Every number and transcript on this page is hand-written to exercise the
            interface. Run <code className="font-mono">lexiforge export-web</code> after
            scoring to replace it with measured output.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-50 border-b border-slate-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-2 text-xs text-slate-600">
        Data source: <span className="font-medium">{meta.data_source}</span>
        {meta.note ? <> — {meta.note}</> : null}
      </div>
    </div>
  );
}
