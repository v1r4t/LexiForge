# Web Data Schema

This document describes the JSON schema for precomputed demo data served by the FastAPI service.

## Files

Data is read from `web/data/*.json` at startup. Missing files return empty lists/defaults with a warning, never crash.

### calls.json
Array of call objects.

```json
[
  {
    "call_id": "string",
    "call_type": "string",
    "duration_s": 0.0,
    "has_audio": true
  }
]
```

### transcripts.json
Mapping of `call_id` to transcript sets for different conditions. Each condition's tokens are tokenised as arrays of token objects.

```json
{
  "c01": {
    "baseline": [{"text": "string", "status": "same|missed|recovered|inserted"}],
    "mismatched": [{"text": "string", "status": "same|missed|recovered|inserted"}],
    "adaptive": [{"text": "string", "status": "same|missed|recovered|inserted"}],
    "oracle": [{"text": "string", "status": "same|missed|recovered|inserted"}]
  }
}
```

Token statuses:
- `same` - correctly recognised/matched
- `missed` - expected term missed
- `recovered` - term recovered with context
- `inserted` - incorrectly inserted term

### terms.json
Mapping of `call_id` to selected and left-out terms.

```json
{
  "c01": {
    "selected": [
      {"term": "string", "source": "lex|phon"}
    ],
    "left_out": ["string"]
  }
}
```

### results.json
Aggregated results and contrasts.

```json
{
  "contrasts": [
    {
      "name": "string",
      "delta_pp": 0.0,
      "ci_low": 0.0,
      "ci_high": 0.0,
      "p_holm": 0.0,
      "verdict": "string"
    }
  ],
  "control": {}
}
```

### demo_config.json
Demo configuration.

```json
{
  "mode": "precomputed"
}
```
