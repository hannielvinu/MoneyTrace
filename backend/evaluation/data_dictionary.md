# MoneyTrace Fraud Classification Benchmark v1 — Data Dictionary

**Dataset Version:** 1.0.0  
**Records:** 2,000 synthetic transaction/incident instances  
**Canonical File:** `dataset_v1.csv` (also available as `dataset_v1.json` and `dataset_v1.xlsx`)  
**SHA-256 Checksum:** `d974d2b8a7e7f159ceaa689ec66d4996390d7fda9db549ea49fbe8f2574a6541`  
**Customer PII:** None (100% synthetic, generated deterministically with seed 42)

---

## 1. Identifiers & Ground Truth (Hidden During Inference)

| Column Name | Data Type | Description | Hidden From Model? |
| :--- | :--- | :--- | :--- |
| `case_id` | String | Unique synthetic identifier (`BENCH_01001` to `BENCH_03000`). | No |
| `fraud_class` | Categorical (Target) | Canonical ground-truth classification. 7 classes: `LEGITIMATE`, `UPI_FRAUD`, `PHISHING`, `IMPERSONATION`, `INVESTMENT_FRAUD`, `ACCOUNT_TAKEOVER`, `WRONG_TRANSFER`. | **YES (Strictly Hidden)** |
| `is_fraud` | Boolean | Binary fraud indicator (`True` if malicious fraud, `False` for `LEGITIMATE` and `WRONG_TRANSFER`). | **YES (Strictly Hidden)** |
| `split` | Categorical | Dataset split partition (`train` = 1,600 / 80%, `test` = 400 / 20%). | **YES (Evaluation Split)** |

---

## 2. Numerical Features (21 Features)

| Feature Name | Type | Range / Units | Description |
| :--- | :--- | :--- | :--- |
| `transaction_amount` | Float | ₹150.00 – ₹1,000,000.00 | Value of the transaction under analysis. |
| `transaction_hour` | Integer | 0 – 23 | Hour of transaction initiation (24h local time). |
| `account_age_days` | Integer | 90 – 3000 days | Age of user account with the financial institution. |
| `transactions_last_24h` | Integer | 1 – 20 | Number of debit operations initiated in the previous 24 hours. |
| `transactions_last_7d` | Integer | 2 – 50 | Total debits executed in the trailing 7 days. |
| `transactions_last_1h` | Integer | 0 – 8 | Sudden velocity burst metric in the immediately preceding hour. |
| `average_transaction_amount`| Float | ₹100.00 – ₹150,000.00 | User's 90-day baseline historical average transaction amount. |
| `amount_deviation_ratio` | Float | 0.10 – 15.00 | Ratio of current transaction amount to historical baseline. |
| `beneficiary_age_days` | Integer | 0 – 800 days | Time elapsed since counterparty beneficiary was registered. |
| `beneficiary_transaction_count`| Integer| 0 – 50 | Historical successful transactions previously sent to this beneficiary. |
| `failed_otp_attempts` | Integer | 0 – 6 | Consecutive failed OTP entries recorded prior to transfer. |
| `failed_login_attempts` | Integer | 0 – 7 | Consecutive authentication failures on the session. |
| `device_age_days` | Integer | 0 – 1200 days | Days since this device fingerprint was first linked to account. |
| `geo_distance_from_usual_location_km` | Float | 0.1 – 1,200.0 km | Distance from user's primary geohash centroid. |
| `previous_fraud_reports` | Integer | 0 – 1 | Prior dispute or fraud claims filed on this account. |
| `previous_chargebacks` | Integer | 0 – 1 | Historical chargeback disputes initiated on this account. |
| `account_risk_score` | Float | 0.01 – 0.99 | Bank internal behavioral risk score (0=safe, 1=critical). |
| `device_risk_score` | Float | 0.01 – 0.99 | Device reputation risk score (jailbreak, emulator, rooted). |
| `ip_risk_score` | Float | 0.01 – 0.99 | Network reputation risk score (VPN, Tor, datacenter proxy). |
| `velocity_score` | Float | 0.05 – 0.99 | Time-decayed debit velocity acceleration score. |
| `beneficiary_risk_score` | Float | 0.01 – 0.99 | Counterparty reputation score derived from inter-bank intelligence. |

---

## 3. Binary / Boolean Features (10 Features)

| Feature Name | Type | Values | Description |
| :--- | :--- | :--- | :--- |
| `new_device` | Boolean | True / False | Transaction initiated from a hardware fingerprint unseen in 30 days. |
| `new_beneficiary` | Boolean | True / False | Counterparty VPA/account added within the last 24 hours. |
| `unusual_location` | Boolean | True / False | Geolocation IP deviates significantly from user's baseline. |
| `otp_requested` | Boolean | True / False | 2FA / OTP challenge was triggered for this transaction. |
| `otp_shared` | Boolean | True / False | Evidence from user narrative or device that OTP was relayed to third-party. |
| `kyc_recently_changed` | Boolean | True / False | Profile KYC or phone number was updated within the last 72 hours. |
| `password_recently_changed`| Boolean | True / False | Credential reset occurred immediately prior to transfer. |
| `multiple_failed_logins` | Boolean | True / False | More than 1 failed credential submission on current session. |
| `suspicious_link_clicked` | Boolean | True / False | Telemetry confirms user clicked a shortened/unverified URL. |
| `remote_access_detected` | Boolean | True / False | Active screen-sharing utility detected (AnyDesk, TeamViewer, RustDesk). |

---

## 4. Categorical Features (7 Features)

| Feature Name | Type | Allowed Values |
| :--- | :--- | :--- |
| `transaction_channel` | Categorical | `UPI_APP`, `NET_BANKING`, `MOBILE_BANKING`, `PAYMENT_GATEWAY`, `POS`, `ATM` |
| `device_type` | Categorical | `ANDROID_MOBILE`, `IOS_MOBILE`, `WINDOWS_DESKTOP`, `MAC_DESKTOP`, `TABLET` |
| `authentication_method` | Categorical | `BIOMETRIC_FINGERPRINT`, `MPIN`, `SMS_OTP`, `EMAIL_OTP`, `PASSWORD_OTP`, `HARDWARE_TOKEN` |
| `beneficiary_type` | Categorical | `INDIVIDUAL_P2P`, `MERCHANT_P2M`, `UTILITY_BILLER`, `UNKNOWN_THIRD_PARTY`, `NEW_UNVERIFIED_VPA` |
| `payment_method` | Categorical | `UPI_COLLECT`, `UPI_INTENT`, `IMPS`, `NEFT`, `RTGS`, `DEBIT_CARD` |
| `geographic_region` | Categorical | `NORTH_INDIA`, `WEST_INDIA`, `SOUTH_INDIA`, `EAST_INDIA`, `CENTRAL_INDIA`, `INTERNATIONAL_IP` |
| `account_type` | Categorical | `SAVINGS`, `CURRENT`, `SALARY`, `DIGITAL_WALLET` |

---

## 5. Text Features (1 Feature)

| Feature Name | Type | Description |
| :--- | :--- | :--- |
| `incident_narrative` | String | Natural language statement filed by victim describing what occurred, deceptive pretexts, and technical vectors. Synthesized with realistic variations across 8 template patterns per class without trivial 1:1 keyword leakage. |
