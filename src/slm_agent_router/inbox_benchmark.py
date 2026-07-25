from __future__ import annotations

import asyncio
import re
import time
from typing import Any


AGENTS: dict[str, dict[str, Any]] = {
    "cascade": {
        "label": "SLM Cascade",
        "model": "local cascade + fallback",
        "speed_ms": 320,
        "token_scale": 0.48,
        "cost_per_1k": 0.0012,
        "draft_quality": 0.83,
        "coverage_bias": -1,
        "route": ["SLM triage", "SLM rank", "LLM fallback for wording", "SLM draft check"],
    },
    "openai": {
        "label": "OpenAI Agent",
        "model": "frontier agent",
        "speed_ms": 850,
        "token_scale": 1.08,
        "cost_per_1k": 0.010,
        "draft_quality": 0.93,
        "coverage_bias": 1,
        "route": ["LLM read", "LLM rank", "LLM synthesize", "LLM draft"],
    },
    "claude": {
        "label": "Claude Agent",
        "model": "frontier agent",
        "speed_ms": 940,
        "token_scale": 1.16,
        "cost_per_1k": 0.012,
        "draft_quality": 0.95,
        "coverage_bias": 1,
        "route": ["LLM read", "LLM reason", "LLM prioritize", "LLM draft"],
    },
}


SYNTHETIC_INBOX: list[dict[str, Any]] = [
    {
        "id": "E-1001",
        "received": "2026-07-24 08:12",
        "from_name": "Maya Chen",
        "from_email": "maya@northstarvc.com",
        "role": "Investor",
        "subject": "Q3 diligence follow-up before Monday partner meeting",
        "body": "Can you send updated June revenue, cohort retention, burn, and the enterprise pipeline notes before 5 PM today? Our partners are reviewing the company Monday morning and want to understand whether expansion revenue is repeatable.",
        "category": "Investor",
        "priority": 98,
        "urgency": "critical",
        "deadline": "Today 5:00 PM",
        "needs_response": True,
        "unread": True,
        "tags": ["fundraising", "metrics", "deadline", "board"],
        "expected_action": "Send the updated metrics packet and explain the enterprise expansion trend.",
    },
    {
        "id": "E-1002",
        "received": "2026-07-24 08:25",
        "from_name": "Jordan Lee",
        "from_email": "jordan@apexhealth.io",
        "role": "Customer champion",
        "subject": "Security questionnaire blocking pilot launch",
        "body": "Our procurement team will not approve the pilot until the SOC 2 bridge letter and subprocessors list are attached. Can you get those over today and confirm whether SAML is available in the pilot workspace?",
        "category": "Customer",
        "priority": 96,
        "urgency": "critical",
        "deadline": "Today",
        "needs_response": True,
        "unread": True,
        "tags": ["security", "customer", "pilot", "revenue"],
        "expected_action": "Attach security documents, answer SAML availability, and unblock pilot approval.",
    },
    {
        "id": "E-1003",
        "received": "2026-07-24 08:49",
        "from_name": "Priya Raman",
        "from_email": "priya@company.com",
        "role": "Finance lead",
        "subject": "Payroll approval needed by noon",
        "body": "Please approve the payroll batch in Rippling before noon. The total is $284,300 and includes the new contractor invoices for support coverage. I flagged two line items in the spreadsheet.",
        "category": "Finance",
        "priority": 94,
        "urgency": "critical",
        "deadline": "Today 12:00 PM",
        "needs_response": True,
        "unread": True,
        "tags": ["finance", "payroll", "approval"],
        "expected_action": "Review flagged items, approve payroll, and confirm completion.",
    },
    {
        "id": "E-1004",
        "received": "2026-07-24 09:05",
        "from_name": "Leo Martinez",
        "from_email": "leo@company.com",
        "role": "Head of product",
        "subject": "Decision needed: ship inbox beta to design partners",
        "body": "The team can ship the inbox beta today, but we need a call on whether to include auto-send or keep drafts review-only. Support prefers review-only because one customer has strict approval language.",
        "category": "Product",
        "priority": 89,
        "urgency": "high",
        "deadline": "Today 2:00 PM",
        "needs_response": True,
        "unread": False,
        "tags": ["product", "launch", "decision"],
        "expected_action": "Choose review-only beta launch and explain the risk tradeoff.",
    },
    {
        "id": "E-1005",
        "received": "2026-07-24 09:18",
        "from_name": "Nora Patel",
        "from_email": "nora@vestalaw.com",
        "role": "Outside counsel",
        "subject": "MSA redlines from Summit Bank",
        "body": "Summit Bank returned the MSA with redlines around liability cap, audit rights, and data retention. I recommend accepting the audit language, narrowing retention, and rejecting the uncapped liability request. Need your business position before I reply.",
        "category": "Legal",
        "priority": 88,
        "urgency": "high",
        "deadline": "Today",
        "needs_response": True,
        "unread": True,
        "tags": ["legal", "enterprise", "contract"],
        "expected_action": "Give business position on redlines so counsel can respond.",
    },
    {
        "id": "E-1006",
        "received": "2026-07-24 09:42",
        "from_name": "Ari Feld",
        "from_email": "ari@clearbank.com",
        "role": "Enterprise buyer",
        "subject": "Can we move the implementation kickoff earlier?",
        "body": "Our COO wants the kickoff moved from August 8 to July 31. If your implementation team can support it, we can sign this week. Please confirm coverage and send the revised rollout plan.",
        "category": "Sales",
        "priority": 92,
        "urgency": "critical",
        "deadline": "Today",
        "needs_response": True,
        "unread": True,
        "tags": ["sales", "enterprise", "implementation", "revenue"],
        "expected_action": "Confirm implementation capacity and send revised rollout plan.",
    },
    {
        "id": "E-1007",
        "received": "2026-07-24 10:01",
        "from_name": "Elena Brooks",
        "from_email": "elena@company.com",
        "role": "Customer success",
        "subject": "Churn risk: Northwind usage dropped 60 percent",
        "body": "Northwind has not completed onboarding and usage dropped sharply this week. Their VP asked whether the workflow can integrate with Outlook shared mailboxes. Can you help me draft a retention note?",
        "category": "Customer",
        "priority": 87,
        "urgency": "high",
        "deadline": "Today",
        "needs_response": True,
        "unread": False,
        "tags": ["customer", "churn", "outlook", "retention"],
        "expected_action": "Draft retention response and answer shared mailbox integration path.",
    },
    {
        "id": "E-1008",
        "received": "2026-07-24 10:16",
        "from_name": "Ben Ortiz",
        "from_email": "ben@company.com",
        "role": "Engineering manager",
        "subject": "Incident review: duplicate replies in Gmail connector",
        "body": "The root cause was a retry loop after a 502 from the mail provider. We patched idempotency keys, but I need you to approve the customer-facing incident note before 3 PM.",
        "category": "Engineering",
        "priority": 86,
        "urgency": "high",
        "deadline": "Today 3:00 PM",
        "needs_response": True,
        "unread": True,
        "tags": ["incident", "gmail", "engineering", "customer"],
        "expected_action": "Approve or edit the customer-facing incident note.",
    },
    {
        "id": "E-1009",
        "received": "2026-07-24 10:31",
        "from_name": "Sofia Grant",
        "from_email": "sofia@pressline.com",
        "role": "Reporter",
        "subject": "Comment request on AI email agents",
        "body": "I am writing about enterprise teams adopting AI email agents. Would you be willing to comment on safeguards, user review, and audit logs? Deadline is tomorrow morning.",
        "category": "Press",
        "priority": 73,
        "urgency": "medium",
        "deadline": "Tomorrow morning",
        "needs_response": True,
        "unread": True,
        "tags": ["press", "ai agents", "audit logs"],
        "expected_action": "Offer a short statement and emphasize review controls.",
    },
    {
        "id": "E-1010",
        "received": "2026-07-24 10:42",
        "from_name": "IT Alerts",
        "from_email": "alerts@company.com",
        "role": "System",
        "subject": "Okta suspicious login blocked for contractor account",
        "body": "A suspicious login attempt from an unusual location was blocked for contractor.jules. No user action was taken. Security recommends rotating the temporary password.",
        "category": "Security",
        "priority": 84,
        "urgency": "high",
        "deadline": "Today",
        "needs_response": False,
        "unread": True,
        "tags": ["security", "okta", "contractor"],
        "expected_action": "Route to security owner and verify password rotation.",
    },
    {
        "id": "E-1011",
        "received": "2026-07-24 11:03",
        "from_name": "Talia Wynn",
        "from_email": "talia@brightpath.edu",
        "role": "Customer admin",
        "subject": "Need invoice split across two departments",
        "body": "Can the annual invoice be split 70/30 between Student Success and IT? Our purchasing deadline is Tuesday and the current invoice will be rejected by accounting.",
        "category": "Finance",
        "priority": 78,
        "urgency": "medium",
        "deadline": "Tuesday",
        "needs_response": True,
        "unread": False,
        "tags": ["billing", "customer", "invoice"],
        "expected_action": "Create split invoice or route to finance with confirmation.",
    },
    {
        "id": "E-1012",
        "received": "2026-07-24 11:18",
        "from_name": "Owen Miller",
        "from_email": "owen@company.com",
        "role": "Recruiting",
        "subject": "Final candidate references for staff designer",
        "body": "All references for Mina are attached. Two are excellent and one flagged that she prefers clear decision ownership. Are you comfortable moving to offer today?",
        "category": "Recruiting",
        "priority": 72,
        "urgency": "medium",
        "deadline": "Today",
        "needs_response": True,
        "unread": True,
        "tags": ["hiring", "design", "offer"],
        "expected_action": "Decide whether to move to offer and respond to recruiting.",
    },
    {
        "id": "E-1013",
        "received": "2026-07-24 11:44",
        "from_name": "Ravi Singh",
        "from_email": "ravi@company.com",
        "role": "Data science",
        "subject": "Weekly activation report",
        "body": "Activation improved from 42 percent to 48 percent after checklist changes. The biggest remaining drop-off is connecting the first mailbox. No response needed unless you want a deeper cut.",
        "category": "Analytics",
        "priority": 55,
        "urgency": "low",
        "deadline": "",
        "needs_response": False,
        "unread": True,
        "tags": ["analytics", "activation", "weekly"],
        "expected_action": "Read when convenient.",
    },
    {
        "id": "E-1014",
        "received": "2026-07-24 12:07",
        "from_name": "Dana Walsh",
        "from_email": "dana@meridianhospital.org",
        "role": "Customer executive",
        "subject": "Board packet screenshot request",
        "body": "The board packet is due Monday. Can you send a clean screenshot of the audit trail view and one paragraph explaining how replies are approved before sending?",
        "category": "Customer",
        "priority": 83,
        "urgency": "high",
        "deadline": "Monday",
        "needs_response": True,
        "unread": True,
        "tags": ["customer", "board", "audit trail"],
        "expected_action": "Send screenshot and approval workflow explanation.",
    },
    {
        "id": "E-1015",
        "received": "2026-07-24 12:22",
        "from_name": "Marcus Reed",
        "from_email": "marcus@company.com",
        "role": "Sales lead",
        "subject": "Renewal negotiation notes for Acme",
        "body": "Acme wants a 12 percent discount and a quarterly business review. I think we can hold at 8 percent if we include implementation credits. Can you approve the position?",
        "category": "Sales",
        "priority": 81,
        "urgency": "medium",
        "deadline": "Today",
        "needs_response": True,
        "unread": False,
        "tags": ["sales", "renewal", "discount"],
        "expected_action": "Approve negotiation guardrails.",
    },
    {
        "id": "E-1016",
        "received": "2026-07-24 12:41",
        "from_name": "Cloud Billing",
        "from_email": "billing@cloudscale.example",
        "role": "Vendor",
        "subject": "Compute spend anomaly: 38 percent above forecast",
        "body": "Your July projected compute spend is 38 percent above forecast. Largest change is browser automation workers in us-west. Review recommended before the next billing cycle.",
        "category": "Finance",
        "priority": 79,
        "urgency": "medium",
        "deadline": "This week",
        "needs_response": False,
        "unread": True,
        "tags": ["billing", "cloud", "cost"],
        "expected_action": "Ask engineering to investigate worker spend.",
    },
    {
        "id": "E-1017",
        "received": "2026-07-24 13:03",
        "from_name": "Hannah Kim",
        "from_email": "hannah@company.com",
        "role": "People ops",
        "subject": "Remote work policy clarification",
        "body": "Two employees asked whether the September onsite is mandatory. Can you confirm the language before I send the policy update?",
        "category": "People",
        "priority": 58,
        "urgency": "low",
        "deadline": "Next week",
        "needs_response": True,
        "unread": False,
        "tags": ["people", "policy"],
        "expected_action": "Clarify onsite language.",
    },
    {
        "id": "E-1018",
        "received": "2026-07-24 13:18",
        "from_name": "Victor Zhao",
        "from_email": "victor@company.com",
        "role": "Support lead",
        "subject": "Escalation: shared inbox import stuck for three accounts",
        "body": "Three customer accounts are stuck importing Outlook shared inboxes. Support has a manual workaround but needs product approval to send it because it requires re-authentication.",
        "category": "Support",
        "priority": 85,
        "urgency": "high",
        "deadline": "Today",
        "needs_response": True,
        "unread": True,
        "tags": ["support", "outlook", "shared inbox", "customer"],
        "expected_action": "Approve support workaround or give safer alternative.",
    },
    {
        "id": "E-1019",
        "received": "2026-07-24 13:42",
        "from_name": "Amara Okafor",
        "from_email": "amara@impactfund.org",
        "role": "Investor",
        "subject": "Intro to portfolio company with 2,400-seat helpdesk",
        "body": "I can introduce you to a portfolio company evaluating email automation for support. Send me a crisp two-sentence positioning blurb and the best proof point.",
        "category": "Investor",
        "priority": 76,
        "urgency": "medium",
        "deadline": "Today",
        "needs_response": True,
        "unread": True,
        "tags": ["investor", "intro", "sales"],
        "expected_action": "Send positioning blurb and proof point.",
    },
    {
        "id": "E-1020",
        "received": "2026-07-24 14:05",
        "from_name": "Calendar",
        "from_email": "calendar@company.com",
        "role": "System",
        "subject": "Reminder: board prep starts in 30 minutes",
        "body": "Board prep with Maya, Leo, and Priya starts at 2:35 PM. Agenda includes metrics, runway, enterprise pipeline, and support incidents.",
        "category": "Calendar",
        "priority": 67,
        "urgency": "medium",
        "deadline": "Today 2:35 PM",
        "needs_response": False,
        "unread": True,
        "tags": ["calendar", "board", "meeting"],
        "expected_action": "Prepare for meeting.",
    },
    {
        "id": "E-1021",
        "received": "2026-07-24 14:19",
        "from_name": "Kelsey Moore",
        "from_email": "kelsey@company.com",
        "role": "Marketing",
        "subject": "Launch copy approval",
        "body": "The homepage copy now says 'autonomous email agent.' Legal suggested 'review-first email assistant' until we have more customer proof. Which positioning do you prefer?",
        "category": "Marketing",
        "priority": 69,
        "urgency": "medium",
        "deadline": "Tomorrow",
        "needs_response": True,
        "unread": False,
        "tags": ["marketing", "positioning", "legal"],
        "expected_action": "Choose safer launch positioning.",
    },
    {
        "id": "E-1022",
        "received": "2026-07-24 14:36",
        "from_name": "Samir Desai",
        "from_email": "samir@company.com",
        "role": "Infrastructure",
        "subject": "Browser worker pool near limit",
        "body": "The public demo is close to the worker pool limit. If traffic spikes, new runs will queue. I recommend lowering concurrent long-running web tasks or moving demos to replay mode.",
        "category": "Engineering",
        "priority": 82,
        "urgency": "high",
        "deadline": "Today",
        "needs_response": True,
        "unread": True,
        "tags": ["infrastructure", "demo", "cost", "browser"],
        "expected_action": "Approve queue limits or replay mode for demos.",
    },
    {
        "id": "E-1023",
        "received": "2026-07-24 15:02",
        "from_name": "Monica Evans",
        "from_email": "monica@summitbank.com",
        "role": "Enterprise legal",
        "subject": "Data retention clause question",
        "body": "Can your team commit to deleting processed email content within 30 days after termination? Our legal team needs a yes/no answer before continuing contract review.",
        "category": "Legal",
        "priority": 90,
        "urgency": "critical",
        "deadline": "Today",
        "needs_response": True,
        "unread": True,
        "tags": ["legal", "enterprise", "data retention"],
        "expected_action": "Coordinate with counsel and answer retention commitment.",
    },
    {
        "id": "E-1024",
        "received": "2026-07-24 15:17",
        "from_name": "Andre Brooks",
        "from_email": "andre@northwind.com",
        "role": "Customer VP",
        "subject": "Concern about rollout timeline",
        "body": "We are worried the rollout is slipping. If the Outlook shared mailbox issue is not resolved this week, we will pause expansion discussions until Q4.",
        "category": "Customer",
        "priority": 93,
        "urgency": "critical",
        "deadline": "This week",
        "needs_response": True,
        "unread": True,
        "tags": ["customer", "churn", "outlook", "expansion"],
        "expected_action": "Respond with remediation plan and executive reassurance.",
    },
    {
        "id": "E-1025",
        "received": "2026-07-24 15:31",
        "from_name": "Lina Hart",
        "from_email": "lina@designpartners.io",
        "role": "Design partner",
        "subject": "Feature request: approval rules by sender domain",
        "body": "The beta is useful, but we need approval rules by sender domain before we can invite the whole team. Happy to jump on a call next week.",
        "category": "Product",
        "priority": 64,
        "urgency": "low",
        "deadline": "Next week",
        "needs_response": True,
        "unread": True,
        "tags": ["product", "feature request", "beta"],
        "expected_action": "Acknowledge request and schedule product call.",
    },
    {
        "id": "E-1026",
        "received": "2026-07-24 15:49",
        "from_name": "Tax Notices",
        "from_email": "notices@tax.example",
        "role": "Government notice",
        "subject": "Quarterly filing confirmation",
        "body": "Your quarterly filing was accepted. No payment is due. Keep this confirmation for records.",
        "category": "Finance",
        "priority": 40,
        "urgency": "low",
        "deadline": "",
        "needs_response": False,
        "unread": True,
        "tags": ["tax", "finance", "records"],
        "expected_action": "Archive for records.",
    },
    {
        "id": "E-1027",
        "received": "2026-07-24 16:03",
        "from_name": "Carla Ruiz",
        "from_email": "carla@company.com",
        "role": "Operations",
        "subject": "Office lease renewal option",
        "body": "The landlord needs notice by August 1 if we want to renew the office lease. Current utilization is low, but the onsite plan may change the math.",
        "category": "Operations",
        "priority": 52,
        "urgency": "low",
        "deadline": "August 1",
        "needs_response": True,
        "unread": False,
        "tags": ["operations", "office", "lease"],
        "expected_action": "Schedule decision before August 1.",
    },
    {
        "id": "E-1028",
        "received": "2026-07-24 16:21",
        "from_name": "Yuki Tan",
        "from_email": "yuki@company.com",
        "role": "Partnerships",
        "subject": "Co-marketing draft with CloudScale",
        "body": "CloudScale sent a co-marketing draft. The only risky claim is 'cuts email handling by 80 percent.' We can support 42 percent from beta data. Can you approve edits?",
        "category": "Marketing",
        "priority": 62,
        "urgency": "low",
        "deadline": "Monday",
        "needs_response": True,
        "unread": True,
        "tags": ["marketing", "partnership", "claims"],
        "expected_action": "Approve safer quantified claim.",
    },
    {
        "id": "E-1029",
        "received": "2026-07-24 16:37",
        "from_name": "Mina Sato",
        "from_email": "mina@example.com",
        "role": "Candidate",
        "subject": "Thank you for the design interview",
        "body": "I enjoyed meeting the team. The product problem is exactly the kind of workflow complexity I like. Let me know if there is anything else I can provide.",
        "category": "Recruiting",
        "priority": 49,
        "urgency": "low",
        "deadline": "",
        "needs_response": True,
        "unread": False,
        "tags": ["hiring", "candidate", "design"],
        "expected_action": "Send warm acknowledgement or route through recruiting.",
    },
    {
        "id": "E-1030",
        "received": "2026-07-24 16:54",
        "from_name": "No Reply",
        "from_email": "noreply@saasmetrics.example",
        "role": "System",
        "subject": "Daily SaaS metrics digest",
        "body": "MRR is up 1.8 percent week over week. Trial conversion is flat. Support response time improved to 2.1 hours.",
        "category": "Analytics",
        "priority": 46,
        "urgency": "low",
        "deadline": "",
        "needs_response": False,
        "unread": True,
        "tags": ["analytics", "mrr", "digest"],
        "expected_action": "Read later.",
    },
]


def inbox_snapshot() -> dict[str, Any]:
    stats = {
        "total": len(SYNTHETIC_INBOX),
        "unread": sum(1 for email in SYNTHETIC_INBOX if email["unread"]),
        "needs_response": sum(1 for email in SYNTHETIC_INBOX if email["needs_response"]),
        "critical": sum(1 for email in SYNTHETIC_INBOX if email["urgency"] == "critical"),
        "today": sum(1 for email in SYNTHETIC_INBOX if "Today" in str(email.get("deadline", ""))),
    }
    categories = sorted({email["category"] for email in SYNTHETIC_INBOX})
    prompts = [
        "Summarize the most important emails I need to respond to today.",
        "Draft replies to the 5 highest priority emails.",
        "Find customer and sales risks that could affect revenue this week.",
        "Which emails can I safely ignore or archive?",
        "Create an action plan for legal, finance, and security emails.",
    ]
    return {"emails": SYNTHETIC_INBOX, "stats": stats, "categories": categories, "suggested_prompts": prompts}


async def run_inbox_comparison(prompt: str) -> dict[str, Any]:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ValueError("Prompt is required.")
    intent = analyze_prompt(clean_prompt)
    truth = select_emails(clean_prompt, intent, agent_id="evaluator")
    started = time.perf_counter()
    results = await asyncio.gather(*(run_agent(agent_id, clean_prompt, intent, truth) for agent_id in AGENTS))
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "prompt": clean_prompt,
        "intent": intent,
        "truth": [email_summary(email) for email in truth],
        "results": results,
        "elapsed_ms": elapsed_ms,
        "winner": {
            "fastest": min(results, key=lambda row: row["runtime_ms"])["agent_id"],
            "lowest_cost": min(results, key=lambda row: row["cost_usd"])["agent_id"],
            "highest_effectiveness": max(results, key=lambda row: row["effectiveness"])["agent_id"],
        },
    }


async def run_agent(agent_id: str, prompt: str, intent: dict[str, Any], truth: list[dict[str, Any]]) -> dict[str, Any]:
    profile = AGENTS[agent_id]
    start = time.perf_counter()
    selected = select_emails(prompt, intent, agent_id=agent_id)
    await asyncio.sleep((profile["speed_ms"] + len(selected) * 48) / 1000)
    answer = compose_answer(agent_id, prompt, intent, selected)
    drafts = compose_drafts(agent_id, selected, intent)
    tokens = estimate_tokens(agent_id, prompt, selected, answer, drafts)
    runtime_ms = int((time.perf_counter() - start) * 1000)
    effectiveness = evaluate_effectiveness(agent_id, selected, truth, drafts, intent)
    return {
        "agent_id": agent_id,
        "label": profile["label"],
        "model": profile["model"],
        "runtime_ms": runtime_ms,
        "tokens": tokens,
        "cost_usd": round((tokens / 1000) * profile["cost_per_1k"], 4),
        "effectiveness": effectiveness,
        "answer": answer,
        "selected_emails": [email_summary(email) for email in selected],
        "drafts": drafts,
        "actions": action_trace(agent_id, selected, intent),
    }


def analyze_prompt(prompt: str) -> dict[str, Any]:
    text = prompt.lower()
    number_match = re.search(r"\b(\d{1,2})\b", text)
    count = int(number_match.group(1)) if number_match else 5
    wants_reply = any(term in text for term in ["respond", "reply", "draft", "answer", "send"])
    wants_archive = any(term in text for term in ["archive", "ignore", "low priority", "safe to ignore"])
    wants_summary = any(term in text for term in ["summarize", "summary", "brief", "important", "prioritize"])
    categories = [category for category in sorted({email["category"].lower() for email in SYNTHETIC_INBOX}) if category.lower() in text]
    if "customer" in text and "Customer" not in categories:
        categories.append("customer")
    if "sales" in text and "Sales" not in categories:
        categories.append("sales")
    if "investor" in text and "Investor" not in categories:
        categories.append("investor")
    return {
        "count": max(1, min(count, 12)),
        "wants_reply": wants_reply,
        "wants_archive": wants_archive,
        "wants_summary": wants_summary or not wants_reply,
        "categories": sorted(set(categories)),
        "deadline_focus": any(term in text for term in ["today", "deadline", "urgent", "important", "critical"]),
        "revenue_focus": any(term in text for term in ["revenue", "sales", "customer", "churn", "renewal", "pilot", "deal"]),
    }


def select_emails(prompt: str, intent: dict[str, Any], agent_id: str) -> list[dict[str, Any]]:
    scored = [(score_email(email, prompt, intent), email) for email in SYNTHETIC_INBOX]
    if intent["wants_archive"]:
        scored = [(archive_score(email, prompt), email) for email in SYNTHETIC_INBOX]
    scored.sort(key=lambda item: item[0], reverse=True)
    profile = AGENTS.get(agent_id, {"coverage_bias": 0})
    count = intent["count"]
    if agent_id == "cascade" and not intent["wants_archive"]:
        count = max(3, count + int(profile["coverage_bias"]))
    elif agent_id in {"openai", "claude"} and not intent["wants_archive"]:
        count = min(10, count + int(profile["coverage_bias"]))
    elif agent_id == "evaluator":
        count = intent["count"]
    return [email for score, email in scored if score > 0][:count]


def score_email(email: dict[str, Any], prompt: str, intent: dict[str, Any]) -> float:
    text = " ".join(
        [
            email["subject"],
            email["body"],
            email["from_name"],
            email["role"],
            email["category"],
            " ".join(email["tags"]),
        ]
    ).lower()
    prompt_terms = [term for term in re.findall(r"[a-zA-Z]{4,}", prompt.lower()) if term not in STOPWORDS]
    score = float(email["priority"])
    if email["needs_response"]:
        score += 18
    if email["urgency"] == "critical":
        score += 16
    elif email["urgency"] == "high":
        score += 9
    if intent["deadline_focus"] and email.get("deadline"):
        score += 10
    if intent["revenue_focus"] and any(tag in email["tags"] for tag in ["revenue", "sales", "customer", "churn", "renewal", "pilot"]):
        score += 18
    if intent["categories"] and email["category"].lower() in intent["categories"]:
        score += 22
    if intent["wants_reply"] and email["needs_response"]:
        score += 24
    score += sum(8 for term in prompt_terms if term in text)
    if intent["categories"] and email["category"].lower() not in intent["categories"]:
        score -= 35
    if intent["wants_reply"] and not email["needs_response"]:
        score -= 28
    return score


def archive_score(email: dict[str, Any], prompt: str) -> float:
    score = 100 - float(email["priority"])
    if not email["needs_response"]:
        score += 25
    if email["urgency"] == "low":
        score += 15
    if email["unread"]:
        score += 4
    return score


def compose_answer(agent_id: str, prompt: str, intent: dict[str, Any], selected: list[dict[str, Any]]) -> str:
    lead = {
        "cascade": "I prioritized the inbox with local triage first, then used fallback wording where a reply needed nuance.",
        "openai": "I reviewed the inbox broadly and ranked messages by urgency, business impact, and response need.",
        "claude": "I grouped the inbox by consequence and drafted responses with context, tone, and owner handoff in mind.",
    }[agent_id]
    if intent["wants_archive"]:
        bullets = [f"{email['from_name']} - {email['subject']}: low action pressure; {email['expected_action']}" for email in selected]
    else:
        bullets = [
            f"{email['from_name']} - {email['subject']}: {email['expected_action']} Deadline: {email['deadline'] or 'none'}."
            for email in selected
        ]
    return lead + "\n" + "\n".join(f"- {bullet}" for bullet in bullets)


def compose_drafts(agent_id: str, selected: list[dict[str, Any]], intent: dict[str, Any]) -> list[dict[str, str]]:
    if not intent["wants_reply"]:
        return []
    drafts = []
    max_drafts = intent["count"]
    for email in [item for item in selected if item["needs_response"]][:max_drafts]:
        if agent_id == "cascade":
            body = f"Hi {first_name(email['from_name'])}, thanks for the note. I am on this and will follow up with {email['expected_action'].lower()} Please treat this as acknowledged while I confirm the final details."
        elif agent_id == "openai":
            body = f"Hi {first_name(email['from_name'])}, thanks for flagging this. I will take the next step now: {email['expected_action']} I will send the relevant materials or decision shortly and keep the timeline in mind."
        else:
            body = f"Hi {first_name(email['from_name'])}, thank you for the context. I agree this needs a timely response. My next step is to {email['expected_action'].lower()} I will make sure the reply is clear, concrete, and aligned with the deadline."
        drafts.append({"to": email["from_email"], "subject": "Re: " + email["subject"], "body": body})
    return drafts


def action_trace(agent_id: str, selected: list[dict[str, Any]], intent: dict[str, Any]) -> list[dict[str, Any]]:
    profile = AGENTS[agent_id]
    actions = []
    for index, label in enumerate(profile["route"], start=1):
        route = "slm" if label.startswith("SLM") else "llm"
        actions.append(
            {
                "step": index,
                "route": route,
                "label": label,
                "detail": trace_detail(index, selected, intent),
            }
        )
    return actions


def trace_detail(index: int, selected: list[dict[str, Any]], intent: dict[str, Any]) -> str:
    if index == 1:
        return f"Scanned {len(SYNTHETIC_INBOX)} messages and extracted urgency, sender role, tags, and deadlines."
    if index == 2:
        return f"Ranked {len(selected)} selected messages against the user prompt."
    if index == 3:
        return "Generated summaries" + (" and draft replies." if intent["wants_reply"] else ".")
    return "Checked output for missed urgent items and duplicate drafts."


def evaluate_effectiveness(
    agent_id: str,
    selected: list[dict[str, Any]],
    truth: list[dict[str, Any]],
    drafts: list[dict[str, str]],
    intent: dict[str, Any],
) -> int:
    selected_ids = {email["id"] for email in selected}
    truth_ids = {email["id"] for email in truth}
    if not truth_ids:
        return 80
    coverage = len(selected_ids & truth_ids) / len(truth_ids)
    precision = len(selected_ids & truth_ids) / max(1, len(selected_ids))
    draft_score = 1.0 if not intent["wants_reply"] else min(1.0, len(drafts) / max(1, min(intent["count"], len([email for email in truth if email["needs_response"]]))))
    quality = AGENTS.get(agent_id, {}).get("draft_quality", 0.85)
    score = (coverage * 0.58 + precision * 0.27 + draft_score * 0.15) * quality * 100
    return max(1, min(99, round(score)))


def estimate_tokens(
    agent_id: str,
    prompt: str,
    selected: list[dict[str, Any]],
    answer: str,
    drafts: list[dict[str, str]],
) -> int:
    profile = AGENTS[agent_id]
    inbox_words = sum(len((email["subject"] + " " + email["body"] + " " + email["expected_action"]).split()) for email in selected)
    output_words = len(answer.split()) + sum(len(draft["body"].split()) for draft in drafts)
    base = len(prompt.split()) * 4 + inbox_words * 2.5 + output_words * 2.2 + 580
    if agent_id != "cascade":
        base += len(SYNTHETIC_INBOX) * 42
    else:
        base += len(selected) * 36
    return int(base * profile["token_scale"])


def email_summary(email: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": email["id"],
        "from_name": email["from_name"],
        "from_email": email["from_email"],
        "role": email["role"],
        "subject": email["subject"],
        "category": email["category"],
        "priority": email["priority"],
        "urgency": email["urgency"],
        "deadline": email["deadline"],
        "needs_response": email["needs_response"],
        "tags": email["tags"],
        "expected_action": email["expected_action"],
    }


def first_name(name: str) -> str:
    return str(name).split()[0]


STOPWORDS = {
    "about",
    "after",
    "before",
    "could",
    "draft",
    "email",
    "emails",
    "important",
    "inbox",
    "need",
    "needs",
    "please",
    "reply",
    "respond",
    "safe",
    "summarize",
    "summary",
    "that",
    "this",
    "today",
    "what",
    "which",
    "with",
}
