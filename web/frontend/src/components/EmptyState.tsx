import { AlertCircle, Inbox } from 'lucide-react';

interface EmptyStateProps {
  title: string;
  detail?: string;
  tone?: 'empty' | 'error';
}

export default function EmptyState({ title, detail, tone = 'empty' }: EmptyStateProps) {
  const Icon = tone === 'error' ? AlertCircle : Inbox;
  const accent = tone === 'error' ? 'text-red-600' : 'text-gray-400';
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-10 text-center">
      <Icon className={`w-10 h-10 mx-auto mb-3 ${accent}`} />
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      {detail && <p className="text-sm text-gray-600 mt-2 max-w-xl mx-auto">{detail}</p>}
    </div>
  );
}
