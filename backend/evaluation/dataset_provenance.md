# MoneyTrace Fraud Classification Benchmark v1 — Provenance & Evaluation Protocol

## 1. Executive Summary & Purpose
This benchmark was constructed to provide a **scientifically defensible, reproducible, and mathematically rigorous** answer to the hackathon question:
> *"How did you measure the accuracy of MoneyTrace?"*

MoneyTrace performs autonomous fraud intake, classification, and investigation. Evaluating real-world fraud models on live production banking data during a public hackathon is prohibited by banking privacy laws (RBI guidelines, DPDP Act 2023). Consequently, we designed the **MoneyTrace Fraud Classification Benchmark v1**, consisting of **2,000 synthetic transaction and incident records** with full multi-signal features and fixed ground-truth target labels.

---

## 2. Benchmark Architecture & Signal Composition
Every record in the benchmark integrates four signal modalities:
1. **Numerical Telemetry (21 features):** High-resolution transaction metrics, baseline deviations, multi-window velocities (1h, 24h, 7d), and 5 distinct domain risk scores (account, device, IP, velocity, counterparty).
2. **Boolean Behavioral Indicators (10 features):** Critical red-flag vectors including credential reset, newly linked devices, unverified VPAs, screen-sharing remote tools, and OTP sharing.
3. **Categorical Context (7 features):** Banking channels, payment rails (UPI Collect vs Intent, IMPS, RTGS), device hardware categories, and geographic zones.
4. **Natural Language Narrative (1 feature):** Victim incident statements capturing psychological pressure (urgency, fear, greed), deceptive pretexts, and technical vectors.

---

## 3. Ground Truth Classes & Distribution
The benchmark establishes 7 mutually exclusive target classes (`fraud_class`):

| Fraud Class | Count | % of Benchmark | Description | Binary Mapping |
| :--- | :--- | :--- | :--- | :--- |
| `LEGITIMATE` | 400 | 20.0% | Normal merchant/P2P transfers, pending statuses, legitimate disputes | `is_fraud = False` |
| `UPI_FRAUD` | 360 | 18.0% | Collect requests, malicious QR code scans, cashback scams | `is_fraud = True` |
| `PHISHING` | 320 | 16.0% | Fake KYC portals, expired utility bill SMS links, SIM swap alerts | `is_fraud = True` |
| `IMPERSONATION` | 280 | 14.0% | Police/CBI digital arrest, bank fraud helpline, regulatory coercion | `is_fraud = True` |
| `INVESTMENT_FRAUD`| 260 | 13.0% | High-yield Telegram/WhatsApp crypto, pre-IPO schemes, task scams | `is_fraud = True` |
| `ACCOUNT_TAKEOVER`| 220 | 11.0% | Credential compromise, unauthorized password resets, remote access | `is_fraud = True` |
| `WRONG_TRANSFER` | 160 | 8.0% | User typographical error in VPA/account, accidental wrong party | `is_fraud = False` |
| **Total** | **2,000**| **100.0%** | Comprehensive benchmark representation | 1,440 Fraud / 560 Non-Fraud |

---

## 4. Strict Anti-Leakage Methodology
To guarantee that high performance is not an artifact of data leakage:
1. **Ground-Truth Target Insulation:** The `fraud_class` and `is_fraud` fields are strictly withheld from the inference pipeline. The model only receives transaction context and incident narratives.
2. **Feature Overlap Across Classes:** Fraudulent and legitimate incidents share overlapping ranges for transaction amounts (₹150 to ₹45,000), transaction hours, payment methods (UPI, IMPS), and channels.
3. **No Keyword Triviality:** Narratives do not contain artificial 1:1 keyword shortcuts (e.g. UPI fraud narratives do not simply contain the phrase "UPI fraud"). Classification requires multi-signal reasoning combining behavioral telemetry, beneficiary risk, velocity, and narrative semantics.

---

## 5. Train / Test Partitioning
The dataset is partitioned deterministically using a fixed random seed (`42`):
- **Development/Reference Partition (80% / 1,600 cases):** Available for baseline feature calibration and reference distribution inspection.
- **Held-Out Test Set (20% / 400 cases):** A blind evaluation set used exclusively for computing out-of-sample benchmark metrics. The production pipeline evaluated on this partition operates zero-shot without post-hoc hyperparameter tuning.

---

## 6. Evaluation Protocol & Metric Definitions
Predictions are evaluated against ground truth using standard scikit-learn standard formulations:

### Multi-Class Metrics:
- **Accuracy:** $\frac{\sum \text{True Class Matches}}{N_{\text{test}}}$
- **Per-Class Precision:** $\frac{TP_c}{TP_c + FP_c}$
- **Per-Class Recall:** $\frac{TP_c}{TP_c + FN_c}$
- **Per-Class F1-Score:** $2 \cdot \frac{\text{Precision}_c \cdot \text{Recall}_c}{\text{Precision}_c + \text{Recall}_c}$
- **Macro F1:** Arithmetic mean of F1-scores across all 7 classes (unweighted by class size).
- **Weighted F1:** Support-weighted mean of F1-scores across all 7 classes.

### Binary Fraud Detection Metrics:
Derived by mapping $\{ \text{UPI\_FRAUD}, \text{PHISHING}, \text{IMPERSONATION}, \text{INVESTMENT\_FRAUD}, \text{ACCOUNT\_TAKEOVER} \} \to \text{Fraud}$ and $\{ \text{LEGITIMATE}, \text{WRONG\_TRANSFER} \} \to \text{Non-Fraud}$:
- **Binary Precision, Recall, F1:** Standard binary classification metrics for distinguishing fraudulent from non-fraudulent incidents.
- **False Positive Rate (FPR):** $\frac{FP}{FP + TN}$ (Fraction of legitimate/accidental transactions incorrectly flagged as malicious fraud).
- **False Negative Rate (FNR):** $\frac{FN}{FN + TP}$ (Fraction of malicious fraud incidents missed).

---

## 7. Component-Level Evaluation Transparency
- **MoneyTrace Classification Engine:** Evaluated directly on the 400 held-out test records.
- **Google Gemini Investigation Agent:** Evaluated on incident type classification, severity stratification, and red-flag extraction for incidents where corresponding ground-truth exists.
- **Sarvam AI (Speech-to-Text):** Marked as `Not measured in this benchmark — labelled audio/reference transcripts are not included.` (Avoiding fabricated speech metrics).
- **Cognee Cloud (Graph Syndicate Discovery):** Marked as `Not measured — relationship graph ground truth is not included in this benchmark.` (Avoiding fabricated graph retrieval metrics).

## 8. Reproducibility
The entire evaluation suite is reproducible using the following commands from the `backend/` directory:
```bash
# 1. Regenerate canonical benchmark dataset
python evaluation/generate_dataset.py

# 2. Run held-out evaluation and generate metrics artifacts
python evaluation/evaluator.py
```
Canonical Dataset SHA-256: `cdef60222fe47f2ff8569233ec8b02083d5844d5d42a4a1dfcc7de9f652cb6e9`
All outputs are saved as permanent, audit-ready JSON files in `backend/evaluation/runs/<run_id>/`.

