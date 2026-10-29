**1) NONDETERMINISM BUDGET**

If a borderline word flips at rate f per file across runs, the expected number of files that change at least once between two runs is N * 2*f*(1-f) for independent flips (symmetric two-outcome approximation). Approximate expected changes per pass with N=100 files:

| Flip rate f (per file) | Expected files changed between runs | % of corpus | Operational impact |
|---|---|---|---|
| 2% | ~3.9 | 3.9% | Marginal; likely noise if unpaired. |
| 5% | ~9.5 | 9.5% | Noticeable; can mask small deltas. |
| 10% | ~18.0 | 18.0% | Material; borderline words dominate variance at small effects. |

**Why this matters more for paired contrasts than absolute accuracy:** Absolute accuracy averages over all files, so single-file flips partially cancel or are diluted by the mean. Paired differences (Δ_i = acc_cond_i - acc_base_i) flip sign when either file flips in opposite directions or one flips and the other doesn't; correlation between baseline and condition runs matters. With common audio and similar decoding, flips are not independent across paired runs - but even modest correlation leaves a large paired-variance component. A small absolute shift can be swamped or created spuriously by per-file nondeterminism if contrasts are unpaired or under-replicated. Treat per-file flip rate as the budget, not just corpus-level noise.

**2) REPLICATION DESIGN**

The prior concern is valid: mean-of-3 baseline vs single-run condition biases paired SE downward by ~ (2/3) of the run variance. Fix with **equal replicate counts for primary contrasts**.

| Group | Runs per condition | Which conditions | Rationale |
|---|---|---|---|
| **Primary contrasts (hypothesis tests)** | 3 each | baseline, static-200, random-200, adaptive-200, BM25-200, oracle-minimal, oracle-200, mismatched-200 | Paired comparisons require symmetric replication to get unbiased paired variance. Mean-of-3 vs mean-of-3 properly weights run-to-run variance; mean-of-3 vs 1 undercounts it. Defensible by design (controls Type I error), not convenience. |
| **Exploratory/sweep** | 1 each | full sweep grid points (and any post-hoc scans) | Hypothesis space is large; use single runs for mapping shape, but do **not** treat these as primary confirmatory contrasts. If any sweep point becomes primary, promote to 3. |
| **Variance-estimation subset** | >=3 repeats (see §3) | stratified sample (separate from full runs) | Dedicated measurement, not conflated with experimental conditions. | 

Enforce: for every paired contrast in the pre-registered confirmatory set, `n_rep(cond)=n_rep(base)`. Record replicate indices in the manifest (section 6).

**3) ESTIMATING RUN-TO-RUN VARIANCE CHEAPLY**

**Subset:** Stratify 25 files from the 100-file set to cover: (a) borderline cases (near decision boundaries for keyterms), (b) OOVs, (c) confusable pairs (§2 of controls), (d) clean cases. Avoid cherry-picking easy files; log stratification.

**Repeats:** Run the same condition (e.g. baseline) **5 independent runs** on this subset (separate job submissions; do not reuse cached results as "repeats"). More repeats reduce variance of the variance estimator; 5 is cheap (125 file-calls extra) and stable enough for planning; if variance is borderline, increase to 7.

**Estimator:** Let $Y_{i,r}$ be accuracy/error metric for file $i$ in run $r$, $i=1..n_s$, $r=1..R$. For paired differences against a reference run $r_0$ (or for a condition), define $D_{i,r} = Y_{i,r}^{(cond)} - Y_{i,r}^{(base)}$. 

Total variance of the paired mean difference includes file and run components:
$$
\widehat{\mathrm{Var}}(\bar{D}_{\cdot,\cdot}) = \frac{\widehat{\sigma}^2_D}{n_s R} + \frac{(R-1)}{R}\cdot\frac{\widehat{\sigma}^2_{D,\text{run}}}{n_s ?}
$$
More directly, decompose $D_{i,r} = \mu_D + \alpha_i + \beta_r + \epsilon_{i,r}$ (file/run effects). Estimate run-to-run variance from repeats:
$$
\widehat{\sigma}^2_{run} = \frac{1}{n_s (R-1)}\sum_{i=1}^{n_s}\sum_{r=1}^{R} (D_{i,r} - \bar{D}_{i,\cdot})^2, \quad \widehat{\sigma}^2_{file} = \frac{R}{n_s - 1}\sum_{i=1}^{n_s} (\bar{D}_{i,\cdot} - \bar{D}_{\cdot,\cdot})^2 - \widehat{\sigma}^2_{run}.
$$
Use a paired t on means across runs or a mixed model; crucially include the **between-run** term. If only comparing means-of-3, the run variance contribution is $\widehat{\sigma}^2_{run}/R$ per condition and must be preserved in the paired SE (equal R required). Also compute intraclass correlation across runs to quantify dependence.

**4) CACHING POLICY**

**Cache key (required):** `sha256(audio_bytes) + sha256(context_json) + model_id + response_format + api_version` (include any decoding params if exposed). Cache entries store: key, request hash, response (transcript + metadata), job/file IDs, timestamp, `cache_hit=true/false`, and a `replicate_allowed` flag.

**Rules:**
- **Detect repeats, don't reuse.** If the same (audio+context+model+format) appears again as a *separate replicate* in the replication plan, it **must not** be a silent cache hit. Either (a) disable cache for planned replicates, (b) issue with a `replicate_id` that is part of the key only for measurement runs (or explicitly bypass), or (c) tag requests as `measurement=true` and force fresh calls. The cache must log `bypass_reason='planned_replicate'`.
- **Caching a repeat and calling it a replicate is a fatal error.** A cached response has zero run-to-run variance and will artificially collapse $\widehat{\sigma}^2_{run}$ toward 0, biasing paired SE down by the same mechanism as unbalanced replication (and undetectably). This invalidates all variance estimates and any inference that relies on run variance.
- **Other uses:** Caching is allowed for debugging/retries of failed jobs, but every cached hit used in reported numbers must be excluded from variance estimation and flagged in the manifest. Track hit rate separately.

**5) IF RUN VARIANCE IS AS LARGE AS THE EFFECT**

If $\widehat{\sigma}^2_{run} \gtrsim \delta^2$ where $\delta$ is the observed/predicted paired effect (or CI width comparable to effect), take these actions:

- **Fallback claim:** Shift from "X outperforms Y by $\delta$" to **"no statistically distinguishable difference at this sample size given observed run-to-run variance"** (or report the minimum detectable effect under observed variance). Do not increase claims; increase replication or narrow the claim.
- **Write-up changes:** (a) Report run-to-run variance explicitly (± run variance) separate from file variance. (b) Justify replication level used. (c) If only 1 run exists for a contrast, **downgrade to exploratory** and remove confirmatory language. (d) Compute MDE for paired design with equal R: $MDE \approx z_{1-\alpha/2}+z_{1-\beta})\sqrt{2(\widehat{\sigma}^2_{file} + \widehat{\sigma}^2_{run}/R)/n}$ and show it's > $\delta$. (e) Consider increasing R for primary contrasts (to 5) or accepting null; do not "average away" by pooling unbalanced designs.
- **Decision rule:** Pre-commit: if observed run variance makes MDE > smallest effect of interest, the experiment is underpowered for confirmatory claims with available budget - state this limitation.

**6) ONE-PAGE EXPERIMENT MANIFEST ENTRY (PER RUN)**

Every submitted run must emit a manifest row with these fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `run_id` | string (uuid) | yes | Globally unique run identifier. |
| `condition` | enum | yes | One of: `baseline`, `static-200`, `random-200`, `adaptive-200`, `BM25-200`, `oracle-minimal`, `oracle-200`, `mismatched-200`, `sweep_*`. |
| `context_hash` | hex(sha256) | yes | Hash of the exact 200-term context JSON sent (order-stable serialization). |
| `glossary_build_id` | string | yes | Frozen glossary version (must include real/fictional counts). |
| `replicate_index` | int (1-based) | yes | Index within replication group (1..R). For variance subset, use dedicated group id. |
| `replication_group` | string | yes | Groups equal-replicate contrasts (e.g. `primary_contrast_set_1`). |
| `model` | string | yes | Gnani model identifier (exact string used). |
| `format` | string | yes | Response format (e.g. `json`, exact value). |
| `api_version` | string | yes | Batch API version used. |
| `timestamp_start`/`timestamp_end` | ISO8601 UTC | yes | Submission and completion timestamps. |
| `files_total` | int | yes | 100 (or subset size). |
| `files_returned` | int | yes | Count returned by API (must equal files_total or logged with reason). |
| `job_ids` | string[] | yes | Batch job IDs for traceability. |
| `cache_bypass` | bool | yes | true if cache bypassed for planned replicate/measurement. |
| `cache_hit_rate_run` | float | yes | Fraction of files served from cache in this run (0 if bypassed). |
| `measurement_run` | bool | yes | true for variance-estimation repeats (excluded from cache reuse). |
| `stratification_key` | string | if subset | For variance subset, which stratum (borderline/OOV/confusable/clean). |
| `audio_set_hash` | hex(sha256) | yes | Hash of the 100-file list (order-stable). |
| `notes` | string | optional | Anomalies (failures/retries). | 

**Enforcement:** All fields logged before analysis; `cache_bypass` must be true for any run contributing to run-variance estimation. Contrast rows with unequal `R` across paired conditions must be rejected from confirmatory analysis.