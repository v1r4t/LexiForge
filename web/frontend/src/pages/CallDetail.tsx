import { ArrowLeft, Clock, Phone } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { describeError, getCalls, getMeta, getTerms, getTranscripts } from '../lib/api';
import type { Call, Meta, Terms, Transcripts } from '../types';
import AudioPlayer from '../components/AudioPlayer';
import EmptyState from '../components/EmptyState';
import TermsPanel from '../components/TermsPanel';
import TokenAlignment from '../components/TokenAlignment';
import TranscriptComparison from '../components/TranscriptComparison';

export default function CallDetail() {
  const { callId } = useParams<{ callId: string }>();
  const [call, setCall] = useState<Call | null>(null);
  const [transcripts, setTranscripts] = useState<Transcripts | null>(null);
  const [terms, setTerms] = useState<Terms | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      if (!callId) return;
      try {
        const [callsData, transcriptsData, termsData, metaData] = await Promise.all([
          getCalls(),
          getTranscripts(callId),
          getTerms(callId),
          getMeta(),
        ]);
        setCall(callsData.find((c) => c.call_id === callId) ?? null);
        setTranscripts(transcriptsData);
        setTerms(termsData);
        setMeta(metaData);
      } catch (err) {
        setError(describeError(err));
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [callId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600" />
      </div>
    );
  }

  const conditions = meta?.conditions ?? [];
  const hasAudio = Boolean(callId && meta?.audio?.includes(callId));

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <Link
        to="/"
        className="inline-flex items-center space-x-2 text-sm text-gray-600 hover:text-gray-900 mb-4"
      >
        <ArrowLeft className="w-4 h-4" />
        <span>Back to Dashboard</span>
      </Link>

      {error && <EmptyState tone="error" title="Could not load this call" detail={error} />}

      {!error && !call && (
        <EmptyState
          title={`Call ${callId} is not in this dataset`}
          detail="Check the call id, or regenerate web/data with lexiforge export-web."
        />
      )}

      {!error && call && (
        <>
          <div className="mb-6">
            <h1 className="text-3xl font-bold text-gray-900 mb-2">{call.call_id}</h1>
            <div className="flex items-center space-x-4 text-sm text-gray-600">
              <div className="flex items-center space-x-1">
                <Phone className="w-4 h-4" />
                <span className="capitalize">{call.call_type.replace(/_/g, ' ')}</span>
              </div>
              {call.duration_s > 0 && (
                <div className="flex items-center space-x-1">
                  <Clock className="w-4 h-4" />
                  <span>{call.duration_s}s</span>
                </div>
              )}
            </div>
          </div>

          <div className="space-y-6">
            {callId && <AudioPlayer callId={callId} available={hasAudio} />}
            {terms && <TermsPanel terms={terms} />}
            {transcripts ? (
              <>
                <TranscriptComparison transcripts={transcripts} conditions={conditions} />
                <TokenAlignment transcripts={transcripts} />
              </>
            ) : (
              <EmptyState
                title="No transcripts for this call"
                detail="The exporter writes one entry per condition it found under transcripts/."
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
