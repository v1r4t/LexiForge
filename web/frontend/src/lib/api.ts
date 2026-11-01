import axios from 'axios';
import type { Call, Transcripts, Terms, Results, Meta } from '../types';

// Production: the dashboard is served by the same FastAPI process, so requests
// are same-origin and need no prefix. Development: Vite proxies /api to :8000.
export const API_BASE = import.meta.env.DEV ? '/api' : '';

const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
});

/** Absolute path to a call recording (used as an <audio> src). */
export const audioUrl = (callId: string): string => `${API_BASE}/calls/${callId}/audio`;

export const getCalls = async (): Promise<Call[]> => {
  const response = await api.get('/calls');
  return response.data;
};

export const getTranscripts = async (callId: string): Promise<Transcripts> => {
  const response = await api.get(`/calls/${callId}/transcripts`);
  return response.data;
};

export const getTerms = async (callId: string): Promise<Terms> => {
  const response = await api.get(`/calls/${callId}/terms`);
  return response.data;
};

export const getResults = async (): Promise<Results> => {
  const response = await api.get('/results');
  return response.data;
};

export const getMeta = async (): Promise<Meta> => {
  const response = await api.get('/meta');
  return response.data;
};

export const getHealth = async () => {
  const response = await api.get('/health');
  return response.data;
};

export function describeError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (error.response) {
      return `API responded ${error.response.status} for ${error.config?.url ?? 'request'}`;
    }
    return `Cannot reach the dashboard API (${error.message}). Is uvicorn running on :8000?`;
  }
  return error instanceof Error ? error.message : String(error);
}
