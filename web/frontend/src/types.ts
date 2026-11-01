export interface Call {
  call_id: string;
  call_type: string;
  duration_s: number;
  has_audio: boolean;
  n_conditions?: number;
}

export type TokenStatus = 'same' | 'missed' | 'recovered' | 'inserted';

export interface Token {
  text: string;
  status: TokenStatus;
}

export type Transcripts = Record<string, Token[]>;

export interface SelectedTerm {
  term: string;
  source: 'lex' | 'phon';
  term_id?: string;
  score?: number;
}

export interface Terms {
  selected: SelectedTerm[];
  left_out: string[];
  missed_by_condition?: Record<string, string[]>;
}

export interface Contrast {
  name: string;
  kind?: 'h1' | 'h2' | 'control' | 'exploratory';
  unit?: string;
  delta_pp: number;
  ci_low?: number;
  ci_high?: number;
  p_holm?: number;
  n_calls?: number;
  verdict: string;
}

export interface Results {
  source?: string;
  is_sample?: boolean;
  contrasts: Contrast[];
  control: Record<string, number>;
  note?: string;
}

export interface Meta {
  data_source: string;
  is_sample: boolean;
  note: string;
  mode: string;
  conditions: string[];
  call_count: number;
  audio?: string[];
  data_dir?: string;
}
