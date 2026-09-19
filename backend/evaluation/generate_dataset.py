"""
MoneyTrace Fraud Classification Benchmark v1 Generator.
Generates 2,000 synthetic transaction and incident records with:
- 21 Numerical features (amounts, hours, velocity, risk scores)
- 10 Binary/Boolean features (device, location, OTP, links)
- 7 Categorical features (channel, device_type, auth_method, etc.)
- 1 Text feature (incident_narrative)
- 1 Ground truth target: fraud_class (7 distinct classes)

CRITICAL DESIGN PRINCIPLES:
1. Synthetic & Defensible: 100% synthetic, zero real customer PII.
2. Deterministic & Reproducible: Fixed random seed (42).
3. Anti-Leakage: No trivial keyword-to-class 1:1 mappings. Features have realistic
   overlap across classes (e.g. legitimate users sometimes have high transaction amounts
   or travel to new locations; phishing and UPI fraud share channels).
4. Realistic Class Distribution: Mimics a real-world financial fraud intake triage:
   - LEGITIMATE: 400 (20.0%)
   - UPI_FRAUD: 360 (18.0%)
   - PHISHING: 320 (16.0%)
   - IMPERSONATION: 280 (14.0%)
   - INVESTMENT_FRAUD: 260 (13.0%)
   - ACCOUNT_TAKEOVER: 220 (11.0%)
   - WRONG_TRANSFER: 160 (8.0%)
   Total: 2,000 records.
"""

import os
import json
import random
import hashlib
from datetime import datetime
import pandas as pd

RANDOM_SEED = 42
TARGET_SIZE = 2000

CLASSES_DISTRIBUTION = {
    "LEGITIMATE": 400,
    "UPI_FRAUD": 360,
    "PHISHING": 320,
    "IMPERSONATION": 280,
    "INVESTMENT_FRAUD": 260,
    "ACCOUNT_TAKEOVER": 220,
    "WRONG_TRANSFER": 160,
}

CHANNELS = ["UPI_APP", "NET_BANKING", "MOBILE_BANKING", "PAYMENT_GATEWAY", "POS", "ATM"]
DEVICE_TYPES = ["ANDROID_MOBILE", "IOS_MOBILE", "WINDOWS_DESKTOP", "MAC_DESKTOP", "TABLET"]
AUTH_METHODS = ["BIOMETRIC_FINGERPRINT", "MPIN", "SMS_OTP", "EMAIL_OTP", "PASSWORD_OTP", "HARDWARE_TOKEN"]
BENEFICIARY_TYPES = ["INDIVIDUAL_P2P", "MERCHANT_P2M", "UTILITY_BILLER", "UNKNOWN_THIRD_PARTY", "NEW_UNVERIFIED_VPA"]
PAYMENT_METHODS = ["UPI_COLLECT", "UPI_INTENT", "IMPS", "NEFT", "RTGS", "DEBIT_CARD"]
REGIONS = ["NORTH_INDIA", "WEST_INDIA", "SOUTH_INDIA", "EAST_INDIA", "CENTRAL_INDIA", "INTERNATIONAL_IP"]
ACCOUNT_TYPES = ["SAVINGS", "CURRENT", "SALARY", "DIGITAL_WALLET"]

# Diverse realistic narrative templates with variable details (avoiding trivial static keywords)
NARRATIVE_TEMPLATES = {
    "LEGITIMATE": [
        "Transferred funds for monthly home rent to landlord as usual, but the status shows pending on my screen.",
        "Purchased an electronic gadget from an e-commerce festival sale. Payment deducted twice from savings account.",
        "Sent money to college fee portal via net banking. Awaiting confirmation receipt from the university finance desk.",
        "Monthly grocery payment made at supermarket POS terminal. Balance was deducted but merchant terminal timed out.",
        "Routine medical insurance premium payment made online; bank notification received immediately.",
        "Transferred funds to a family member for festive shopping expenses through standard UPI app interface.",
        "Scheduled bill payment for electricity and broadband utilities deducted successfully from salary account.",
        "Tried paying for flight ticket booking during promotion. Amount debited but airline PNR not generated yet."
    ],
    "UPI_FRAUD": [
        "Received a request claiming to be from a prospective buyer on an online marketplace asking me to approve a collect request to receive advance payment.",
        "Scanned a QR code received over chat believing it was to receive cash prize reward, but ₹{amt} was deducted instantly.",
        "Got an urgent call from someone claiming payment failed for a courier package; was told to approve ₹5 token collect request which took full balance.",
        "Someone posing as a restaurant refund agent sent a collect link on my messaging app saying money will be returned.",
        "A buyer on classifieds app insisted on paying via dynamic QR code and instructed me to enter my UPI MPIN to claim funds.",
        "Tried claiming cashback banner on a third-party coupon site which opened UPI app with pre-filled debit collect request.",
        "Contacted fake helpline found on social media for utility bill delay; executive sent a collect request stating it is verification."
    ],
    "PHISHING": [
        "Received an SMS stating electricity supply would be disconnected tonight unless I updated bill details at a shortened link.",
        "Clicked a notification link warning my SIM card will be deactivated within 24 hours due to pending identity verification.",
        "Opened an email warning my tax refund was pending. Entered my net banking credentials and OTP on the portal.",
        "SMS claiming my pan card was not linked with bank account provided a portal link where I submitted personal banking details.",
        "Received an alert about suspicious login attempt on net banking with a link to verify identity; entered card numbers and pin.",
        "Clicked on a sponsored search ad claiming to be customer service portal for credit card point redemption.",
        "Got an urgent text message indicating reward points worth ₹{amt} were expiring today and prompted to claim through secure portal."
    ],
    "IMPERSONATION": [
        "Caller claiming to be senior officer from telecom regulatory authority stated my phone number is linked to illegal advertising.",
        "Received video call from someone in police uniform claiming a parcel containing contraband was seized at customs in my name.",
        "Person claiming to be bank fraud prevention executive called saying unauthorized debit occurred and asked to confirm security code.",
        "Caller stated they were from credit card department offering zero interest rate conversion; asked to verify identity details.",
        "Received message from my manager's photo profile on WhatsApp requesting urgent gift voucher transfers for client meeting.",
        "Individual claiming to be income tax commissioner called demanding immediate penalty settlement to avoid bank account freeze.",
        "Person posing as an old school friend contacted on messaging app asking for immediate financial assistance for medical emergency."
    ],
    "INVESTMENT_FRAUD": [
        "Added to a private messaging investment channel promising 200% returns in 7 days through algorithmic crypto arbitrage trading.",
        "Saw social media influencer advertisement about high-yield pre-IPO stock allotment group. Transferred initial margin money.",
        "Offered a part-time remote job involving rating hotels and liking videos; required to deposit increasing funds to unlock commissions.",
        "Promised daily guaranteed 5% return on custom trading terminal app provided via direct APK file download.",
        "Investment advisor in VIP trading group recommended exclusive institutional equity allocation requiring transfer to partner accounts.",
        "Joined forex trading pool after viewing profit screenshots. Platform showed huge balance but blocked withdrawals demanding tax fees.",
        "Friend recommended high return automated trading bot requiring deposits into escrow UPI handle."
    ],
    "ACCOUNT_TAKEOVER": [
        "Suddenly lost cellular mobile network connectivity; discovered later an unauthorized duplicate e-SIM swap had been executed.",
        "Received repeated OTP requests while asleep; woke up to find net banking password reset and beneficiary added without consent.",
        "Installed a screen sharing remote support app recommended by someone claiming to fix device performance issues.",
        "Noticed strange login notification from an IP in another state followed by multiple unauthorized IMPS transfers.",
        "Email account was compromised and password reset emails for banking apps were triggered during midnight hours.",
        "Attacked by malware that intercepted SMS notifications and initiated transfers from my mobile banking app.",
        "Found secondary authentication device added to my digital wallet without authorization after visiting unverified website."
    ],
    "WRONG_TRANSFER": [
        "Mistyped one digit of recipient mobile phone number while sending money via UPI to my brother.",
        "Accidentally selected the wrong saved beneficiary with a similar name from my banking contact list.",
        "Entered wrong bank IFSC code and account number while doing an IMPS transfer for medical equipment.",
        "Sent funds to previous landlord's old UPI ID instead of current landlord by mistake from transaction history.",
        "Mistakenly entered extra zero in the amount field and sent to correct party but cannot get the excess returned.",
        "Transferred tuition fee to another student's virtual payment address due to typo in student ID roll number.",
        "Accidentally transferred vendor payment to an inactive supplier account that was closed last year."
    ]
}


def generate_benchmark_record(record_id: int, fraud_class: str, rng: random.Random) -> dict:
    """Generates a single realistic benchmark record with multi-signal complexity."""
    
    # 1. Base amounts and patterns according to class with realistic overlapping
    if fraud_class == "LEGITIMATE":
        amount = round(rng.choice([
            rng.uniform(150, 2500),
            rng.uniform(2500, 15000),
            rng.uniform(15000, 45000)
        ]), 2)
        tx_hour = rng.randint(7, 23)
        account_age = rng.randint(180, 2500)
        avg_amt = amount * rng.uniform(0.7, 1.4)
        amt_dev = round(amount / max(avg_amt, 1.0), 2)
        tx_24h = rng.randint(1, 8)
        tx_7d = tx_24h + rng.randint(4, 30)
        tx_1h = rng.randint(0, 2)
        ben_age = rng.randint(30, 800)
        ben_tx_count = rng.randint(3, 45)
        failed_otp = 0 if rng.random() > 0.1 else 1
        failed_login = 0 if rng.random() > 0.08 else 1
        dev_age = rng.randint(60, 1200)
        geo_dist = round(rng.uniform(0.1, 15.0), 1)
        prev_fraud = 0
        prev_cb = 0
        new_dev = rng.random() < 0.05
        new_ben = rng.random() < 0.15
        unusual_loc = rng.random() < 0.04
        otp_req = True
        otp_shared = False
        kyc_changed = False
        pwd_changed = rng.random() < 0.03
        multi_failed = False
        suspicious_link = False
        remote_access = False
        acct_risk = round(rng.uniform(0.02, 0.20), 2)
        dev_risk = round(rng.uniform(0.01, 0.15), 2)
        ip_risk = round(rng.uniform(0.01, 0.18), 2)
        vel_score = round(rng.uniform(0.05, 0.30), 2)
        ben_risk = round(rng.uniform(0.01, 0.15), 2)
        channel = rng.choice(["UPI_APP", "UPI_APP", "NET_BANKING", "MOBILE_BANKING", "POS"])
        auth_method = rng.choice(["BIOMETRIC_FINGERPRINT", "MPIN", "SMS_OTP"])
        ben_type = rng.choice(["INDIVIDUAL_P2P", "MERCHANT_P2M", "UTILITY_BILLER"])
        pay_method = rng.choice(["UPI_INTENT", "IMPS", "NEFT", "DEBIT_CARD"])

    elif fraud_class == "UPI_FRAUD":
        amount = round(rng.choice([
            rng.uniform(1500, 10000),
            rng.uniform(10000, 49000),
            rng.uniform(49000, 100000)
        ]), 2)
        tx_hour = rng.randint(8, 22)
        account_age = rng.randint(90, 1500)
        avg_amt = amount * rng.uniform(0.2, 0.6)
        amt_dev = round(amount / max(avg_amt, 1.0), 2)
        tx_24h = rng.randint(2, 10)
        tx_7d = tx_24h + rng.randint(5, 25)
        tx_1h = rng.randint(1, 4)
        ben_age = rng.randint(0, 14)
        ben_tx_count = rng.choice([0, 1])
        failed_otp = 0
        failed_login = 0
        dev_age = rng.randint(30, 800)
        geo_dist = round(rng.uniform(1.0, 30.0), 1)
        prev_fraud = 0 if rng.random() > 0.15 else 1
        prev_cb = 0
        new_dev = False
        new_ben = True
        unusual_loc = rng.random() < 0.10
        otp_req = rng.random() < 0.4
        otp_shared = False
        kyc_changed = False
        pwd_changed = False
        multi_failed = False
        suspicious_link = rng.random() < 0.65
        remote_access = False
        acct_risk = round(rng.uniform(0.20, 0.55), 2)
        dev_risk = round(rng.uniform(0.10, 0.35), 2)
        ip_risk = round(rng.uniform(0.20, 0.50), 2)
        vel_score = round(rng.uniform(0.35, 0.70), 2)
        ben_risk = round(rng.uniform(0.70, 0.98), 2)
        channel = "UPI_APP"
        auth_method = "MPIN"
        ben_type = rng.choice(["NEW_UNVERIFIED_VPA", "UNKNOWN_THIRD_PARTY"])
        pay_method = rng.choice(["UPI_COLLECT", "UPI_INTENT"])

    elif fraud_class == "PHISHING":
        amount = round(rng.choice([
            rng.uniform(5000, 25000),
            rng.uniform(25000, 75000),
            rng.uniform(75000, 190000)
        ]), 2)
        tx_hour = rng.randint(9, 21)
        account_age = rng.randint(120, 2000)
        avg_amt = amount * rng.uniform(0.15, 0.45)
        amt_dev = round(amount / max(avg_amt, 1.0), 2)
        tx_24h = rng.randint(3, 12)
        tx_7d = tx_24h + rng.randint(5, 20)
        tx_1h = rng.randint(2, 5)
        ben_age = rng.randint(0, 5)
        ben_tx_count = 0
        failed_otp = rng.randint(1, 4)
        failed_login = rng.randint(1, 3)
        dev_age = rng.randint(1, 60)
        geo_dist = round(rng.uniform(20.0, 450.0), 1)
        prev_fraud = 0 if rng.random() > 0.2 else 1
        prev_cb = 0
        new_dev = rng.random() < 0.55
        new_ben = True
        unusual_loc = rng.random() < 0.60
        otp_req = True
        otp_shared = True
        kyc_changed = rng.random() < 0.75
        pwd_changed = rng.random() < 0.40
        multi_failed = failed_login > 1
        suspicious_link = True
        remote_access = rng.random() < 0.25
        acct_risk = round(rng.uniform(0.55, 0.90), 2)
        dev_risk = round(rng.uniform(0.50, 0.88), 2)
        ip_risk = round(rng.uniform(0.60, 0.95), 2)
        vel_score = round(rng.uniform(0.60, 0.92), 2)
        ben_risk = round(rng.uniform(0.75, 0.99), 2)
        channel = rng.choice(["NET_BANKING", "PAYMENT_GATEWAY", "UPI_APP"])
        auth_method = rng.choice(["SMS_OTP", "PASSWORD_OTP"])
        ben_type = "UNKNOWN_THIRD_PARTY"
        pay_method = rng.choice(["IMPS", "NEFT", "UPI_INTENT"])

    elif fraud_class == "IMPERSONATION":
        amount = round(rng.choice([
            rng.uniform(10000, 50000),
            rng.uniform(50000, 200000),
            rng.uniform(200000, 600000)
        ]), 2)
        tx_hour = rng.randint(10, 19)
        account_age = rng.randint(300, 3000)
        avg_amt = amount * rng.uniform(0.1, 0.3)
        amt_dev = round(amount / max(avg_amt, 1.0), 2)
        tx_24h = rng.randint(1, 6)
        tx_7d = tx_24h + rng.randint(2, 15)
        tx_1h = rng.randint(1, 3)
        ben_age = rng.randint(0, 3)
        ben_tx_count = 0
        failed_otp = 0
        failed_login = 0
        dev_age = rng.randint(90, 1200)
        geo_dist = round(rng.uniform(0.5, 25.0), 1)
        prev_fraud = 0
        prev_cb = 0
        new_dev = False
        new_ben = True
        unusual_loc = False
        otp_req = True
        otp_shared = rng.random() < 0.30
        kyc_changed = False
        pwd_changed = False
        multi_failed = False
        suspicious_link = rng.random() < 0.20
        remote_access = rng.random() < 0.35
        acct_risk = round(rng.uniform(0.40, 0.80), 2)
        dev_risk = round(rng.uniform(0.10, 0.40), 2)
        ip_risk = round(rng.uniform(0.20, 0.60), 2)
        vel_score = round(rng.uniform(0.50, 0.85), 2)
        ben_risk = round(rng.uniform(0.70, 0.95), 2)
        channel = rng.choice(["NET_BANKING", "MOBILE_BANKING", "UPI_APP"])
        auth_method = rng.choice(["MPIN", "SMS_OTP", "BIOMETRIC_FINGERPRINT"])
        ben_type = rng.choice(["UNKNOWN_THIRD_PARTY", "NEW_UNVERIFIED_VPA"])
        pay_method = rng.choice(["RTGS", "IMPS", "NEFT"])

    elif fraud_class == "INVESTMENT_FRAUD":
        amount = round(rng.choice([
            rng.uniform(15000, 75000),
            rng.uniform(75000, 300000),
            rng.uniform(300000, 1000000)
        ]), 2)
        tx_hour = rng.randint(9, 23)
        account_age = rng.randint(180, 2200)
        avg_amt = amount * rng.uniform(0.15, 0.5)
        amt_dev = round(amount / max(avg_amt, 1.0), 2)
        tx_24h = rng.randint(2, 8)
        tx_7d = tx_24h + rng.randint(4, 20)
        tx_1h = rng.randint(1, 3)
        ben_age = rng.randint(1, 15)
        ben_tx_count = rng.randint(1, 3)
        failed_otp = 0
        failed_login = 0
        dev_age = rng.randint(100, 1000)
        geo_dist = round(rng.uniform(0.5, 35.0), 1)
        prev_fraud = 0
        prev_cb = 0
        new_dev = False
        new_ben = rng.random() < 0.80
        unusual_loc = False
        otp_req = True
        otp_shared = False
        kyc_changed = False
        pwd_changed = False
        multi_failed = False
        suspicious_link = rng.random() < 0.50
        remote_access = False
        acct_risk = round(rng.uniform(0.35, 0.75), 2)
        dev_risk = round(rng.uniform(0.15, 0.45), 2)
        ip_risk = round(rng.uniform(0.25, 0.65), 2)
        vel_score = round(rng.uniform(0.55, 0.90), 2)
        ben_risk = round(rng.uniform(0.65, 0.95), 2)
        channel = rng.choice(["UPI_APP", "NET_BANKING"])
        auth_method = rng.choice(["MPIN", "SMS_OTP"])
        ben_type = rng.choice(["UNKNOWN_THIRD_PARTY", "NEW_UNVERIFIED_VPA"])
        pay_method = rng.choice(["IMPS", "NEFT", "UPI_INTENT"])

    elif fraud_class == "ACCOUNT_TAKEOVER":
        amount = round(rng.choice([
            rng.uniform(20000, 80000),
            rng.uniform(80000, 250000),
            rng.uniform(250000, 750000)
        ]), 2)
        tx_hour = rng.choice([rng.randint(0, 6), rng.randint(22, 23)])
        account_age = rng.randint(365, 3000)
        avg_amt = amount * rng.uniform(0.08, 0.25)
        amt_dev = round(amount / max(avg_amt, 1.0), 2)
        tx_24h = rng.randint(5, 20)
        tx_7d = tx_24h + rng.randint(10, 40)
        tx_1h = rng.randint(3, 8)
        ben_age = 0
        ben_tx_count = 0
        failed_otp = rng.randint(2, 6)
        failed_login = rng.randint(2, 7)
        dev_age = rng.randint(0, 3)
        geo_dist = round(rng.uniform(150.0, 1200.0), 1)
        prev_fraud = 0 if rng.random() > 0.25 else 1
        prev_cb = 0 if rng.random() > 0.20 else 1
        new_dev = True
        new_ben = True
        unusual_loc = True
        otp_req = True
        otp_shared = rng.random() < 0.60
        kyc_changed = rng.random() < 0.50
        pwd_changed = True
        multi_failed = True
        suspicious_link = rng.random() < 0.40
        remote_access = rng.random() < 0.55
        acct_risk = round(rng.uniform(0.70, 0.98), 2)
        dev_risk = round(rng.uniform(0.75, 0.99), 2)
        ip_risk = round(rng.uniform(0.80, 0.99), 2)
        vel_score = round(rng.uniform(0.80, 0.99), 2)
        ben_risk = round(rng.uniform(0.80, 0.99), 2)
        channel = rng.choice(["NET_BANKING", "MOBILE_BANKING"])
        auth_method = rng.choice(["PASSWORD_OTP", "SMS_OTP"])
        ben_type = "UNKNOWN_THIRD_PARTY"
        pay_method = rng.choice(["IMPS", "RTGS"])

    elif fraud_class == "WRONG_TRANSFER":
        amount = round(rng.choice([
            rng.uniform(500, 5000),
            rng.uniform(5000, 25000),
            rng.uniform(25000, 60000)
        ]), 2)
        tx_hour = rng.randint(8, 22)
        account_age = rng.randint(180, 2000)
        avg_amt = amount * rng.uniform(0.6, 1.3)
        amt_dev = round(amount / max(avg_amt, 1.0), 2)
        tx_24h = rng.randint(1, 5)
        tx_7d = tx_24h + rng.randint(3, 20)
        tx_1h = rng.randint(1, 2)
        ben_age = rng.choice([0, rng.randint(60, 400)])
        ben_tx_count = rng.choice([0, 1])
        failed_otp = 0
        failed_login = 0
        dev_age = rng.randint(60, 900)
        geo_dist = round(rng.uniform(0.1, 10.0), 1)
        prev_fraud = 0
        prev_cb = 0
        new_dev = False
        new_ben = rng.random() < 0.70
        unusual_loc = False
        otp_req = True
        otp_shared = False
        kyc_changed = False
        pwd_changed = False
        multi_failed = False
        suspicious_link = False
        remote_access = False
        acct_risk = round(rng.uniform(0.05, 0.25), 2)
        dev_risk = round(rng.uniform(0.02, 0.20), 2)
        ip_risk = round(rng.uniform(0.02, 0.20), 2)
        vel_score = round(rng.uniform(0.10, 0.35), 2)
        ben_risk = round(rng.uniform(0.05, 0.30), 2)
        channel = rng.choice(["UPI_APP", "MOBILE_BANKING", "NET_BANKING"])
        auth_method = rng.choice(["MPIN", "BIOMETRIC_FINGERPRINT", "SMS_OTP"])
        ben_type = rng.choice(["INDIVIDUAL_P2P", "NEW_UNVERIFIED_VPA"])
        pay_method = rng.choice(["UPI_INTENT", "IMPS"])

    else:
        raise ValueError(f"Unknown class: {fraud_class}")

    # Realistic borderline edge cases (producing real-world false positives and false negatives)
    if fraud_class == "LEGITIMATE" and rng.random() < 0.14:
        # Realistic false positive: User traveling or purchasing emergency equipment with a new device / payment method
        ben_risk = round(rng.uniform(0.72, 0.88), 2)
        acct_risk = round(rng.uniform(0.55, 0.75), 2)
        dev_risk = round(rng.uniform(0.60, 0.82), 2)
        vel_score = round(rng.uniform(0.60, 0.82), 2)
        new_dev = True
        unusual_loc = True
        ben_type = "NEW_UNVERIFIED_VPA"
        pay_method = "UPI_COLLECT"
        narrative = rng.choice([
            "Urgent payment sent to a new local vendor while traveling out of state, but transaction failed.",
            "Paid a new unverified merchant for emergency repair supplies from a borrowed smartphone.",
            "Transferred money urgently to an unlisted contact during an emergency trip."
        ])
    elif fraud_class in ["UPI_FRAUD", "PHISHING", "IMPERSONATION", "INVESTMENT_FRAUD", "ACCOUNT_TAKEOVER"] and rng.random() < 0.058:
        # Realistic false negative: Sophisticated stealth scammer using aged mule account with clean telemetry
        ben_risk = round(rng.uniform(0.08, 0.20), 2)
        acct_risk = round(rng.uniform(0.05, 0.18), 2)
        dev_risk = round(rng.uniform(0.05, 0.15), 2)
        ip_risk = round(rng.uniform(0.05, 0.15), 2)
        vel_score = round(rng.uniform(0.05, 0.22), 2)
        unusual_loc = False
        new_dev = False
        new_ben = False
        suspicious_link = False
        remote_access = False
        otp_shared = False
        pwd_changed = False
        kyc_changed = False
        ben_type = "MERCHANT_P2M"
        pay_method = "IMPS"
        channel = "MOBILE_BANKING"
        narrative = rng.choice([
            "Paid regular subscription fee but vendor claimed non-receipt of payment.",
            "Sent usual monthly maintenance fund through regular banking application.",
            "Routine utility transfer debited but service provider has not updated bill."
        ])
    else:
        # Build narrative with realistic variation
        template = rng.choice(NARRATIVE_TEMPLATES[fraud_class])
        narrative = template.replace("{amt}", f"{amount:,.2f}")

    record = {
        "case_id": f"BENCH_{record_id:05d}",
        # Target (Ground Truth)
        "fraud_class": fraud_class,
        "is_fraud": fraud_class not in ["LEGITIMATE", "WRONG_TRANSFER"],
        # A. Numerical Features
        "transaction_amount": amount,
        "transaction_hour": tx_hour,
        "account_age_days": account_age,
        "transactions_last_24h": tx_24h,
        "transactions_last_7d": tx_7d,
        "transactions_last_1h": tx_1h,
        "average_transaction_amount": round(avg_amt, 2),
        "amount_deviation_ratio": amt_dev,
        "beneficiary_age_days": ben_age,
        "beneficiary_transaction_count": ben_tx_count,
        "failed_otp_attempts": failed_otp,
        "failed_login_attempts": failed_login,
        "device_age_days": dev_age,
        "geo_distance_from_usual_location_km": geo_dist,
        "previous_fraud_reports": prev_fraud,
        "previous_chargebacks": prev_cb,
        "account_risk_score": acct_risk,
        "device_risk_score": dev_risk,
        "ip_risk_score": ip_risk,
        "velocity_score": vel_score,
        "beneficiary_risk_score": ben_risk,
        # B. Boolean Features
        "new_device": new_dev,
        "new_beneficiary": new_ben,
        "unusual_location": unusual_loc,
        "otp_requested": otp_req,
        "otp_shared": otp_shared,
        "kyc_recently_changed": kyc_changed,
        "password_recently_changed": pwd_changed,
        "multiple_failed_logins": multi_failed,
        "suspicious_link_clicked": suspicious_link,
        "remote_access_detected": remote_access,
        # C. Categorical Features
        "transaction_channel": channel,
        "device_type": rng.choice(DEVICE_TYPES),
        "authentication_method": auth_method,
        "beneficiary_type": ben_type,
        "payment_method": pay_method,
        "geographic_region": rng.choice(REGIONS),
        "account_type": rng.choice(ACCOUNT_TYPES),
        # D. Text Features
        "incident_narrative": narrative
    }
    return record


def generate_dataset():
    """Builds the 2,000-record dataset, splits into 80/20 train/test, and exports CSV, JSON, XLSX."""
    rng = random.Random(RANDOM_SEED)
    records = []
    curr_id = 1001

    # Generate according to strict distribution
    for cls_name, count in CLASSES_DISTRIBUTION.items():
        for _ in range(count):
            rec = generate_benchmark_record(curr_id, cls_name, rng)
            records.append(rec)
            curr_id += 1

    # Shuffle deterministically to prevent ordering bias
    rng.shuffle(records)

    # 80/20 Split
    total = len(records)
    train_size = int(total * 0.8)  # 1600
    test_size = total - train_size  # 400

    for i, r in enumerate(records):
        r["split"] = "train" if i < train_size else "test"

    df = pd.DataFrame(records)

    # Save to backend/evaluation/
    out_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(out_dir, "dataset_v1.csv")
    json_path = os.path.join(out_dir, "dataset_v1.json")
    xlsx_path = os.path.join(out_dir, "dataset_v1.xlsx")

    df.to_csv(csv_path, index=False)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    df.to_excel(xlsx_path, index=False)

    # Calculate SHA-256 hash of canonical CSV
    hasher = hashlib.sha256()
    with open(csv_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    sha256_hash = hasher.hexdigest()

    # Manifest metadata
    manifest = {
        "dataset_name": "MoneyTrace Fraud Classification Benchmark v1",
        "version": "1.0.0",
        "creation_timestamp": datetime.utcnow().isoformat() + "Z",
        "random_seed": RANDOM_SEED,
        "record_count": total,
        "train_count": train_size,
        "test_count": test_size,
        "class_distribution": CLASSES_DISTRIBUTION,
        "test_class_distribution": df[df["split"] == "test"]["fraud_class"].value_counts().to_dict(),
        "train_class_distribution": df[df["split"] == "train"]["fraud_class"].value_counts().to_dict(),
        "feature_count": len(df.columns) - 4,  # minus case_id, fraud_class, is_fraud, split
        "feature_list": [c for c in df.columns if c not in ["case_id", "fraud_class", "is_fraud", "split"]],
        "generation_script_name": "generate_dataset.py",
        "canonical_csv_sha256": sha256_hash,
        "synthetic": True,
        "real_customer_data": False
    }

    manifest_path = os.path.join(out_dir, "dataset_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("==================================================")
    print("MONEYTRACE BENCHMARK GENERATION COMPLETE")
    print(f"Total records: {total} (Train: {train_size}, Test: {test_size})")
    print(f"Classes: {list(CLASSES_DISTRIBUTION.keys())}")
    print(f"CSV SHA-256: {sha256_hash}")
    print(f"Output files in: {out_dir}")
    print("==================================================")
    return manifest


if __name__ == "__main__":
    generate_dataset()
