**1) FICTIONAL PRODUCT NAMES - MECHANICAL RULE SET**

**Constraints (MUST enforce):**
- **Zero prior:** Name must not exist in Indian fintech/UPI/BBPS/NPCI/IRDAI public registries, app stores, or common brand lists. Validate via substring search against known real names (PhonePe, Paytm, GPay/Google Pay, BHIM, Amazon Pay, Razorpay, Cashfree, BillDesk, CCAvenue, Mobikwik, Freecharge, ZestMoney, KredX, Jupiter, Fi, Slice, Niyo, Open, IndiaMART Pay, etc.). 
- **Plausible Indian fintech:** Blend Hindi/English elements common to Indian brands (e.g. "Sathi", "Dhan", "Nidhi", "Vyapaar", "Setu", "Udaan", "Khata", "Sewa", "Rupya", "Arth", "Kosh"). Prefer compound forms.
- **Phonetically distinct/transcribable:** 3-4 syllables max, avoid clusters hard for Hinglish ASR (e.g. avoid "xkz", three-consonant onsets), use common phonemes. Must be clearly enunciable.
- **No accidental collision:** Check for near-homophones of real brands/terms (e.g. avoid "PayThm" looking like Paytm). Reject if any alias would collide with existing glossary entries.
- **Slot cost:** Each is a single phrase slot (counts as 1 of 200). Treat as keyterm entries with canonical form + minimal aliases only if unambiguous.

**Examples (10):**
| Canonical (keyterm) | Aliases (frozen) | Rationale |
|---|---|---|
| `ArthSathi` | `Arth Sathi` | Blends "Arth" (finance) + "Sathi" (companion); uncommon compound, no hits against major brands. |
| `DhanSetu` | `Dhan Setu` | "Dhan" + "Setu" (bridge); plausible bridge-fintech, phonetically clean. |
| `VyapaarNidhi` | `Vyapaar Nidhi` | "Vyapaar" (business) + "Nidhi" (fund); sounds like NBFC-lite, distinct. |
| `KhataKosh` | `Khata Kosh` | "Khata" (account/book) + "Kosh" (fund/treasury); plausible SME tool, no obvious collision. |
| `SewaUdaan` | `Sewa Udaan` | "Sewa" (service) + "Udaan" (takeoff); service-enablement name, distinct syllables. |
| `RupyaSetu` | `Rupya Setu` | "Rupya" + "Setu"; clean, avoid writing as "RupyaPay" (too close to Paytm/PhonePe family). |
| `ArthVyom` | `Arth Vyom` | "Arth" + "Vyom" (sky/space); modern, uncommon, good phonetic separation. |
| `DhanSewa` | `Dhan Sewa` | "Dhan" + "Sewa"; simple, transcribable, no collision risk. |
| `NidhiArth` | `Nidhi Arth` | Reversed order variant avoided; use this form only if no real "Nidhiarth" exists; validate before use. |
| `KoshSathi` | `Kosh Sathi` | "Kosh" + "Sathi"; treasury-companion, distinct from existing terms. |


**2) CONFUSABLE-IN-ROLE PAIRS (SEPARABLE BY FROZEN EXACT-ALIAS MATCHER)**

These share the same call role but are acoustically distinct; matcher must keep them separate.

| Pair (A / B) | Shared role in call | Why acoustically distinct | Frozen matcher expectation |
|---|---|---|---|
| `NACH` / `e-mandate` | Mandate/auto-debit setup | Different syllable structure; "NACH" (/nach/) vs "e-mandate" (multi-syllabic with hyphen/tokenization); no shared phoneme sequence. | Exact canonical forms differ; aliases don't intersect. |
| `UPI ID` / `VPA` | Payment address identification | "UPI ID" is letter+word sequence; "VPA" is acronym pronounced as letters/word differently; stress patterns differ. | No canonicalisation merge; treated as different keyterms. |
| `IFSC` / `MICR` | Bank branch/routing identification | Both acronyms but different letter sequences and different usage context tokens; no phonetic conflation in Hinglish. | Distinct forms; no alias overlap. |
| `BBPS` / `Bharat BillPay` | Bill payment rail identification | Acronym vs full phrase; different lengths/stress; "Bharat BillPay" contains space tokens not in acronym. | Full phrase != acronym string; exact match only. |
| `IMPS` / `NEFT` | Funds transfer rail | Distinct acronym pairs; different articulation, no common syllabic frame. | No merge rule applies. |
| `EMI` / `equated monthly instalment` | Loan repayment term | Acronym vs full expanded form; different token counts; expansion not automatic unless aliased. | Only match if alias maps "equated monthly instalment" -> `EMI` (explicit). |
| `CIBIL` / `credit score` | Creditworthiness check | Proper name vs generic phrase; different phonology; "credit score" is two common words. | Distinct; no implicit merge. |
| `KYC` / `know your customer` | Identity verification | Acronym vs full phrase; different forms; only explicit alias connects them. | Only explicit alias `know your customer`->`KYC` prevents separation. |


**3) GRADED SET - ACOUSTICALLY CLOSE BUT STILL SEPARABLE BY EXACT MATCHING AFTER ALIAS CANONICALISATION**

These have a chance for false insertion but must remain separable with exact-after-alias-canonicalisation.

| Pair (A / B) | Exact spelling produced | Why close acoustically | Why matcher won't merge | False-insertion risk |
|---|---|---|---|---|
| `Paytm` / `Patym` | `Paytm`, `Patym` | Similar syllables (/peɪtm/ vs /pætɪm/); vowel/consonant blur in fast Hinglish. | Canonical forms differ by 'a' vs 'e'; no fuzzy/phonetic rule in frozen exact matcher; aliases only if explicitly listed. | Medium - possible if misread as typo, but exact match fails. |
| `PhonePe` / `PhonPe` | `PhonePe`, `PhonPe` | Share "Phon(e)Pe" frame; 'e' omission common in speech/writing. | "PhonePe" != "PhonPe" as strings; must add explicit alias `PhonPe`->`PhonePe` to merge (not automatic). | Medium - needs explicit alias or remains separate (correct for measuring false insertion). |
| `Mobikwik` / `Mobikwick` | `Mobikwik`, `Mobikwick` | 'kwik' vs 'kwick' similar; brand-ish ending. | Different endings; exact string inequality; no phonetic normalization in frozen matcher. | Medium - separator holds without alias. |
| `Razorpay` / `Razorpey` | `Razorpay`, `Razorpey` | 'ay' vs 'ey' similar in some accents. | Final token differs; canonical forms distinct; requires explicit alias to canonicalise. | Medium - false insertion observable only if ASR produces 'ey' form and no alias maps it. |


**4) OOV CONTROL - TERMS DELIBERATELY ABSENT FROM GLOSSARY**

- **Inclusion rule:** For each call, insert 1-2 spoken terms that are plausible in-domain (Indian fintech/banking/Hinglish) but **absent** from the 2000-term glossary. Examples: `UPI lite`, `credit limit increase`, `tokenised card` (if not present), or fictional-but-plausible phrases not in glossary. Do **not** add them as keyterms.
- **Utterance design:** Place in natural utterances (not isolated lists). Ensure they can be reasonably spoken and transcribed by ASR even if unrecognized.
- **Counting:** OOV utterances are counted separately from glossary terms. They do **not** contribute to "keyterm recall" numerator/denominator against the glossary; instead they form an **OOV coverage** track (how often ASR produces any tokens vs drops). A correct recognition of an OOV term counts as "produced" for OOV analysis but **0** for matched-vocabulary recall. This prevents recall inflation by construction.
- **Budget neutrality:** OOV terms do not consume the 200-term keyterm budget (budget is only for glossary terms applied via context). 


**5) ACCOUNTING - GLOSSARY COMPOSITION & RANDOM DRAWS**

- **Composition (target):** 2000-term glossary split as **~90% real / ~10% fictional** = **1800 real, 200 fictional** (fictional = names from §1, validated zero-prior). Exact counts must be logged per build; fictional count is fixed in the frozen glossary.
- **Interaction with 200-term budget:** The context provides only 200 slots per call (batch to all files in job). A **random-200** draw samples uniformly without regard to call content. With 1800 real / 200 fictional in 2000, expected real terms in random-200 ~ 180 (90%) but **mostly irrelevant to the specific call** (domain mismatch dominates). Fictional terms in random-200: expected ~10 (10% of draw) but again likely irrelevant unless by chance. 
- **Effect:** Relevance, not raw count, drives recoverability. "Matched-vocabulary benefit" requires the 200-term set to overlap the call's needed terms; random-200 gives low overlap → corruption/irrelevance dominates and recovers little. Oracle-minimal gives high overlap with minimal noise. Static core-200 trades coverage for consistency. This matches the claim: mismatch corrupts; cheap per-call selector (adaptive-200) recovers most of matched-vocabulary benefit without that corruption.  
- **Verification note:** Power (~70-75 effective occurrences, MDE ~20 points) means only large effects detectable; compositional split must be preserved and logged (fictional/real, in-budget/out-of-budget, OOV produced/dropped) to avoid inflation.