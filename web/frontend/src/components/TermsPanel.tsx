import { CheckCircle, Tag, XCircle } from 'lucide-react';
import type { Terms } from '../types';

interface TermsPanelProps {
  terms: Terms;
}

export default function TermsPanel({ terms }: TermsPanelProps) {
  const selected = terms.selected ?? [];
  const leftOut = terms.left_out ?? [];
  const missedByCondition = Object.entries(terms.missed_by_condition ?? {}).filter(
    ([, missed]) => missed.length > 0,
  );

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="px-6 py-4 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900">Vocabulary Context</h2>
        <p className="text-sm text-gray-500 mt-1">
          Terms the selector put in the context list for this call
        </p>
      </div>
      <div className="p-6 space-y-6">
        <div>
          <div className="flex items-center space-x-2 mb-3">
            <CheckCircle className="w-4 h-4 text-green-600" />
            <h3 className="text-sm font-medium text-gray-900">Selected ({selected.length})</h3>
          </div>
          {selected.length === 0 ? (
            <p className="text-sm text-gray-500 italic">
              No selection recorded for this call.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {selected.map((term, idx) => (
                <span
                  key={`${term.term}-${idx}`}
                  className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-blue-100 text-blue-800"
                  title={`Source: ${term.source === 'lex' ? 'lexical' : 'phonetic'}${
                    typeof term.score === 'number' ? ` · score ${term.score.toFixed(3)}` : ''
                  }`}
                >
                  <Tag className="w-3 h-3 mr-1" />
                  {term.term}
                  <span className="ml-1 text-blue-600">({term.source})</span>
                </span>
              ))}
            </div>
          )}
        </div>

        <div>
          <div className="flex items-center space-x-2 mb-3">
            <XCircle className="w-4 h-4 text-gray-400" />
            <h3 className="text-sm font-medium text-gray-900">Left out ({leftOut.length})</h3>
          </div>
          {leftOut.length === 0 ? (
            <p className="text-sm text-gray-500 italic">Nothing left out.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {leftOut.map((term, idx) => (
                <span
                  key={`${term}-${idx}`}
                  className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-gray-100 text-gray-600"
                >
                  {term}
                </span>
              ))}
            </div>
          )}
        </div>

        {missedByCondition.length > 0 && (
          <div>
            <h3 className="text-sm font-medium text-gray-900 mb-3">
              Reference terms not produced
            </h3>
            <div className="space-y-2">
              {missedByCondition.map(([condition, missed]) => (
                <div key={condition} className="text-xs text-gray-600">
                  <span className="font-medium">{condition}:</span>{' '}
                  {missed.join(', ')}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
