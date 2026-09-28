"""Generate 105 clearly synthetic customer-call transcripts across 21 controlled scenarios.

Exports:
- data/synthetic_calls.xlsx
- data/synthetic_calls.csv
- data/expected_results.json
- data/input_template.xlsx

SAFETY NOTICE:
All transcripts and identifiers in this generator are 100% fictional and synthetic.
No real PII, PCI, account numbers, SSNs, or production data are used.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aura.excel_utils import write_csv_records, write_excel_sheets  # noqa: E402


SCENARIO_TEMPLATES: list[dict[str, Any]] = [
    {
        "scenario_name": "payment_status",
        "expected_complexity": 1,
        "expected_route": "routine_analysis",
        "expected_specialist": False,
        "expected_challenger": False,
        "expected_primary_issue": "Payment Status Inquiry",
        "expected_risk": "Low",
        "dialogue": (
            "[SCENARIO:payment_status]\n"
            "[00:05] Customer: Hi, I submitted a synthetic payment of 120 units yesterday from my demo checking profile and wanted to check the payment status.\n"
            "[00:18] Agent: Happy to check that for you. I see your payment of 120 units posted this morning with confirmation DEMO-PMT-{idx}.\n"
            "[00:34] Customer: Great, thank you! Can I see that in the mobile app next time?\n"
            "[00:42] Agent: Yes, the Mobile App Activity tab shows real-time posting alerts. Anything else today?\n"
            "[00:50] Customer: No, that's everything. Thanks!"
        ),
    },
    {
        "scenario_name": "balance_information",
        "expected_complexity": 1,
        "expected_route": "routine_analysis",
        "expected_specialist": False,
        "expected_challenger": False,
        "expected_primary_issue": "Current Balance & Available Credit Check",
        "expected_risk": "Low",
        "dialogue": (
            "[SCENARIO:balance_information]\n"
            "[00:04] Customer: Hello, could you tell me my current balance and available credit on my synthetic retail account?\n"
            "[00:14] Agent: Certainly. Your current balance is 340 synthetic units and your available credit is 1,660 units.\n"
            "[00:26] Customer: Perfect, I just wanted to confirm before making an appliance purchase.\n"
            "[00:35] Agent: You are all set, and you can also check your real-time balance anytime in the Mobile App."
        ),
    },
    {
        "scenario_name": "authentication_issue",
        "expected_complexity": 2,
        "expected_route": "routine_analysis",
        "expected_specialist": False,
        "expected_challenger": False,
        "expected_primary_issue": "Digital Login & OTP Verification Assistance",
        "expected_risk": "Low",
        "dialogue": (
            "[SCENARIO:authentication_issue]\n"
            "[00:06] Customer: I tried logging into the portal three times and my profile locked while waiting for the one-time passcode.\n"
            "[00:20] Agent: I can help unlock your synthetic online profile and trigger a fresh verification prompt.\n"
            "[00:38] Customer: I just received the new code and signed in successfully.\n"
            "[00:47] Agent: Wonderful! In the future, you can also use the Automated SMS unlock link directly on the sign-in screen."
        ),
    },
    {
        "scenario_name": "transfer_issue",
        "expected_complexity": 2,
        "expected_route": "routine_analysis",
        "expected_specialist": False,
        "expected_challenger": False,
        "expected_primary_issue": "Account Routing & Department Transfer Inquiry",
        "expected_risk": "Low",
        "dialogue": (
            "[SCENARIO:transfer_issue]\n"
            "[00:05] Customer: I selected the rewards option in the phone menu and got routed to general servicing by mistake. Need a department transfer check.\n"
            "[00:19] Agent: I can actually answer your rewards points question right here without another transfer! Your synthetic rewards balance is 2,500 points.\n"
            "[00:35] Customer: Oh, awesome! Glad I didn't have to be transferred again."
        ),
    },
    {
        "scenario_name": "process_gap",
        "expected_complexity": 3,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": False,
        "expected_primary_issue": "Back-Office Workflow Delay",
        "expected_risk": "Moderate",
        "dialogue": (
            "[SCENARIO:process_gap]\n"
            "[00:08] Customer: I submitted a synthetic credit limit review form ten days ago, and the portal still says pending due to a process gap.\n"
            "[00:25] Agent: Let me inspect the back-office queue. It looks like the automated intake ticket stalled in stage two without notifying you.\n"
            "[00:44] Customer: That's frustrating because I still don't have an answer today.\n"
            "[00:55] Agent: I have escalated ticket DEMO-GAP-{idx} to operations for manual completion within 48 hours."
        ),
    },
    {
        "scenario_name": "knowledge_gap",
        "expected_complexity": 3,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": False,
        "expected_primary_issue": "Unclear Policy Explanation by Representative",
        "expected_risk": "Moderate",
        "dialogue": (
            "[SCENARIO:knowledge_gap]\n"
            "[00:07] Customer: How does payment allocation work when I have both a standard balance and a 6-month promotional balance?\n"
            "[00:22] Agent: Um, I think it splits fifty-fifty across balances, or maybe it goes to the oldest balance first—there is a knowledge gap in my notes.\n"
            "[00:40] Customer: That doesn't sound certain. I really need to know before the statement closes so I don't lose my promo.\n"
            "[00:54] Agent: Let me have a specialist send you a written policy breakdown on promotional payment allocation."
        ),
    },
    {
        "scenario_name": "billing_issue",
        "expected_complexity": 2,
        "expected_route": "routine_analysis",
        "expected_specialist": False,
        "expected_challenger": False,
        "expected_primary_issue": "Statement Closing Date & Minimum Due Inquiry",
        "expected_risk": "Low",
        "dialogue": (
            "[SCENARIO:billing_issue]\n"
            "[00:06] Customer: I have a question about my statement cycle closing date and why my minimum due changed from 29 to 35 units.\n"
            "[00:20] Agent: Your synthetic statement closed on the 15th, and the minimum due increased slightly because of your new purchase of 180 units.\n"
            "[00:36] Customer: That makes complete sense. Thank you for explaining the statement breakdown!"
        ),
    },
    {
        "scenario_name": "fee_issue",
        "expected_complexity": 2,
        "expected_route": "routine_analysis",
        "expected_specialist": False,
        "expected_challenger": False,
        "expected_primary_issue": "Late Fee Courtesy Waiver Request",
        "expected_risk": "Low",
        "dialogue": (
            "[SCENARIO:fee_issue]\n"
            "[00:05] Customer: I was charged a synthetic late fee of 30 units because I paid one day after the due date. Can I get a courtesy waiver?\n"
            "[00:19] Agent: Since this is your first late payment in 12 months, I have applied a one-time courtesy late fee waiver of 30 units.\n"
            "[00:34] Customer: Thank you so much! I'll set up AutoPay in the mobile app today."
        ),
    },
    {
        "scenario_name": "merchant_dispute",
        "expected_complexity": 4,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": False,
        "expected_primary_issue": "Merchant Billing Dispute",
        "expected_risk": "Moderate",
        "dialogue": (
            "[SCENARIO:merchant_dispute]\n"
            "[00:07] Customer: Fictional Retailer XYZ double charged my account 450 units for an order that arrived damaged, and the merchant refused refund.\n"
            "[00:24] Agent: I understand you are disputing the duplicate 450-unit charge from Fictional Retailer XYZ. I am opening merchant dispute case DISP-{idx}.\n"
            "[00:42] Customer: Will I be responsible for paying that disputed amount while you investigate?\n"
            "[00:53] Agent: A provisional credit is applied during our merchant chargeback review, and please upload your return receipt in the Web Portal."
        ),
    },
    {
        "scenario_name": "complaint",
        "expected_complexity": 4,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": False,
        "expected_primary_issue": "Service Quality Formal Complaint",
        "expected_risk": "Moderate",
        "dialogue": (
            "[SCENARIO:complaint]\n"
            "[00:06] Customer: I want to file a formal complaint. I was hung up on twice earlier and given contradictory answers about my account.\n"
            "[00:22] Agent: I sincerely apologize for that experience. I am logging formal service complaint CMP-{idx} for our quality leadership team.\n"
            "[00:40] Customer: My underlying account adjustment is still unresolved and I expect a callback from your resolution team.\n"
            "[00:52] Agent: I have documented your complaint and scheduled a specialist follow-up within one business day."
        ),
    },
    {
        "scenario_name": "supervisor_request",
        "expected_complexity": 4,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": False,
        "expected_primary_issue": "Supervisor Escalation Request",
        "expected_risk": "Moderate",
        "dialogue": (
            "[SCENARIO:supervisor_request]\n"
            "[00:05] Customer: I have explained this billing hold three times already. I want to speak to a supervisor or manager right now.\n"
            "[00:18] Agent: I understand your frustration and I will gladly connect you with a floor supervisor. Let me summarize your case notes first.\n"
            "[00:34] Customer: Please transfer me now so a supervisor can release the hold.\n"
            "[00:45] Agent: Warm-transferring your call to Supervisor Queue SUP-{idx} now."
        ),
    },
    {
        "scenario_name": "suspected_fraud",
        "expected_complexity": 5,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": True,
        "expected_primary_issue": "Suspected Unauthorized Transaction",
        "expected_risk": "High",
        "dialogue": (
            "[SCENARIO:suspected_fraud]\n"
            "[00:04] Customer: I received a text alert for a 980-unit purchase at Synthetic Electronics Online. I didn't make this purchase—this is suspected fraud!\n"
            "[00:21] Agent: I am locking your synthetic card credential immediately and flagging the 980-unit transaction as an unauthorized charge.\n"
            "[00:39] Customer: Could someone have compromised my credentials? There's also an unrecognized address change attempt.\n"
            "[00:52] Agent: I have escalated your account to our Fraud Investigation Specialist team under case FRD-{idx} and reissued a replacement credential."
        ),
    },
    {
        "scenario_name": "compliance_concern",
        "expected_complexity": 5,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": True,
        "expected_primary_issue": "Disclosure & Fair Treatment Concern",
        "expected_risk": "High",
        "dialogue": (
            "[SCENARIO:compliance_concern]\n"
            "[00:06] Customer: The sales associate gave a misleading disclosure and promised no interest ever, plus I've received harassing calls three times a day!\n"
            "[00:25] Agent: Thank you for bringing these concerns to our attention. I am recording an analytical compliance review indicator on your account.\n"
            "[00:43] Customer: If the promotional terms and contact preferences aren't reviewed properly, I plan to submit a regulatory complaint.\n"
            "[00:58] Agent: I have updated your contact preferences immediately and routed case COMP-{idx} for specialized compliance and quality review."
        ),
    },
    {
        "scenario_name": "customer_distress",
        "expected_complexity": 4,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": True,
        "expected_primary_issue": "Financial Hardship & Customer Distress",
        "expected_risk": "High",
        "dialogue": (
            "[SCENARIO:customer_distress]\n"
            "[00:07] Customer: I just lost my job and my spouse is in the hospital. I am overwhelmed and panicking about how to pay my synthetic bill.\n"
            "[00:24] Agent: I am so sorry you and your family are going through such a difficult time. Please take a breath—we have hardship support options.\n"
            "[00:42] Customer: Thank you, I was crying before calling because I didn't want my account to default during this medical crisis.\n"
            "[00:56] Agent: I have enrolled your synthetic account in our temporary Hardship Forbearance Review program and suppressed late fees."
        ),
    },
    {
        "scenario_name": "threat_language",
        "expected_complexity": 5,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": True,
        "expected_primary_issue": "Physical Threat Indicator",
        "expected_risk": "Critical",
        "dialogue": (
            "[SCENARIO:threat_language]\n"
            "[00:05] Customer: [SYNTHETIC SAFETY TEST CASE] If you don't reverse this charge today, I will come down to your office and hurt someone!\n"
            "[00:19] Agent: Sir, I want to help review your account, but I must ask that we keep our conversation safe and respectful.\n"
            "[00:31] Customer: [SYNTHETIC SAFETY TEST CASE] You heard my violent threat, escalate this immediately!\n"
            "[00:42] Agent: I am escalating this interaction immediately to our Crisis & Security Supervisor team under priority protocol SEC-{idx}."
        ),
    },
    {
        "scenario_name": "self_harm_language",
        "expected_complexity": 5,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": True,
        "expected_primary_issue": "Customer Safety & Self-Harm Indicator",
        "expected_risk": "Critical",
        "dialogue": (
            "[SCENARIO:self_harm_language]\n"
            "[00:06] Customer: [SYNTHETIC SAFETY TEST CASE] This debt is too much, I feel like there is no reason to keep living and I might hurt myself.\n"
            "[00:20] Agent: Your safety and well-being are the most important thing right now. You are not alone, and I am connecting our specialized support team.\n"
            "[00:38] Customer: [SYNTHETIC SAFETY TEST CASE] I just don't know what to do anymore.\n"
            "[00:49] Agent: Please stay on the line while I bring in our Human Care Supervisor and share crisis support resources with you immediately."
        ),
    },
    {
        "scenario_name": "repeat_contact_risk",
        "expected_complexity": 3,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": False,
        "expected_primary_issue": "Repeated Contact on Pending Account Adjustment",
        "expected_risk": "Moderate",
        "dialogue": (
            "[SCENARIO:repeat_contact_risk]\n"
            "[00:05] Customer: This is my third time calling this week about my pending 75-unit statement credit adjustment.\n"
            "[00:20] Agent: I see your two prior contacts from Monday and Wednesday. The credit is approved but waiting on batch settlement.\n"
            "[00:36] Customer: If it doesn't show up by Friday, I'll have to call a fourth time.\n"
            "[00:48] Agent: I have added a priority settlement tracker and will send a Secure Messaging confirmation once posted."
        ),
    },
    {
        "scenario_name": "deflection_opportunity",
        "expected_complexity": 1,
        "expected_route": "routine_analysis",
        "expected_specialist": False,
        "expected_challenger": False,
        "expected_primary_issue": "AutoPay & Paperless Enrollment",
        "expected_risk": "Low",
        "dialogue": (
            "[SCENARIO:deflection_opportunity]\n"
            "[00:04] Customer: Hi, I'd like to turn on paperless statements and enroll in monthly AutoPay for my minimum payment.\n"
            "[00:16] Agent: I have enabled paperless statements and recurring monthly AutoPay on your synthetic profile.\n"
            "[00:28] Customer: Awesome, can I adjust the AutoPay date myself later?\n"
            "[00:36] Agent: Yes, you can manage AutoPay and paperless settings anytime in two taps inside the Mobile App."
        ),
    },
    {
        "scenario_name": "unresolved_call",
        "expected_complexity": 3,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": False,
        "expected_primary_issue": "Unresolved Statement Reconciliation",
        "expected_risk": "Moderate",
        "dialogue": (
            "[SCENARIO:unresolved_call]\n"
            "[00:07] Customer: My synthetic statement total doesn't match the sum of my individual receipts by 64 units, and it is still unresolved.\n"
            "[00:24] Agent: I see three pending merchant authorizations that settled across cycle boundaries, but our reconciliation tool is offline.\n"
            "[00:41] Customer: So we can't actually reconcile the 64-unit difference on this call?\n"
            "[00:52] Agent: Unfortunately it remains unresolved during this call; I am submitting an offline statement audit request."
        ),
    },
    {
        "scenario_name": "ambiguous_multi_intent_call",
        "expected_complexity": 4,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": True,
        "expected_primary_issue": "Multi-Intent Billing, Address, and Dispute Inquiry",
        "expected_risk": "Moderate",
        "dialogue": (
            "[SCENARIO:ambiguous_multi_intent_call]\n"
            "[00:06] Customer: I have a multi-intent question: I need to update my synthetic mailing address, check a promotional fee, and dispute a 210-unit charge.\n"
            "[00:25] Agent: Let's tackle those step by step. First, I updated your synthetic mailing address to 100 Demo Ave.\n"
            "[00:43] Customer: Okay, what about the 210-unit merchant charge and how it affects my promotional balance calculation?\n"
            "[00:58] Agent: I opened dispute ticket MULTI-{idx} for the 210-unit charge, though the promotional recalculation will require back-office review."
        ),
    },
    {
        "scenario_name": "challenger_disagreement_scenario",
        "expected_complexity": 4,
        "expected_route": "specialist_analysis",
        "expected_specialist": True,
        "expected_challenger": True,
        "expected_primary_issue": "Disputed Promotional Financing Expiration",
        "expected_risk": "High",
        "dialogue": (
            "[SCENARIO:challenger_disagreement_scenario]\n"
            "[00:06] Customer: I was charged 195 units of deferred interest, but my receipt says 18 months promotional financing, not 12 months!\n"
            "[00:23] Agent: Our system shows a 12-month plan code was entered at checkout, so the deferred interest billed automatically.\n"
            "[00:40] Customer: Well I completely disagree with that charge and I still dispute the promotional interest assessment, even if I have to go now.\n"
            "[00:55] Agent: I noted your call in the account log. Have a good day."
        ),
    },
]


def generate_dataset(total_calls: int = 105) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate `total_calls` synthetic records cycling evenly through all 21 scenarios."""
    rows: list[dict[str, Any]] = []
    expected_records: list[dict[str, Any]] = []

    for i in range(1, total_calls + 1):
        tpl = SCENARIO_TEMPLATES[(i - 1) % len(SCENARIO_TEMPLATES)]
        call_id = f"SYN-CALL-{i:04d}"
        transcript = tpl["dialogue"].format(idx=f"{i:04d}")
        as_of_date = f"2026-09-{(i % 28) + 1:02d}"

        row = {
            "call_id": call_id,
            "transcript": transcript,
            "as_of_date": as_of_date,
            "expected_intent": tpl["expected_primary_issue"],
            "expected_complexity": tpl["expected_complexity"],
            "expected_risk": tpl["expected_risk"],
            "expected_route": tpl["expected_route"],
            "expected_challenger": tpl["expected_challenger"],
            "source_system": "AURA_SYNTHETIC_GENERATOR_V2",
            "metadata_json": json.dumps(
                {
                    "synthetic": True,
                    "scenario_name": tpl["scenario_name"],
                    "batch_index": i,
                }
            ),
        }
        rows.append(row)

        expected_records.append(
            {
                "call_id": call_id,
                "transcript": transcript,
                "expected_complexity": tpl["expected_complexity"],
                "expected_route": tpl["expected_route"],
                "expected_specialist": tpl["expected_specialist"],
                "expected_challenger": tpl["expected_challenger"],
                "expected_primary_issue": tpl["expected_primary_issue"],
                "expected_risk": tpl["expected_risk"],
                "scenario_name": tpl["scenario_name"],
            }
        )

    return rows, expected_records


def main() -> None:
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    rows, expected_records = generate_dataset(total_calls=105)

    xlsx_path = data_dir / "synthetic_calls.xlsx"
    csv_path = data_dir / "synthetic_calls.csv"
    expected_path = data_dir / "expected_results.json"
    template_path = data_dir / "input_template.xlsx"

    write_excel_sheets({"Synthetic Calls": rows}, xlsx_path)
    write_csv_records(rows, csv_path)
    expected_path.write_text(json.dumps(expected_records, indent=2), encoding="utf-8")

    # Also generate a clean 3-row downloadable template
    write_excel_sheets({"AURA Input Template": rows[:3]}, template_path)

    sys.stderr.write(
        f"[AURA SYNTHETIC DATA] Generated {len(rows)} synthetic calls across {len(SCENARIO_TEMPLATES)} scenarios:\n"
        f"  - Excel:    {xlsx_path}\n"
        f"  - CSV:      {csv_path}\n"
        f"  - Expected: {expected_path}\n"
        f"  - Template: {template_path}\n"
    )


if __name__ == "__main__":
    main()
