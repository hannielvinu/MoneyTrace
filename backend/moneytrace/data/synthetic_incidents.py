"""
Synthetic Dataset for MoneyTrace Demo & Testing.
Contains realistic Indian fraud incidents, repeated entities (phones, UPI VPAs, QR IDs, domains),
and pre-seeded scam clusters (Cluster A: Fake KYC, Cluster B: Fake Support QR, Cluster C: Digital Arrest, etc.).
"""

from typing import List, Dict, Any
from datetime import datetime, timedelta

# Known target accounts / entities for pre-seeded clusters
CLUSTER_A_ENTITIES = {
    "phone": "+91-98765-43210",
    "upi_vpa": "kyc-update.pay@ybl",
    "bank_account": "HDFC-009214481029",
    "domain": "secure-kyc-update.co.in",
    "scam_type": "Fake KYC",
}

CLUSTER_B_ENTITIES = {
    "phone": "+91-88123-99441",
    "upi_vpa": "care-refund.helpdesk@okhdfcbank",
    "qr_id": "QR_SUPPORT_8832",
    "domain": "paytm-refund-desk.in",
    "scam_type": "Fake Customer Support",
}

CLUSTER_C_ENTITIES = {
    "phone": "+91-77009-12845",
    "upi_vpa": "cbi-cybercell.verify@axis",
    "bank_account": "ICICI-88192004123",
    "domain": "cybercrime-clearance.gov-verify.info",
    "scam_type": "Digital Arrest",
}

CLUSTER_D_ENTITIES = {
    "phone": "+91-91234-56789",
    "upi_vpa": "fast-loan.approval@paytm",
    "domain": "instant-credit-loan.org",
    "scam_type": "Fake Loan",
}

CLUSTER_E_ENTITIES = {
    "phone": "+91-99887-76655",
    "upi_vpa": "global-invest.returns@icici",
    "domain": "quant-trading-india.top",
    "scam_type": "Investment Scam",
}

# The canonical primary demo transaction
DEMO_PRIMARY_TRANSACTION = {
    "transaction_id": "TXN784219",
    "amount": 18500,
    "currency": "INR",
    "sender": "Victim User (Ramesh Kumar)",
    "recipient": "kyc-update.pay@ybl",
    "recipient_phone": "+91-98765-43210",
    "recipient_bank": "Yes Bank (IFSC: YESB0000001)",
    "date": "18 Sep 2026, 14:22 IST",
    "status": "Completed",
    "scam_category": "Fake KYC",
    "note": "Immediate KYC verification charge reversal promised"
}

# Additional known demo transactions
DEMO_SECONDARY_TRANSACTIONS = [
    {
        "transaction_id": "TXN902311",
        "amount": 9450,
        "currency": "INR",
        "sender": "Pooja Sharma",
        "recipient": "care-refund.helpdesk@okhdfcbank",
        "recipient_phone": "+91-88123-99441",
        "recipient_bank": "HDFC Bank",
        "date": "18 Sep 2026, 11:15 IST",
        "status": "Completed",
        "scam_category": "Fake Customer Support",
        "note": "QR scan refund authorization"
    },
    {
        "transaction_id": "TXN441029",
        "amount": 54000,
        "currency": "INR",
        "sender": "Anil Deshmukh",
        "recipient": "cbi-cybercell.verify@axis",
        "recipient_phone": "+91-77009-12845",
        "recipient_bank": "Axis Bank",
        "date": "17 Sep 2026, 19:40 IST",
        "status": "Completed",
        "scam_category": "Digital Arrest",
        "note": "Supreme Court bail bond clearance fee"
    }
]


def generate_synthetic_dataset() -> Dict[str, Any]:
    """
    Generates ~125 synthetic incidents with realistic Indian fraud patterns,
    connected clusters, and shared entities.
    """
    now = datetime(2026, 9, 18, 20, 30, 0)
    incidents: List[Dict[str, Any]] = []
    transactions: List[Dict[str, Any]] = [DEMO_PRIMARY_TRANSACTION] + DEMO_SECONDARY_TRANSACTIONS
    
    # -------------------------------------------------------------
    # 1. CLUSTER A: Fake KYC Impersonation (7 Related Incidents to primary)
    # -------------------------------------------------------------
    kyc_victims = [
        ("MT-10481", "Sanjay Patel", 18500, "TXN784210", 35, "Received SMS saying SBI wallet KYC pending, caller asked to send test payment."),
        ("MT-10478", "Meena Iyer", 22000, "TXN784192", 120, "Call claiming Paytm wallet KYC blocked. Transferred money to update profile."),
        ("MT-10472", "Kavita Rao", 18500, "TXN784115", 280, "Caller stated SIM card and bank KYC expired. Asked for quick deposit to verify."),
        ("MT-10465", "Venkatesh S", 15000, "TXN784089", 420, "Urgent WhatsApp call regarding bank KYC expiry. Sent funds to the given VPA."),
        ("MT-10450", "Deepak Verma", 18500, "TXN783990", 610, "Fake executive asked to install quick support app and transfer KYC fee."),
        ("MT-10439", "Priyanka Sen", 25000, "TXN783844", 800, "Received SMS from VM-PAYTM regarding pending documentation. Lost 25k."),
        ("MT-10420", "Harish Nair", 18500, "TXN783610", 1100, "Caller impersonated bank officer regarding annual KYC update.")
    ]
    
    for inc_id, victim, amt, tx_id, minutes_ago, narrative in kyc_victims:
        t_time = (now - timedelta(minutes=minutes_ago)).strftime("%d %b %Y, %H:%M IST")
        incidents.append({
            "id": inc_id,
            "victim_name": victim,
            "victim_phone": f"+91-98{inc_id[-4:]}102",
            "amount": amt,
            "currency": "INR",
            "transaction_id": tx_id,
            "scam_type": "Fake KYC",
            "severity": "CRITICAL",
            "status": "ESCALATED",
            "narrative": narrative,
            "recipient_upi": CLUSTER_A_ENTITIES["upi_vpa"],
            "scammer_phone": CLUSTER_A_ENTITIES["phone"],
            "bank_account": CLUSTER_A_ENTITIES["bank_account"],
            "domain": CLUSTER_A_ENTITIES["domain"],
            "qr_id": None,
            "created_at": t_time,
            "shared_cluster": "Cluster A (Fake KYC Ring)",
            "red_flags": [
                "KYC-expiry impersonation",
                "Urgent payment deadline",
                "Known repeat fraud VPA",
                "Linked to 7 previous reports"
            ]
        })
        transactions.append({
            "transaction_id": tx_id,
            "amount": amt,
            "currency": "INR",
            "sender": victim,
            "recipient": CLUSTER_A_ENTITIES["upi_vpa"],
            "recipient_phone": CLUSTER_A_ENTITIES["phone"],
            "recipient_bank": "Yes Bank",
            "date": t_time,
            "status": "Completed",
            "scam_category": "Fake KYC",
            "note": "Mandatory KYC renewal fee"
        })

    # -------------------------------------------------------------
    # 2. CLUSTER B: Fake Customer Support / QR Refund (9 Incidents)
    # -------------------------------------------------------------
    qr_victims = [
        ("MT-10490", "Pooja Sharma", 9450, "TXN902311", 45, "Searched online customer care number for ticket refund. Asked to scan QR."),
        ("MT-10488", "Rahul Bajaj", 12000, "TXN902280", 90, "Scanned QR code sent via WhatsApp claiming to be merchant refund."),
        ("MT-10475", "Ankit Tiwari", 8500, "TXN902140", 180, "Customer care agent asked to receive cashback via reverse QR code."),
        ("MT-10461", "Sneha Joshi", 15000, "TXN901990", 300, "Executive claimed electricity bill double deduction refund via QR."),
        ("MT-10444", "Gopalakrishnan", 9450, "TXN901750", 490, "Flight booking cancellation refund. Executive sent payment request instead."),
        ("MT-10431", "Farhan Akhtar", 11200, "TXN901500", 680, "Couriers delivery address correction refund QR."),
        ("MT-10415", "Manoj Singh", 9450, "TXN901200", 920, "Food delivery refund requested, scanned QR and money deducted."),
        ("MT-10398", "Shreya Das", 14300, "TXN900900", 1200, "Shopping app dispute. Fake helpdesk sent reverse QR code."),
        ("MT-10380", "Kiran Hegde", 9450, "TXN900600", 1450, "Wallet recharge failed refund QR code scan.")
    ]
    for inc_id, victim, amt, tx_id, minutes_ago, narrative in qr_victims:
        t_time = (now - timedelta(minutes=minutes_ago)).strftime("%d %b %Y, %H:%M IST")
        incidents.append({
            "id": inc_id,
            "victim_name": victim,
            "victim_phone": f"+91-91{inc_id[-4:]}882",
            "amount": amt,
            "currency": "INR",
            "transaction_id": tx_id,
            "scam_type": "Fake Customer Support",
            "severity": "CRITICAL",
            "status": "ESCALATED",
            "narrative": narrative,
            "recipient_upi": CLUSTER_B_ENTITIES["upi_vpa"],
            "scammer_phone": CLUSTER_B_ENTITIES["phone"],
            "bank_account": None,
            "domain": CLUSTER_B_ENTITIES["domain"],
            "qr_id": CLUSTER_B_ENTITIES["qr_id"],
            "created_at": t_time,
            "shared_cluster": "Cluster B (Customer Support QR Ring)",
            "red_flags": [
                "Reverse QR code deceit",
                "Impersonating authorized support",
                "Shared QR template across 9 victims",
                "Domain registered 48 hours ago"
            ]
        })
        transactions.append({
            "transaction_id": tx_id,
            "amount": amt,
            "currency": "INR",
            "sender": victim,
            "recipient": CLUSTER_B_ENTITIES["upi_vpa"],
            "recipient_phone": CLUSTER_B_ENTITIES["phone"],
            "recipient_bank": "HDFC Bank",
            "date": t_time,
            "status": "Completed",
            "scam_category": "Fake Customer Support",
            "note": "Refund reversal request"
        })

    # -------------------------------------------------------------
    # 3. CLUSTER C: Digital Arrest / Law Enforcement Extortion (6 Incidents)
    # -------------------------------------------------------------
    digital_arrest_victims = [
        ("MT-10495", "Anil Deshmukh", 54000, "TXN441029", 50, "Skype video call by fake police officer stating parcel containing narcotics found."),
        ("MT-10485", "Sunita Nair", 98000, "TXN440950", 110, "Fake CBI officer showing forged warrant, demanded security clearance fund."),
        ("MT-10468", "Arun Bhattacharya", 125000, "TXN440810", 250, "Threatened with immediate arrest for money laundering unless funds verified."),
        ("MT-10440", "Rekha Pillai", 75000, "TXN440550", 520, "Video call with police station backdrop demanding bank account verification deposit."),
        ("MT-10410", "Devendra Chauhan", 150000, "TXN440200", 980, "Supreme Court affidavit forgery, transferred retirement savings to safe escrow."),
        ("MT-10375", "Geeta Kapoor", 82000, "TXN439800", 1600, "Customs officer call claiming illicit drugs seized at Mumbai airport under her Aadhaar.")
    ]
    for inc_id, victim, amt, tx_id, minutes_ago, narrative in digital_arrest_victims:
        t_time = (now - timedelta(minutes=minutes_ago)).strftime("%d %b %Y, %H:%M IST")
        incidents.append({
            "id": inc_id,
            "victim_name": victim,
            "victim_phone": f"+91-97{inc_id[-4:]}993",
            "amount": amt,
            "currency": "INR",
            "transaction_id": tx_id,
            "scam_type": "Digital Arrest",
            "severity": "CRITICAL",
            "status": "ESCALATED",
            "narrative": narrative,
            "recipient_upi": CLUSTER_C_ENTITIES["upi_vpa"],
            "scammer_phone": CLUSTER_C_ENTITIES["phone"],
            "bank_account": CLUSTER_C_ENTITIES["bank_account"],
            "domain": CLUSTER_C_ENTITIES["domain"],
            "qr_id": None,
            "created_at": t_time,
            "shared_cluster": "Cluster C (Digital Arrest Syndicate)",
            "red_flags": [
                "Govt / Police officer impersonation",
                "Fake arrest warrant & video coercion",
                "High value funds transfer to dummy escrow",
                "Known mule account flagged in multiple states"
            ]
        })
        transactions.append({
            "transaction_id": tx_id,
            "amount": amt,
            "currency": "INR",
            "sender": victim,
            "recipient": CLUSTER_C_ENTITIES["upi_vpa"],
            "recipient_phone": CLUSTER_C_ENTITIES["phone"],
            "recipient_bank": "Axis Bank",
            "date": t_time,
            "status": "Completed",
            "scam_category": "Digital Arrest",
            "note": "Judicial verification security deposit"
        })

    # -------------------------------------------------------------
    # 4. Generate Remaining 100+ realistic distributed incidents across categories
    # -------------------------------------------------------------
    categories = [
        ("Investment Scam", "HIGH", 45000, CLUSTER_E_ENTITIES),
        ("Fake Loan", "HIGH", 12500, CLUSTER_D_ENTITIES),
        ("Job Scam", "MEDIUM", 6500, {"phone": "+91-93112-44019", "upi_vpa": "telegram-tasks.hire@icici", "domain": "earn-daily-parttime.site"}),
        ("Fake Refund", "MEDIUM", 4200, {"phone": "+91-94551-82011", "upi_vpa": "instant-refund.portal@paytm", "domain": "quick-cashback-portal.net"}),
        ("QR Scam", "HIGH", 8900, {"phone": "+91-89221-30044", "upi_vpa": "merchant-settlement.pay@sbi", "qr_id": "QR_PAY_4412"}),
        ("Lottery / Prize", "LOW", 2500, {"phone": "+91-96541-11928", "upi_vpa": "kbc-prize.tax-clear@ybl", "domain": "kbc-lucky-winner.club"}),
    ]

    names_pool = [
        "Amitabh Roy", "Bhavna Patel", "Chetan Bhagat", "Divya Menon", "Eshwar Reddy",
        "Farida Khan", "Girish Kulkarni", "Himani Joshi", "Ishaan Malhotra", "Jaya Bachchan",
        "Kartik Aryan", "Lakshmi Bai", "Manish Sisodia", "Nandini Murthy", "Omkar Nath",
        "Praveen Kumar", "Qasim Ali", "Ritu Karidhal", "Saurabh Ganguly", "Tanvi Azmi",
        "Umesh Yadav", "Varun Dhawan", "Wasim Akram", "Yuvraj Singh", "Zoya Akhtar",
        "Abhay Deol", "Bipasha Basu", "Chirag Paswan", "Daisy Shah", "Emraan Hashmi",
        "Fardeen Khan", "Genelia D'Souza", "Harshvardhan Kapoor", "Ileana D'Cruz", "Jackie Shroff"
    ]

    base_id = 10370
    for i in range(100):
        cat_idx = i % len(categories)
        cat_name, severity, base_amt, ent = categories[cat_idx]
        name = names_pool[i % len(names_pool)]
        inc_num = base_id - i
        inc_id = f"MT-{inc_num}"
        tx_id = f"TXN{600000 + i * 37}"
        amt = base_amt + (i * 350) % 7500
        
        # Determine status
        status = "REVIEW_REQUIRED" if i % 3 == 0 else ("ESCALATED" if i % 2 == 0 else "INVESTIGATING")
        minutes_ago = 1800 + (i * 45)
        t_time = (now - timedelta(minutes=minutes_ago)).strftime("%d %b %Y, %H:%M IST")
        
        incidents.append({
            "id": inc_id,
            "victim_name": name,
            "victim_phone": f"+91-98{1000 + i}440",
            "amount": amt,
            "currency": "INR",
            "transaction_id": tx_id,
            "scam_type": cat_name,
            "severity": severity,
            "status": status,
            "narrative": f"Victim was targeted with {cat_name.lower()} via SMS and social channel. Lost ₹{amt:,} after being promised returns/relief.",
            "recipient_upi": ent.get("upi_vpa", f"merchant.{i}@upi"),
            "scammer_phone": ent.get("phone", f"+91-99881-{i:05d}"),
            "bank_account": ent.get("bank_account", None),
            "domain": ent.get("domain", None),
            "qr_id": ent.get("qr_id", None),
            "created_at": t_time,
            "shared_cluster": f"{cat_name} Pattern" if (i % 4 == 0) else None,
            "red_flags": [
                f"Suspicious {cat_name.lower()} pattern",
                "High frequency incoming UPI transfers",
                "Urgent unsolicited contact"
            ]
        })
        transactions.append({
            "transaction_id": tx_id,
            "amount": amt,
            "currency": "INR",
            "sender": name,
            "recipient": ent.get("upi_vpa", f"merchant.{i}@upi"),
            "recipient_phone": ent.get("phone", f"+91-99881-{i:05d}"),
            "recipient_bank": "State Bank of India",
            "date": t_time,
            "status": "Completed",
            "scam_category": cat_name,
            "note": f"{cat_name} transfer payment"
        })

    return {
        "incidents": incidents,
        "transactions": transactions
    }
