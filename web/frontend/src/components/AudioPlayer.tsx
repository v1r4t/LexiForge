import { useEffect, useState } from 'react';
import { Volume2 } from 'lucide-react';
import { audioUrl } from '../lib/api';

interface AudioPlayerProps {
  callId: string;
  available: boolean;
}

/**
 * Renders only when the recording actually resolves. Audio is gitignored, so a
 * fresh clone has none; showing a broken player would be worse than showing
 * nothing.
 */
export default function AudioPlayer({ callId, available }: AudioPlayerProps) {
  const [reachable, setReachable] = useState(false);

  useEffect(() => {
    if (!available) {
      setReachable(false);
      return;
    }
    let cancelled = false;
    fetch(audioUrl(callId), { method: 'HEAD' })
      .then((response) => {
        if (!cancelled) setReachable(response.ok);
      })
      .catch(() => {
        if (!cancelled) setReachable(false);
      });
    return () => {
      cancelled = true;
    };
  }, [callId, available]);

  if (!reachable) return null;

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
      <div className="flex items-center gap-2 mb-2 text-sm font-medium text-gray-700">
        <Volume2 className="w-4 h-4 text-blue-600" />
        Call recording
      </div>
      <audio controls preload="none" src={audioUrl(callId)} className="w-full">
        <track kind="captions" />
      </audio>
    </div>
  );
}
