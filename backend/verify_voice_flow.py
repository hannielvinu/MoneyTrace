from moneytrace.services.voice_response import resolve_amount_with_provenance, build_voice_script

tests = [
    ("I was tricked into sending 18,500 rupees to someone.", "en"),
    ("I transferred 7,250 rupees to the wrong person.", "en"),
    ("I lost 50,000 rupees after someone convinced me to make a payment.", "en"),
    ("Someone hacked my device and accessed my account.", "en")
]

for idx, (text, lang) in enumerate(tests, 1):
    prov = resolve_amount_with_provenance(text, None)
    amt = prov["amount"]
    src = prov["amount_source"]
    frag = prov["amount_source_text"]
    conf = prov["amount_conflict"]
    script = build_voice_script(
        event_type="complaint_received",
        case_id=f"MT-1080{idx}",
        language=lang,
        amount=amt,
        amount_source=src,
        complaint_narrative=text
    )
    res_script = build_voice_script(
        event_type="investigation_completed",
        case_id=f"MT-1080{idx}",
        language=lang,
        amount=amt,
        amount_source=src,
        status="ESCALATED",
        scam_type="Fake KYC",
        complaint_narrative=text,
        investigation_result={"status": "ESCALATED", "incident_type": "Fake KYC", "recommended_action": "Freeze beneficiary account"}
    )
    print(f"=== TEST CASE {idx} ===")
    print("Victim Spoke:        ", text)
    print(f"Extracted Amount:     {amt} (source: {src}, fragment: '{frag}', conflict: {conf})")
    print("Voice Acknowledgement:", script)
    print("Voice Resolution:     ", res_script)
    print()
