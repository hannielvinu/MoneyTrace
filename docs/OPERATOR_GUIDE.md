# MoneyTrace help desk — operator quick-start (WhiteHats)

You are a **fraud operator**: you review reports from scam victims, check the AI's work and sign off CRITICAL cases.
MoneyTrace is an independent student project, **not** a police, government or bank service. Every victim must
also report on **1930** / **cybercrime.gov.in** and to their bank. Say this in every conversation.

## 1. Log in
- Open the help-desk URL and log in with the operator account Hanniel created for you
  (`scripts/create_operator.py`). Keep the password private; ask Hanniel to reset it if it leaks.
- Operators see: **Live Investigations**, **Case Workspace**, **Operations Dashboard** and **Evaluation**.
  Victims see only their own reports.

## 2. What happens when a victim reports
1. The victim types, speaks (English / Hindi / Tamil / Kannada) or uploads a payment screenshot, and ticks the consent box.
2. The **coordinator agent** hands the case to three specialists:
   - **Intake**: turns the report into a structured case record (amount, transaction ID, recipient UPI, fraud type).
   - **Investigation**: looks up the ledger, scores fraud signals, searches for other victims who paid the same
     UPI / phone / account (mule ring), then decides severity and explains why.
   - **Guidance**: writes steps for the victim using **only** official RBI / NPCI / CERT-In / I4C / SEBI advisories,
     each step with its source link.
3. A **grounding check** removes any step its source does not support. If nothing is left, the victim gets the
   safe fallback ("Report immediately on 1930 / cybercrime.gov.in and contact your bank").
4. You see all 12 milestones live in **Live Investigations**.

## 3. Your job on each case
- Open the case in **Case Workspace**.
- Check **Severity justification**: does it match the evidence (amount, ledger match, related cases)?
- Check **Guidance**: every step should have a source. Open one or two links and confirm they say what the step says.
- If `ai_investigator.status` is not `GEMINI LIVE`, the agents fell back to rules; read the case yourself.
- **CRITICAL cases** show `HUMAN_REVIEW_REQUIRED`. Use **Approve** (escalation is right) or **Request info**.
  Your email is written into the audit trail.

## 4. Talking to victims
- Be calm and short. First: has the money gone? If yes, **call 1930 now** (the golden hour matters) and
  call the bank's official number (from the card / passbook / official app, never from a Google search).
- Never ask for OTP, UPI PIN, passwords, full card numbers or Aadhaar. Never promise recovery.
- Do not contact the scammer, and do not ask the victim to.
- If the victim mentions threats, sextortion or self-harm, give them the police number (112) and stay with them.

## 5. Privacy
- Do not copy victims' data into WhatsApp groups or personal notes. Discuss cases only inside MoneyTrace.
- Reports are kept for at most 90 days. Usage statistics (`/api/helpdesk/usage`) have no personal data.

## 6. When something breaks
- No guidance after 5 minutes: tell the victim to report on 1930 / cybercrime.gov.in and inform Hanniel.
- Wrong advice in a step: note the case ID and step, and tell Hanniel. Do **not** pass the step on.
