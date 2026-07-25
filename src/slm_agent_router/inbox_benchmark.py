from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any


AGENTS: dict[str, dict[str, Any]] = {
    "cascade": {
        "label": "SLM Cascade",
        "model": os.getenv("OLLAMA_MODEL", "llama3.2:1b"),
        "route": ["Local retrieval", "Ollama SLM call", "Validate answer", "Retry or fallback if needed"],
    },
    "openai": {
        "label": "OpenAI Agent",
        "model": os.getenv("OPENAI_MODEL", "gpt-5.6-sol"),
        "route": ["Send inbox to OpenAI", "Receive structured answer", "Validate answer", "Prepare actions"],
    },
    "claude": {
        "label": "Claude Agent",
        "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
        "route": ["Send inbox to Claude", "Receive structured answer", "Validate answer", "Prepare actions"],
    },
}


INBOX_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "selected_email_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Email ids from the supplied mailbox that directly support the answer.",
        },
        "answer": {
            "type": "string",
            "description": "A concise but complete visible answer to the user's prompt, grounded only in the supplied emails.",
        },
        "drafts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        },
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["summarize", "draft_reply", "archive", "mark_read", "star", "flag"],
                    },
                    "email_id": {"type": "string"},
                    "label": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["type", "email_id", "label", "reason"],
            },
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Your confidence that the selected emails and answer fully satisfy the user's request.",
        },
    },
    "required": ["selected_email_ids", "answer", "drafts", "operations", "confidence"],
}


INBOX_SYSTEM_PROMPT = """You are an inbox-management benchmark agent.
You receive a synthetic email inbox and a user request. Do the task exactly.

Rules:
- Return only JSON matching the inbox_result schema.
- Use only the emails supplied in the prompt. Do not invent senders, facts, deadlines, or actions.
- selected_email_ids must contain every email that materially supports the answer.
- If the user asks what a person said, answer from that sender's actual message body.
- If the user asks for drafts, create realistic draft replies in drafts.
- If the user asks to archive, include archive operations for safe candidates.
- The answer field must be the user-visible output, not a note that an agent ran.
- confidence must be between 0 and 1. Use lower confidence when the prompt target is ambiguous, selected emails may be incomplete, or the answer is thin.
- Be concise, but include enough content for a person to act on the email."""


@dataclass
class InboxProviderOutput:
    provider: str
    model: str
    selected_email_ids: list[str]
    answer: str
    drafts: list[dict[str, str]]
    operations: list[dict[str, Any]]
    raw: str
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    confidence: float = 0.0
    cost_usd: float | None = None
    route_events: list[dict[str, Any]] = field(default_factory=list)
    messages_sent_to_model: int | None = None


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


async def run_inbox_comparison(
    prompt: str,
    providers: dict[str, "InboxProvider"] | None = None,
    provider_keys: dict[str, str] | None = None,
    allow_server_keys: bool = True,
) -> dict[str, Any]:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ValueError("Prompt is required.")
    intent = analyze_prompt(clean_prompt)
    matched = select_emails(clean_prompt, intent, agent_id="evaluator")
    active_providers = providers or build_inbox_providers(provider_keys, allow_server_keys=allow_server_keys)
    started = time.perf_counter()
    results = await asyncio.gather(
        *(run_agent(agent_id, clean_prompt, intent, matched, active_providers.get(agent_id)) for agent_id in AGENTS)
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "prompt": clean_prompt,
        "intent": intent,
        "matched_emails": [email_summary(email) for email in matched],
        "results": results,
        "elapsed_ms": elapsed_ms,
        "summary": run_summary(results, matched),
    }


async def run_agent(
    agent_id: str,
    prompt: str,
    intent: dict[str, Any],
    matched: list[dict[str, Any]],
    provider: "InboxProvider | None",
) -> dict[str, Any]:
    profile = AGENTS[agent_id]
    start = time.perf_counter()
    model_context = inbox_context_for_agent(prompt, intent, agent_id)
    output = await call_inbox_provider(provider, agent_id, prompt, intent, model_context)
    selected = selected_from_provider_output(output)
    if not selected and output.answer:
        selected = infer_selected_from_answer(output.answer)
    drafts = sanitize_drafts(output.drafts) if intent["wants_reply"] else []
    operations = sanitize_operations(output.operations, selected, intent) or mailbox_operations(selected, intent)
    answer = output.answer.strip()
    completion = (
        provider_error_completion(output.error)
        if output.error
        else evaluate_completion(selected, matched, drafts, intent, answer)
    )
    runtime_ms = round((time.perf_counter() - start) * 1000, 2)
    input_tokens = output.input_tokens or estimate_text_tokens(build_inbox_prompt(prompt, intent, model_context))
    output_tokens = output.output_tokens or estimate_text_tokens(answer + " " + " ".join(draft["body"] for draft in drafts))
    tokens = input_tokens + output_tokens
    cost_usd = output.cost_usd
    if cost_usd is None:
        cost_usd = estimate_provider_cost_usd(agent_id, output.model, input_tokens, output_tokens)
    return {
        "agent_id": agent_id,
        "label": profile["label"],
        "provider": output.provider,
        "model": output.model or profile["model"],
        "runtime_ms": runtime_ms,
        "status": completion["state"],
        "completion": completion,
        "answer": answer,
        "selected_emails": [email_summary(email) for email in selected],
        "drafts": drafts,
        "operations": operations,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens": tokens,
        "cost_usd": round(cost_usd, 6),
        "confidence": round(float(output.confidence or 0), 3),
        "raw_response": output.raw[:1200],
        "work": {
            "messages_scanned": len(SYNTHETIC_INBOX),
            "messages_sent_to_model": output.messages_sent_to_model
            if output.messages_sent_to_model is not None
            else len(model_context),
            "messages_matched": len(selected),
            "drafts_created": len(drafts),
            "actions_prepared": len(operations),
        },
        "actions": action_trace(agent_id, selected, intent, output),
    }


class InboxProvider:
    provider = "provider"
    model = "unknown"

    async def complete(
        self,
        prompt: str,
        intent: dict[str, Any],
        emails: list[dict[str, Any]],
    ) -> InboxProviderOutput:
        raise NotImplementedError


class OpenAIInboxProvider(InboxProvider):
    provider = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 90,
    ):
        self.api_key = api_key
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.6-sol")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout_s = timeout_s

    async def complete(
        self,
        prompt: str,
        intent: dict[str, Any],
        emails: list[dict[str, Any]],
    ) -> InboxProviderOutput:
        if not self.api_key:
            return unavailable_output("openai", self.model, "Set OPENAI_API_KEY to run the OpenAI inbox agent.")

        import httpx

        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": INBOX_SYSTEM_PROMPT},
                {"role": "user", "content": build_inbox_prompt(prompt, intent, emails)},
            ],
            "max_output_tokens": int(os.getenv("INBOX_OPENAI_MAX_OUTPUT_TOKENS", "1600")),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "inbox_result",
                    "strict": True,
                    "schema": INBOX_RESULT_SCHEMA,
                }
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(f"{self.base_url}/responses", headers=headers, json=payload)
            if response.status_code >= 400:
                return unavailable_output("openai", self.model, response_error("OpenAI", response))
            data = response.json()
            raw = extract_openai_text(data)
            parsed = parse_model_json(raw)
            input_tokens, output_tokens = extract_openai_usage(data)
            return provider_output_from_payload("openai", self.model, parsed, raw, input_tokens, output_tokens)
        except Exception as exc:
            return unavailable_output("openai", self.model, f"OpenAI API call failed: {safe_error(exc)}")


class AnthropicInboxProvider(InboxProvider):
    provider = "claude"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 90,
    ):
        self.api_key = api_key
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
        self.base_url = (base_url or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")).rstrip("/")
        self.timeout_s = timeout_s

    async def complete(
        self,
        prompt: str,
        intent: dict[str, Any],
        emails: list[dict[str, Any]],
    ) -> InboxProviderOutput:
        if not self.api_key:
            return unavailable_output("claude", self.model, "Set ANTHROPIC_API_KEY to run the Claude inbox agent.")

        import httpx

        payload = {
            "model": self.model,
            "max_tokens": int(os.getenv("INBOX_ANTHROPIC_MAX_TOKENS", "1600")),
            "system": INBOX_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": build_inbox_prompt(prompt, intent, emails)}],
            "tools": [
                {
                    "name": "inbox_result",
                    "description": "Return the completed inbox task result.",
                    "input_schema": INBOX_RESULT_SCHEMA,
                }
            ],
            "tool_choice": {"type": "tool", "name": "inbox_result"},
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(f"{self.base_url}/messages", headers=headers, json=payload)
            if response.status_code >= 400:
                return unavailable_output("claude", self.model, response_error("Claude", response))
            data = response.json()
            parsed, raw = extract_anthropic_inbox_payload(data)
            input_tokens, output_tokens = extract_anthropic_usage(data)
            return provider_output_from_payload("claude", self.model, parsed, raw, input_tokens, output_tokens)
        except Exception as exc:
            return unavailable_output("claude", self.model, f"Claude API call failed: {safe_error(exc)}")


class OllamaInboxProvider(InboxProvider):
    provider = "ollama"

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 60,
    ):
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2:1b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout_s = timeout_s

    async def complete(
        self,
        prompt: str,
        intent: dict[str, Any],
        emails: list[dict[str, Any]],
    ) -> InboxProviderOutput:
        import httpx

        payload = {
            "model": self.model,
            "stream": False,
            "format": INBOX_RESULT_SCHEMA,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": INBOX_SYSTEM_PROMPT},
                {"role": "user", "content": build_inbox_prompt(prompt, intent, emails)},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
            if response.status_code >= 400:
                return unavailable_output("ollama", self.model, response_error("Ollama", response))
            data = response.json()
            raw = data.get("message", {}).get("content", "")
            parsed = parse_model_json(raw)
            input_tokens = int(data.get("prompt_eval_count") or 0)
            output_tokens = int(data.get("eval_count") or 0)
            return provider_output_from_payload("ollama", self.model, parsed, raw, input_tokens, output_tokens)
        except Exception as exc:
            return unavailable_output("ollama", self.model, f"Ollama call failed: {safe_error(exc)}")


class InboxCascadeProvider(InboxProvider):
    provider = "cascade"

    def __init__(
        self,
        local_provider: InboxProvider,
        fallback_providers: list[InboxProvider],
        confidence_threshold: float | None = None,
        fallback_confidence_threshold: float | None = None,
        max_local_retries: int | None = None,
    ):
        self.local_provider = local_provider
        self.fallback_providers = fallback_providers
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else float(os.getenv("INBOX_CASCADE_CONFIDENCE_THRESHOLD", "0.72"))
        )
        self.fallback_confidence_threshold = (
            fallback_confidence_threshold
            if fallback_confidence_threshold is not None
            else float(os.getenv("INBOX_CASCADE_FALLBACK_CONFIDENCE_THRESHOLD", "0.62"))
        )
        self.max_local_retries = (
            max_local_retries
            if max_local_retries is not None
            else int(os.getenv("INBOX_CASCADE_MAX_LOCAL_RETRIES", "1"))
        )
        self.model = self.local_provider.model

    async def complete(
        self,
        prompt: str,
        intent: dict[str, Any],
        emails: list[dict[str, Any]],
    ) -> InboxProviderOutput:
        route_events: list[dict[str, Any]] = []
        matched = select_emails(prompt, intent, agent_id="evaluator")
        local_context = emails or inbox_context_for_agent(prompt, intent, "cascade")
        total_input_tokens = 0
        total_output_tokens = 0
        total_messages_sent = 0
        fallback_cost = 0.0
        best_output: InboxProviderOutput | None = None
        best_validation: dict[str, Any] | None = None

        retrieval_confidence = local_retrieval_confidence(local_context, matched, intent)
        route_events.append(
            route_event(
                "slm",
                "Local retrieval",
                f"Scored {len(SYNTHETIC_INBOX)} messages and sent top {len(local_context)} to Ollama.",
                confidence=retrieval_confidence,
                messages=len(local_context),
            )
        )

        attempts = max(0, self.max_local_retries) + 1
        for attempt_index in range(attempts):
            attempt_started = time.perf_counter()
            attempt_prompt = prompt
            if best_validation:
                attempt_prompt = retry_prompt(prompt, best_validation)
            output = await self.local_provider.complete(attempt_prompt, intent, local_context)
            output.confidence = output.confidence or inferred_output_confidence(output, prompt, intent, matched)
            total_input_tokens += output.input_tokens
            total_output_tokens += output.output_tokens
            total_messages_sent += len(local_context)
            route_events.append(
                route_event(
                    "slm",
                    f"Ollama attempt {attempt_index + 1}",
                    model_call_detail(output),
                    confidence=output.confidence,
                    latency_ms=duration_ms(attempt_started),
                    tokens=output.input_tokens + output.output_tokens,
                )
            )

            validation = validate_cascade_attempt(output, prompt, intent, matched, self.confidence_threshold)
            route_events.append(
                route_event(
                    "validator",
                    "Validate local answer",
                    validation_detail(validation),
                    confidence=validation["confidence"],
                )
            )
            if is_better_validation(validation, best_validation):
                best_output = output
                best_validation = validation
            if validation["accepted"]:
                return cascade_output(
                    output,
                    model=f"ollama:{output.model}",
                    route_events=route_events,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    cost_usd=0.0,
                    messages_sent_to_model=total_messages_sent,
                )
            if attempt_index + 1 < attempts:
                previous_count = len(local_context)
                local_context = expanded_inbox_context(prompt, intent, local_context)
                route_events.append(
                    route_event(
                        "slm",
                        "Retry/replan",
                        "Broadened local context from "
                        f"{previous_count} to {len(local_context)} messages after {failure_summary(validation)}.",
                        confidence=max(0.1, validation["confidence"] - 0.08),
                        messages=len(local_context),
                    )
                )

        fallback_result = await self.complete_with_fallback(
            prompt,
            intent,
            matched,
            route_events,
            total_messages_sent,
        )
        if fallback_result:
            output, fallback_input, fallback_output, fallback_cost, fallback_messages = fallback_result
            total_input_tokens += fallback_input
            total_output_tokens += fallback_output
            total_messages_sent += fallback_messages
            return cascade_output(
                output,
                model=f"ollama:{self.local_provider.model} -> {output.provider}:{output.model}",
                route_events=route_events,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_usd=fallback_cost,
                messages_sent_to_model=total_messages_sent,
            )

        if best_output:
            route_events.append(
                route_event(
                    "unavailable",
                    "Fallback unavailable",
                    "No configured cloud fallback accepted the handoff; showing the best local result for review.",
                    confidence=best_validation["confidence"] if best_validation else best_output.confidence,
                )
            )
            return cascade_output(
                best_output,
                model=f"ollama:{best_output.model}",
                route_events=route_events,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_usd=fallback_cost,
                messages_sent_to_model=total_messages_sent,
            )

        unavailable = unavailable_output("cascade", self.local_provider.model, "The cascade could not produce a local or fallback answer.")
        unavailable.route_events = route_events
        unavailable.messages_sent_to_model = total_messages_sent
        return unavailable

    async def complete_with_fallback(
        self,
        prompt: str,
        intent: dict[str, Any],
        matched: list[dict[str, Any]],
        route_events: list[dict[str, Any]],
        messages_sent_before_fallback: int,
    ) -> tuple[InboxProviderOutput, int, int, float, int] | None:
        del messages_sent_before_fallback
        for provider in self.fallback_providers:
            fallback_started = time.perf_counter()
            output = await provider.complete(prompt, intent, SYNTHETIC_INBOX)
            output.confidence = output.confidence or inferred_output_confidence(output, prompt, intent, matched)
            fallback_tokens = output.input_tokens + output.output_tokens
            route_kind = "llm" if not output.error else "unavailable"
            route_events.append(
                route_event(
                    route_kind,
                    f"{provider.provider.title()} fallback",
                    model_call_detail(output),
                    confidence=output.confidence,
                    latency_ms=duration_ms(fallback_started),
                    tokens=fallback_tokens,
                    messages=len(SYNTHETIC_INBOX),
                )
            )
            if output.error:
                continue
            validation = validate_cascade_attempt(
                output,
                prompt,
                intent,
                matched,
                self.fallback_confidence_threshold,
            )
            route_events.append(
                route_event(
                    "validator",
                    "Validate fallback answer",
                    validation_detail(validation),
                    confidence=validation["confidence"],
                )
            )
            if validation["accepted"]:
                cost = estimate_provider_cost_usd(output.provider, output.model, output.input_tokens, output.output_tokens)
                return output, output.input_tokens, output.output_tokens, cost, len(SYNTHETIC_INBOX)
        return None


class DeterministicInboxProvider(InboxProvider):
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.provider = f"test-{agent_id}"
        self.model = "deterministic-test-provider"

    async def complete(
        self,
        prompt: str,
        intent: dict[str, Any],
        emails: list[dict[str, Any]],
    ) -> InboxProviderOutput:
        del emails
        selected = select_emails(prompt, intent, agent_id=self.agent_id)
        answer = compose_answer(self.agent_id, prompt, intent, selected)
        drafts = compose_drafts(self.agent_id, selected, intent)
        operations = mailbox_operations(selected, intent)
        return InboxProviderOutput(
            provider=self.provider,
            model=self.model,
            selected_email_ids=[email["id"] for email in selected],
            answer=answer,
            drafts=drafts,
            operations=operations,
            raw=json.dumps(
                {
                    "selected_email_ids": [email["id"] for email in selected],
                    "answer": answer,
                    "drafts": drafts,
                    "operations": operations,
                    "confidence": 0.95,
                }
            ),
            input_tokens=120,
            output_tokens=80,
            confidence=0.95,
        )


def route_event(
    route: str,
    label: str,
    detail: str,
    *,
    confidence: float | None = None,
    latency_ms: float | None = None,
    tokens: int | None = None,
    messages: int | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "route": route,
        "label": label,
        "detail": detail,
    }
    if confidence is not None:
        event["confidence"] = round(clamp_confidence(confidence), 3)
    if latency_ms is not None:
        event["latency_ms"] = round(float(latency_ms), 2)
    if tokens is not None:
        event["tokens"] = max(0, int(tokens))
    if messages is not None:
        event["messages"] = max(0, int(messages))
    return event


def duration_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def local_retrieval_confidence(
    local_context: list[dict[str, Any]],
    matched: list[dict[str, Any]],
    intent: dict[str, Any],
) -> float:
    if not local_context:
        return 0.1
    local_ids = {email["id"] for email in local_context}
    matched_ids = {email["id"] for email in matched}
    if matched_ids and matched_ids.issubset(local_ids):
        return 0.96 if intent.get("direct_lookup") or intent.get("targeted_lookup") else 0.9
    if matched_ids:
        return 0.52
    if intent.get("categories") or intent.get("deadline_focus") or intent.get("revenue_focus"):
        return 0.78
    return 0.68


def inferred_output_confidence(
    output: InboxProviderOutput,
    prompt: str,
    intent: dict[str, Any],
    matched: list[dict[str, Any]],
) -> float:
    validation = validate_cascade_attempt(output, prompt, intent, matched, confidence_threshold=0)
    return clamp_confidence(0.35 + 0.6 * validation["check_ratio"])


def validate_cascade_attempt(
    output: InboxProviderOutput,
    prompt: str,
    intent: dict[str, Any],
    matched: list[dict[str, Any]],
    confidence_threshold: float,
) -> dict[str, Any]:
    del prompt
    confidence = clamp_confidence(output.confidence)
    if output.error:
        return {
            "accepted": False,
            "confidence": confidence,
            "check_ratio": 0.0,
            "failed_reasons": ["provider_unavailable"],
            "completion": provider_error_completion(output.error),
            "selected_count": 0,
        }
    selected, drafts, _, answer = normalized_output_parts(output, intent)
    completion = evaluate_completion(selected, matched, drafts, intent, answer)
    total_checks = max(1, int(completion["total_checks"]))
    check_ratio = int(completion["passed_checks"]) / total_checks
    failed_reasons = [check["label"] for check in completion["checks"] if not check["passed"]]
    if confidence < confidence_threshold:
        failed_reasons.append(f"confidence below {confidence_threshold:.2f}")
    return {
        "accepted": completion["state"] == "complete" and confidence >= confidence_threshold,
        "confidence": confidence,
        "check_ratio": check_ratio,
        "failed_reasons": failed_reasons,
        "completion": completion,
        "selected_count": len(selected),
    }


def normalized_output_parts(
    output: InboxProviderOutput,
    intent: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, Any]], str]:
    selected = selected_from_provider_output(output)
    if not selected and output.answer:
        selected = infer_selected_from_answer(output.answer)
    drafts = sanitize_drafts(output.drafts) if intent["wants_reply"] else []
    operations = sanitize_operations(output.operations, selected, intent) or mailbox_operations(selected, intent)
    return selected, drafts, operations, output.answer.strip()


def is_better_validation(current: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    if previous is None:
        return True
    current_score = current["check_ratio"] + current["confidence"]
    previous_score = previous["check_ratio"] + previous["confidence"]
    return current_score > previous_score


def validation_detail(validation: dict[str, Any]) -> str:
    completion = validation["completion"]
    base = (
        f"{completion['passed_checks']}/{completion['total_checks']} checks passed; "
        f"confidence {validation['confidence']:.2f}."
    )
    if validation["accepted"]:
        return base + " Accepted."
    return base + f" Needs {failure_summary(validation)}."


def failure_summary(validation: dict[str, Any]) -> str:
    reasons = validation.get("failed_reasons") or ["review"]
    return ", ".join(str(reason) for reason in reasons[:3])


def retry_prompt(prompt: str, validation: dict[str, Any]) -> str:
    return (
        prompt
        + "\n\nRetry/replan instruction: the previous local answer did not pass validation because "
        + failure_summary(validation)
        + ". Re-check the supplied mailbox, cite the exact supporting email ids, produce a direct answer, "
        + "and set confidence only as high as the evidence allows."
    )


def expanded_inbox_context(
    prompt: str,
    intent: dict[str, Any],
    current_context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = [(score_email(email, prompt, intent), email) for email in SYNTHETIC_INBOX]
    if intent["wants_archive"]:
        candidates = [(archive_score(email, prompt), email) for email in SYNTHETIC_INBOX]
    candidates.sort(key=lambda item: item[0], reverse=True)
    current_count = len(current_context)
    target_count = max(
        current_count + 4,
        selection_count(intent),
        int(os.getenv("INBOX_OLLAMA_RETRY_CONTEXT_EMAILS", "14")),
    )
    return [email for score, email in candidates if score > 0][: min(target_count, len(SYNTHETIC_INBOX))]


def model_call_detail(output: InboxProviderOutput) -> str:
    if output.error:
        return output.error
    return f"Called {output.provider} model {output.model}."


def cascade_output(
    output: InboxProviderOutput,
    *,
    model: str,
    route_events: list[dict[str, Any]],
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    messages_sent_to_model: int,
) -> InboxProviderOutput:
    raw_payload = {
        "final_provider": output.provider,
        "final_model": output.model,
        "raw_response": output.raw,
        "route_events": route_events,
    }
    return InboxProviderOutput(
        provider="cascade",
        model=model,
        selected_email_ids=output.selected_email_ids,
        answer=output.answer,
        drafts=output.drafts,
        operations=output.operations,
        raw=json.dumps(raw_payload, ensure_ascii=True),
        input_tokens=max(0, int(input_tokens or 0)),
        output_tokens=max(0, int(output_tokens or 0)),
        error=output.error,
        confidence=clamp_confidence(output.confidence),
        cost_usd=cost_usd,
        route_events=route_events,
        messages_sent_to_model=messages_sent_to_model,
    )


def build_inbox_providers(
    provider_keys: dict[str, str] | None = None,
    allow_server_keys: bool = True,
) -> dict[str, InboxProvider]:
    provider_keys = provider_keys or {}
    openai_key = provider_keys.get("openai") or (os.getenv("OPENAI_API_KEY") if allow_server_keys else None)
    claude_key = provider_keys.get("claude") or (os.getenv("ANTHROPIC_API_KEY") if allow_server_keys else None)
    openai = OpenAIInboxProvider(api_key=openai_key)
    claude = AnthropicInboxProvider(api_key=claude_key)
    return {
        "cascade": InboxCascadeProvider(OllamaInboxProvider(), [openai, claude]),
        "openai": openai,
        "claude": claude,
    }


def deterministic_inbox_providers() -> dict[str, InboxProvider]:
    return {agent_id: DeterministicInboxProvider(agent_id) for agent_id in AGENTS}


async def call_inbox_provider(
    provider: InboxProvider | None,
    agent_id: str,
    prompt: str,
    intent: dict[str, Any],
    emails: list[dict[str, Any]],
) -> InboxProviderOutput:
    if provider is None:
        return unavailable_output(agent_id, AGENTS[agent_id]["model"], f"No provider configured for {agent_id}.")
    return await provider.complete(prompt, intent, emails)


def analyze_prompt(prompt: str) -> dict[str, Any]:
    text = prompt.lower()
    number_match = re.search(r"\b(\d{1,2})\b", text)
    count = int(number_match.group(1)) if number_match else 5
    wants_reply = any(term in text for term in ["respond", "reply", "draft", "answer", "send"])
    wants_archive = any(term in text for term in ["archive", "ignore", "low priority", "safe to ignore"])
    wants_summary = any(term in text for term in ["summarize", "summary", "brief", "important", "prioritize"])
    terms = prompt_terms(prompt)
    target_matches = target_email_matches(prompt, terms)
    categories = [category for category in sorted({email["category"].lower() for email in SYNTHETIC_INBOX}) if category.lower() in text]
    if "customer" in text and "Customer" not in categories:
        categories.append("customer")
    if "sales" in text and "Sales" not in categories:
        categories.append("sales")
    if "investor" in text and "Investor" not in categories:
        categories.append("investor")
    question_lookup = is_direct_lookup_prompt(text)
    return {
        "count": max(1, min(count, 12)),
        "explicit_count": number_match is not None,
        "wants_reply": wants_reply,
        "wants_archive": wants_archive,
        "wants_summary": wants_summary or not wants_reply,
        "categories": sorted(set(categories)),
        "prompt_terms": terms,
        "direct_lookup": question_lookup or bool(target_matches["ids"] and not wants_reply),
        "targeted_lookup": bool(target_matches["ids"]),
        "target_email_ids": target_matches["ids"],
        "matched_people": target_matches["people"],
        "deadline_focus": any(term in text for term in ["today", "deadline", "urgent", "important", "critical"]),
        "revenue_focus": any(term in text for term in ["revenue", "sales", "customer", "churn", "renewal", "pilot", "deal"]),
    }


def select_emails(prompt: str, intent: dict[str, Any], agent_id: str) -> list[dict[str, Any]]:
    scored = [(score_email(email, prompt, intent), email) for email in SYNTHETIC_INBOX]
    if intent["wants_archive"]:
        scored = [(archive_score(email, prompt), email) for email in SYNTHETIC_INBOX]
    target_ids = set(intent.get("target_email_ids", []))
    if target_ids and not intent["wants_archive"]:
        scored = [item for item in scored if item[1]["id"] in target_ids]
    scored.sort(key=lambda item: item[0], reverse=True)
    count = selection_count(intent)
    if agent_id == "evaluator":
        count = selection_count(intent)
    return [email for score, email in scored if score > 0][:count]


def score_email(email: dict[str, Any], prompt: str, intent: dict[str, Any]) -> float:
    del prompt
    target_ids = set(intent.get("target_email_ids", []))
    direct_lookup = bool(intent.get("direct_lookup") or intent.get("targeted_lookup"))
    score = float(email["priority"]) * (0.18 if direct_lookup else 1.0)
    if email["id"] in target_ids:
        score += 520
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
    term_score = prompt_match_score(email, intent.get("prompt_terms", []))
    score += term_score
    if direct_lookup and term_score <= 0 and email["id"] not in target_ids and not intent["categories"]:
        score -= 120
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


def inbox_context_for_agent(prompt: str, intent: dict[str, Any], agent_id: str) -> list[dict[str, Any]]:
    if agent_id == "cascade":
        candidates = [(score_email(email, prompt, intent), email) for email in SYNTHETIC_INBOX]
        if intent["wants_archive"]:
            candidates = [(archive_score(email, prompt), email) for email in SYNTHETIC_INBOX]
        target_ids = set(intent.get("target_email_ids", []))
        if target_ids and not intent["wants_archive"]:
            candidates = [item for item in candidates if item[1]["id"] in target_ids]
        candidates.sort(key=lambda item: item[0], reverse=True)
        target_count = max(selection_count(intent), int(os.getenv("INBOX_OLLAMA_CONTEXT_EMAILS", "8")))
        return [email for score, email in candidates if score > 0][:target_count]
    return SYNTHETIC_INBOX


def build_inbox_prompt(prompt: str, intent: dict[str, Any], emails: list[dict[str, Any]]) -> str:
    payload = {
        "user_prompt": prompt,
        "intent": {
            "count": intent["count"],
            "wants_reply": intent["wants_reply"],
            "wants_archive": intent["wants_archive"],
            "wants_summary": intent["wants_summary"],
            "categories": intent["categories"],
            "direct_lookup": intent["direct_lookup"],
            "matched_people": intent["matched_people"],
        },
        "mailbox": [model_email(email) for email in emails],
    }
    return (
        "Complete the inbox task from this JSON. Return only the JSON result.\n"
        + json.dumps(payload, ensure_ascii=True)
    )


def model_email(email: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": email["id"],
        "received": email["received"],
        "from_name": email["from_name"],
        "from_email": email["from_email"],
        "role": email["role"],
        "subject": email["subject"],
        "body": email["body"],
        "category": email["category"],
        "priority": email["priority"],
        "urgency": email["urgency"],
        "deadline": email["deadline"],
        "needs_response": email["needs_response"],
        "tags": email["tags"],
        "expected_action": email["expected_action"],
    }


def provider_output_from_payload(
    provider: str,
    model: str,
    payload: Any,
    raw: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> InboxProviderOutput:
    if not isinstance(payload, dict):
        return unavailable_output(provider, model, "Model returned non-object JSON.", raw=raw)
    selected_ids = unique_strings(payload.get("selected_email_ids"))
    return InboxProviderOutput(
        provider=provider,
        model=model,
        selected_email_ids=selected_ids,
        answer=coerce_answer(payload.get("answer"), selected_ids),
        drafts=sanitize_drafts(payload.get("drafts") or []),
        operations=sanitize_operations(payload.get("operations") or [], [], {}),
        raw=raw,
        input_tokens=max(0, int(input_tokens or 0)),
        output_tokens=max(0, int(output_tokens or 0)),
        confidence=clamp_confidence(payload.get("confidence"), 0.72),
    )


def unavailable_output(provider: str, model: str, message: str, raw: str = "") -> InboxProviderOutput:
    return InboxProviderOutput(
        provider=provider,
        model=model,
        selected_email_ids=[],
        answer=message,
        drafts=[],
        operations=[],
        raw=raw or message,
        error=message,
        confidence=0.0,
    )


def clamp_confidence(value: Any, default: float = 0.0) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(1.0, confidence))


def coerce_answer(value: Any, selected_ids: list[str]) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return coerce_answer(json.loads(text), selected_ids)
            except json.JSONDecodeError:
                selected = selected_from_ids(selected_ids)
                if selected:
                    return direct_lookup_answer(selected)
                return text
        return text
    if isinstance(value, list):
        return "\n".join(coerce_answer(item, selected_ids) for item in value if item).strip()
    if isinstance(value, dict):
        for key in ("answer", "summary", "message", "response"):
            if value.get(key):
                return coerce_answer(value[key], selected_ids)
        if value.get("body"):
            name = value.get("from_name") or value.get("sender") or selected_sender_name(selected_ids)
            body = str(value["body"]).strip()
            subject = f" about {value['subject']}" if value.get("subject") else ""
            return f"{name} said{subject}: {body}".strip()
        if selected_ids:
            selected = [email for email in selected_from_ids(selected_ids)]
            if selected:
                return direct_lookup_answer(selected)
        return json.dumps(value, ensure_ascii=True)
    if selected_ids:
        selected = [email for email in selected_from_ids(selected_ids)]
        if selected:
            return direct_lookup_answer(selected)
    return ""


def selected_sender_name(selected_ids: list[str]) -> str:
    selected = selected_from_ids(selected_ids)
    return selected[0]["from_name"] if selected else "The sender"


def selected_from_ids(selected_ids: list[str]) -> list[dict[str, Any]]:
    email_by_id = {email["id"]: email for email in SYNTHETIC_INBOX}
    return [email_by_id[email_id] for email_id in selected_ids if email_id in email_by_id]


def selected_from_provider_output(output: InboxProviderOutput) -> list[dict[str, Any]]:
    email_by_id = {email["id"]: email for email in SYNTHETIC_INBOX}
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for email_id in output.selected_email_ids:
        if email_id in seen or email_id not in email_by_id:
            continue
        selected.append(email_by_id[email_id])
        seen.add(email_id)
    return selected


def infer_selected_from_answer(answer: str) -> list[dict[str, Any]]:
    text = answer.lower()
    selected = []
    for email in SYNTHETIC_INBOX:
        if email["from_name"].lower() in text or email["subject"].lower() in text:
            selected.append(email)
    return selected


def sanitize_drafts(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    drafts: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        to = str(item.get("to") or "").strip()
        subject = str(item.get("subject") or "").strip()
        body = str(item.get("body") or "").strip()
        if to and subject and body:
            drafts.append({"to": to, "subject": subject, "body": body})
    return drafts[:12]


def sanitize_operations(value: Any, selected: list[dict[str, Any]], intent: dict[str, Any]) -> list[dict[str, Any]]:
    del selected, intent
    if not isinstance(value, list):
        return []
    valid_ids = {email["id"] for email in SYNTHETIC_INBOX}
    valid_types = {"summarize", "draft_reply", "archive", "mark_read", "star", "flag"}
    operations: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        email_id = str(item.get("email_id") or "").strip()
        operation_type = str(item.get("type") or "summarize").strip()
        if email_id not in valid_ids:
            continue
        if operation_type not in valid_types:
            operation_type = "summarize"
        operations.append(
            {
                "type": operation_type,
                "email_id": email_id,
                "label": str(item.get("label") or operation_type.replace("_", " ").title()).strip(),
                "reason": str(item.get("reason") or "").strip(),
            }
        )
    return operations[:12]


def parse_model_json(raw: str) -> Any:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def extract_openai_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks: list[str] = []
    for output in data.get("output") or []:
        for content in output.get("content") or []:
            if isinstance(content.get("text"), str):
                chunks.append(content["text"])
            elif isinstance(content.get("output_text"), str):
                chunks.append(content["output_text"])
    return "\n".join(chunks)


def extract_openai_usage(data: dict[str, Any]) -> tuple[int, int]:
    usage = data.get("usage") or {}
    return int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0), int(
        usage.get("output_tokens") or usage.get("completion_tokens") or 0
    )


def extract_anthropic_inbox_payload(data: dict[str, Any]) -> tuple[Any, str]:
    text_blocks: list[str] = []
    for block in data.get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") == "inbox_result":
            payload = block.get("input") or {}
            return payload, json.dumps(payload, ensure_ascii=True)
        if block.get("type") == "text":
            text_blocks.append(str(block.get("text") or ""))
    raw = "\n".join(text_blocks)
    return parse_model_json(raw), raw


def extract_anthropic_usage(data: dict[str, Any]) -> tuple[int, int]:
    usage = data.get("usage") or {}
    return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)


def unique_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            items.append(text)
    return items


def provider_error_completion(message: str | None) -> dict[str, Any]:
    return {
        "state": "provider_unavailable",
        "passed_checks": 0,
        "total_checks": 1,
        "checks": [
            {
                "label": "Provider call completed",
                "passed": False,
                "detail": message or "Provider did not return a usable response.",
            }
        ],
    }


def response_error(provider_name: str, response: Any) -> str:
    body = str(getattr(response, "text", "") or "").strip().replace("\n", " ")
    if len(body) > 500:
        body = body[:497] + "..."
    return f"{provider_name} API returned HTTP {response.status_code}: {body or response.reason_phrase}"


def safe_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:500]


def estimate_text_tokens(text: str) -> int:
    return max(1, round(len(str(text or "")) / 4))


def estimate_provider_cost_usd(agent_id: str, model: str, input_tokens: int, output_tokens: int) -> float:
    if agent_id == "cascade":
        return 0.0
    input_per_mtok, output_per_mtok = provider_price_per_mtok(agent_id, model)
    return (input_tokens / 1_000_000) * input_per_mtok + (output_tokens / 1_000_000) * output_per_mtok


def provider_price_per_mtok(agent_id: str, model: str) -> tuple[float, float]:
    normalized = (model or "").lower()
    if agent_id == "openai":
        env_input = os.getenv("OPENAI_INPUT_COST_PER_MTOK")
        env_output = os.getenv("OPENAI_OUTPUT_COST_PER_MTOK")
        if env_input and env_output:
            return float(env_input), float(env_output)
        if "gpt-5.6-luna" in normalized:
            return 1.0, 6.0
        if "gpt-5.6-terra" in normalized:
            return 2.5, 15.0
        return 5.0, 30.0
    if agent_id == "claude":
        env_input = os.getenv("ANTHROPIC_INPUT_COST_PER_MTOK")
        env_output = os.getenv("ANTHROPIC_OUTPUT_COST_PER_MTOK")
        if env_input and env_output:
            return float(env_input), float(env_output)
        if "haiku" in normalized:
            return 1.0, 5.0
        if "sonnet-5" in normalized:
            return 2.0, 10.0
        if "sonnet" in normalized:
            return 3.0, 15.0
        return 5.0, 25.0
    return 0.0, 0.0


def compose_answer(agent_id: str, prompt: str, intent: dict[str, Any], selected: list[dict[str, Any]]) -> str:
    if not selected:
        return f"No matching emails were found for: {prompt}"
    if intent.get("direct_lookup"):
        return direct_lookup_answer(selected)
    if intent["wants_archive"]:
        bullets = [
            f"{email['from_name']} - {email['subject']}: {message_summary(email)} Low action pressure; {email['expected_action']}"
            for email in selected
        ]
        return "Safe archive candidates:\n" + "\n".join(f"- {bullet}" for bullet in bullets)
    heading = "Draft-ready messages:" if intent["wants_reply"] else "Relevant inbox summary:"
    if agent_id == "cascade":
        heading = "Fast inbox pass:"
    elif agent_id == "openai":
        heading = "Task answer:"
    else:
        bullets = [
            f"{email['from_name']} - {email['subject']}: {message_summary(email)} Action: {email['expected_action']} Deadline: {email['deadline'] or 'none'}."
            for email in selected
        ]
        return "Contextual inbox answer:\n" + "\n".join(f"- {bullet}" for bullet in bullets)
    bullets = [
        f"{email['from_name']} - {email['subject']}: {message_summary(email)} Action: {email['expected_action']} Deadline: {email['deadline'] or 'none'}."
        for email in selected
    ]
    return heading + "\n" + "\n".join(f"- {bullet}" for bullet in bullets)


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


def action_trace(
    agent_id: str,
    selected: list[dict[str, Any]],
    intent: dict[str, Any],
    output: InboxProviderOutput | None = None,
) -> list[dict[str, Any]]:
    if output and output.route_events:
        return [
            {
                "step": index,
                "route": event.get("route", "unknown"),
                "label": event.get("label", "Route event"),
                "detail": event.get("detail", ""),
                "confidence": event.get("confidence"),
                "latency_ms": event.get("latency_ms"),
                "tokens": event.get("tokens"),
                "messages": event.get("messages"),
            }
            for index, event in enumerate(output.route_events, start=1)
        ]
    profile = AGENTS[agent_id]
    actions = []
    for index, label in enumerate(profile["route"], start=1):
        route = "slm" if agent_id == "cascade" else "llm"
        actions.append(
            {
                "step": index,
                "route": route,
                "label": label,
                "detail": trace_detail(index, selected, intent, output),
            }
        )
    return actions


def trace_detail(
    index: int,
    selected: list[dict[str, Any]],
    intent: dict[str, Any],
    output: InboxProviderOutput | None = None,
) -> str:
    if index == 1:
        if intent.get("matched_people"):
            return "Matched sender: " + ", ".join(intent["matched_people"]) + "."
        return f"Read the prompt and searched {len(SYNTHETIC_INBOX)} messages."
    if index == 2:
        if output and output.error:
            return output.error
        if output:
            return f"Called {output.provider} model {output.model}."
        return f"Selected {len(selected)} relevant message{'s' if len(selected) != 1 else ''}."
    if index == 3:
        return f"Validated {len(selected)} cited email{'s' if len(selected) != 1 else ''}."
    return "Prepared mailbox actions for review."


def mailbox_operations(selected: list[dict[str, Any]], intent: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for email in selected:
        if intent["wants_archive"]:
            operations.append(
                {
                    "type": "archive",
                    "email_id": email["id"],
                    "label": f"Archive {email['from_name']}",
                    "reason": "Low urgency or no response required.",
                }
            )
        elif intent["wants_reply"] and email["needs_response"]:
            operations.append(
                {
                    "type": "draft_reply",
                    "email_id": email["id"],
                    "label": f"Draft reply to {email['from_name']}",
                    "reason": email["expected_action"],
                }
            )
        else:
            operations.append(
                {
                    "type": "summarize",
                    "email_id": email["id"],
                    "label": f"Summarize {email['from_name']}",
                    "reason": email["subject"],
                }
            )
    return operations


def evaluate_completion(
    selected: list[dict[str, Any]],
    matched: list[dict[str, Any]],
    drafts: list[dict[str, str]],
    intent: dict[str, Any],
    answer: str,
) -> dict[str, Any]:
    selected_ids = {email["id"] for email in selected}
    matched_ids = {email["id"] for email in matched}
    checks = [
        {
            "label": "Found relevant email",
            "passed": bool(selected),
            "detail": f"{len(selected)} email{'s' if len(selected) != 1 else ''} selected.",
        },
        {
            "label": "Answered with mailbox content",
            "passed": answer_is_grounded(answer, selected),
            "detail": "The response includes sender, subject, or message-specific terms from the selected email.",
        },
    ]
    if matched_ids:
        checks.append(
            {
                "label": "Matched prompt target",
                "passed": matched_ids.issubset(selected_ids),
                "detail": f"Expected {len(matched_ids)} target email{'s' if len(matched_ids) != 1 else ''}.",
            }
        )
        if intent.get("direct_lookup") or intent.get("targeted_lookup"):
            checks.append(
                {
                    "label": "Avoided unrelated emails",
                    "passed": selected_ids.issubset(matched_ids),
                    "detail": "Direct lookups should cite only the requested sender or message.",
                }
            )
    if intent["wants_reply"]:
        needed = len([email for email in selected if email["needs_response"]])
        checks.append(
            {
                "label": "Prepared requested drafts",
                "passed": len(drafts) >= min(int(intent["count"]), needed),
                "detail": f"{len(drafts)} draft{'s' if len(drafts) != 1 else ''} prepared.",
            }
        )
    if intent["wants_archive"]:
        checks.append(
            {
                "label": "Chose archive candidates",
                "passed": bool(selected) and all(email["urgency"] in {"low", "medium"} or not email["needs_response"] for email in selected),
                "detail": "Selected emails have low action pressure.",
            }
        )
    passed = sum(1 for check in checks if check["passed"])
    return {
        "state": "complete" if passed == len(checks) else "needs_review",
        "passed_checks": passed,
        "total_checks": len(checks),
        "checks": checks,
    }


def answer_is_grounded(answer: str, selected: list[dict[str, Any]]) -> bool:
    answer_text = str(answer or "").lower()
    if len(answer_text.split()) < 5 or not selected:
        return False
    for email in selected:
        if email["from_name"].lower() in answer_text or email["subject"].lower() in answer_text:
            return True
        keywords = content_keywords(email)
        if sum(1 for keyword in keywords if keyword in answer_text) >= 3:
            return True
    return False


def content_keywords(email: dict[str, Any]) -> list[str]:
    text = " ".join(
        [
            email["from_name"],
            email["subject"],
            email["body"],
            email["expected_action"],
            " ".join(email["tags"]),
        ]
    )
    return [
        term
        for term in prompt_terms(text)
        if len(term) >= 5 and term not in {"email", "reply", "action", "needed", "today"}
    ][:18]


def run_summary(results: list[dict[str, Any]], matched: list[dict[str, Any]]) -> dict[str, Any]:
    states = [result["completion"]["state"] for result in results]
    return {
        "state": "complete" if states and all(state == "complete" for state in states) else "needs_review",
        "agents_completed": len(results),
        "matched_emails": len(matched),
        "drafts_created": sum(len(result["drafts"]) for result in results),
        "operations_prepared": sum(len(result["operations"]) for result in results),
        "total_tokens": sum(int(result.get("tokens") or 0) for result in results),
        "total_cost_usd": round(sum(float(result.get("cost_usd") or 0) for result in results), 6),
        "providers_unavailable": sum(1 for result in results if result["status"] == "provider_unavailable"),
    }


def email_summary(email: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": email["id"],
        "received": email["received"],
        "from_name": email["from_name"],
        "from_email": email["from_email"],
        "role": email["role"],
        "subject": email["subject"],
        "body": email["body"],
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


def selection_count(intent: dict[str, Any]) -> int:
    target_ids = intent.get("target_email_ids", [])
    if target_ids and not intent.get("explicit_count"):
        return len(target_ids)
    if intent.get("direct_lookup") and not intent.get("explicit_count"):
        return 3 if intent.get("categories") and not target_ids else max(1, min(intent["count"], 5))
    return int(intent["count"])


def prompt_terms(prompt: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for term in re.findall(r"[a-zA-Z][a-zA-Z0-9']{1,}", prompt.lower()):
        normalized = term.strip("'")
        if normalized.endswith("'s"):
            normalized = normalized[:-2]
        if len(normalized) < 3 or normalized in STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return terms


def is_direct_lookup_prompt(text: str) -> bool:
    return bool(
        re.search(
            r"\b(what did|what does|what do|what was|what were|what is|what are|tell me what|who said|who asked)\b",
            text,
        )
        or re.search(r"\b(say|says|said|ask|asks|asked|want|wants|wanted|mention|mentioned)\b", text)
    )


def target_email_matches(prompt: str, terms: list[str]) -> dict[str, list[str]]:
    normalized_prompt = normalize_lookup_text(prompt)
    term_set = set(terms)
    ids: list[str] = []
    people: list[str] = []
    for email in SYNTHETIC_INBOX:
        full_name = normalize_lookup_text(email["from_name"])
        name_parts = [part for part in full_name.split() if len(part) > 2]
        local_part = email["from_email"].split("@", 1)[0]
        local_tokens = [part for part in re.split(r"[^a-zA-Z0-9]+", local_part.lower()) if len(part) > 2]
        matched_full_name = bool(full_name and re.search(rf"\b{re.escape(full_name)}\b", normalized_prompt))
        matched_token = any(part in term_set for part in name_parts + local_tokens)
        if matched_full_name or matched_token:
            ids.append(email["id"])
            people.append(email["from_name"])
    return {"ids": ids, "people": people}


def normalize_lookup_text(value: str) -> str:
    return " ".join(re.findall(r"[a-zA-Z0-9]+", str(value).lower()))


def prompt_match_score(email: dict[str, Any], terms: list[str]) -> float:
    if not terms:
        return 0
    from_text = f"{email['from_name']} {email['from_email']}".lower()
    subject_text = email["subject"].lower()
    body_text = email["body"].lower()
    meta_text = f"{email['role']} {email['category']} {' '.join(email['tags'])}".lower()
    score = 0.0
    for term in terms:
        if term in from_text:
            score += 110
        if term in subject_text:
            score += 42
        if term in body_text:
            score += 32
        if term in meta_text:
            score += 26
    return score


def direct_lookup_answer(selected: list[dict[str, Any]]) -> str:
    lines = []
    for email in selected:
        deadline = f" Deadline: {email['deadline']}." if email.get("deadline") else ""
        action = str(email["expected_action"]).rstrip(".")
        lines.append(
            f"- {email['from_name']} said: {message_summary(email)} Action needed: {action}.{deadline}"
        )
    return "\n".join(lines)


def message_summary(email: dict[str, Any]) -> str:
    body = " ".join(str(email["body"]).split())
    return body if body.endswith((".", "!", "?")) else body + "."


def sentence_anchor(email: dict[str, Any]) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", str(email["body"]).strip(), maxsplit=1)[0]
    return sentence[:80]


STOPWORDS = {
    "about",
    "after",
    "agent",
    "agents",
    "asked",
    "asks",
    "before",
    "could",
    "did",
    "does",
    "doing",
    "draft",
    "email",
    "emails",
    "from",
    "give",
    "have",
    "important",
    "inbox",
    "into",
    "need",
    "needs",
    "please",
    "reply",
    "respond",
    "safe",
    "say",
    "said",
    "says",
    "summarize",
    "summary",
    "that",
    "tell",
    "this",
    "today",
    "what",
    "when",
    "where",
    "which",
    "with",
    "want",
    "wants",
}
