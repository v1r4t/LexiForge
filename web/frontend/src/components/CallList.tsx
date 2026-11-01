import { Phone, Clock, Mic } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { Call } from '../types';

interface CallListProps {
  calls: Call[];
}

export default function CallList({ calls }: CallListProps) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="px-6 py-4 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900">Test Calls</h2>
        <p className="text-sm text-gray-500 mt-1">Synthetic Hinglish banking calls</p>
      </div>
      <div className="divide-y divide-gray-200">
        {calls.map((call) => (
          <Link
            key={call.call_id}
            to={`/calls/${call.call_id}`}
            className="flex items-center justify-between px-6 py-4 hover:bg-gray-50 transition-colors"
          >
            <div className="flex items-center space-x-4">
              <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                <Phone className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">{call.call_id}</div>
                <div className="text-xs text-gray-500 capitalize">{call.call_type.replace('_', ' ')}</div>
              </div>
            </div>
            <div className="flex items-center space-x-6">
              <div className="flex items-center space-x-2 text-sm text-gray-500">
                <Clock className="w-4 h-4" />
                <span>{call.duration_s}s</span>
              </div>
              {call.has_audio && (
                <div className="flex items-center space-x-2 text-sm text-green-600">
                  <Mic className="w-4 h-4" />
                  <span>Audio</span>
                </div>
              )}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
