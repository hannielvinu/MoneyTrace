# MoneyTrace Evaluation Protocol & Mathematical Formulations

This document specifies the exact mathematical definitions and operational pipeline for the MoneyTrace Evaluation Engine.

## 1. Pipeline Execution Flow

```
+-------------------------------------------------------------------+
| Held-Out Test Set (400 cases) from dataset_v1.csv                 |
| Features: 21 Numerical + 10 Binary + 7 Categorical + 1 Narrative  |
| Target (fraud_class, is_fraud): STRIPPED OUT                      |
+-------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| MoneyTrace Classification Pipeline                                |
| Multi-Modal Fusion:                                               |
|  - Telemetry Feature Extraction & Behavioral Scoring              |
|  - Risk Velocity & Baseline Deviation Evaluation                  |
|  - Narrative Semantic Feature Analysis                            |
+-------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| Output Prediction: predicted_fraud_class                          |
+-------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| Ground-Truth Matching & Metric Engine                             |
| Multi-Class: Macro P, Macro R, Macro F1, Weighted F1, Confusion M.|
| Binary Fraud: Accuracy, Precision, Recall, F1, FPR, FNR           |
+-------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| Artifact Generation & Dashboard API                               |
| runs/<run_id>/results.json, predictions.json, metrics.json        |
+-------------------------------------------------------------------+
```

## 2. Mathematical Formulations

### Multi-Class Metrics (C = 7 classes)
Let $C = \{ c_1, c_2, \dots, c_7 \}$ denote the classes.
For each class $c$:
- $TP_c$: Cases where actual = $c$ and predicted = $c$.
- $FP_c$: Cases where actual $\neq c$ and predicted = $c$.
- $FN_c$: Cases where actual = $c$ and predicted $\neq c$.
- $Support_c$: Total ground truth cases where actual = $c$.

$$\text{Precision}_c = \frac{TP_c}{TP_c + FP_c}$$
$$\text{Recall}_c = \frac{TP_c}{TP_c + FN_c}$$
$$F1_c = \frac{2 \cdot \text{Precision}_c \cdot \text{Recall}_c}{\text{Precision}_c + \text{Recall}_c}$$

$$\text{Macro Precision} = \frac{1}{|C|} \sum_{c \in C} \text{Precision}_c$$
$$\text{Macro Recall} = \frac{1}{|C|} \sum_{c \in C} \text{Recall}_c$$
$$\text{Macro F1} = \frac{1}{|C|} \sum_{c \in C} F1_c$$
$$\text{Weighted F1} = \sum_{c \in C} \left( \frac{Support_c}{N} \cdot F1_c \right)$$

### Confusion Matrix
$M_{i,j}$ represents the count of records with ground-truth class $i$ that were predicted as class $j$.
$$\sum_{i,j} M_{i,j} = N_{\text{test}} = 400$$

### Binary Fraud Metrics
Derived mapping:
- Fraud ($Y=1$): `UPI_FRAUD`, `PHISHING`, `IMPERSONATION`, `INVESTMENT_FRAUD`, `ACCOUNT_TAKEOVER`.
- Non-Fraud ($Y=0$): `LEGITIMATE`, `WRONG_TRANSFER`.

$$\text{Accuracy}_{\text{bin}} = \frac{TP + TN}{TP + TN + FP + FN}$$
$$\text{Precision}_{\text{bin}} = \frac{TP}{TP + FP}$$
$$\text{Recall}_{\text{bin}} = \frac{TP}{TP + FN}$$
$$F1_{\text{bin}} = \frac{2 \cdot \text{Precision}_{\text{bin}} \cdot \text{Recall}_{\text{bin}}}{\text{Precision}_{\text{bin}} + \text{Recall}_{\text{bin}}}$$
$$\text{False Positive Rate (FPR)} = \frac{FP}{FP + TN}$$
$$\text{False Negative Rate (FNR)} = \frac{FN}{FN + TP}$$
