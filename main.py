from agents import Agent, Runner, function_tool
from app import config
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import re

# ==============================
# Context Model (Pydantic)
# ==============================
class SupportContext(BaseModel):
    name: str = "Guest"
    is_premium_user: bool = False
    issue_type: Optional[str] = None  # 'billing' | 'technical' | 'general'
    last_agent: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)

# Global mutable context used by tools (simple approach for console demo)
CTX = SupportContext()

# ==============================
# Guardrail (Optional Bonus)
# ==============================
BANNED_PHRASES = re.compile(r"\b(sorry|apologiz\w*)\b", re.IGNORECASE)

def guard_output(text: str) -> str:
    """Ensure output never contains apologies. Replace if found."""
    if not text:
        return text
    return BANNED_PHRASES.sub("(removed)", text)

# ==============================
# Tools (with dynamic is_enabled)
# ==============================
@function_tool
def classify_issue(user_text: str) -> str:
    t = user_text.lower()
    if any(w in t for w in ["refund", "invoice", "bill", "payment"]):
        return "billing"
    if any(w in t for w in ["error", "crash", "down", "restart", "bug", "technical"]):
        return "technical"
    return "general"

@function_tool
def get_invoice(dummy: str) -> str:
    who = CTX.name
    tier = "Premium" if CTX.is_premium_user else "Free"
    return f"Invoice for {who}: Plan={tier}, Last payment: 2025-08-01, Amount: $19.00"

@function_tool
def refund(dummy: str) -> str:
    if not getattr(refund, "is_enabled")(CTX):  # dynamic gating
        return "Refund tool disabled: premium membership required."
    return f"Refund initiated for {CTX.name}. You will receive confirmation via email."

# attach dynamic is_enabled to refund
refund.is_enabled = lambda ctx: bool(ctx.is_premium_user)

@function_tool
def restart_service(dummy: str) -> str:
    if not getattr(restart_service, "is_enabled")(CTX):
        return "Restart tool disabled: this request is not a technical issue."
    return "Service restart command sent. Please wait ~2 minutes and try again."

# dynamic gate for restart_service: only when issue_type == "technical"
restart_service.is_enabled = lambda ctx: (ctx.issue_type == "technical")

@function_tool
def check_service_status(dummy: str) -> str:
    return "All systems operational, no outages detected in your region."

@function_tool
def general_faq(user_text: str) -> str:
    return (
        "Here's some info: You can update profile in Settings > Account. "
        "Type 'invoice', 'refund', or describe a technical error for specialized help."
    )

# ==============================
# Agents
# ==============================
triage_agent = Agent(
    name="Triage Agent",
    instructions=(
        "Classify the user's issue into one of: billing, technical, or general using classify_issue. "
        "Return only the single word label."
    ),
    tools=[classify_issue],
)

billing_agent = Agent(
    name="Billing Agent",
    instructions=(
        "Handle billing questions. Use get_invoice by default; use refund for premium users when refund is mentioned."
    ),
    tools=[get_invoice, refund],
)

technical_agent = Agent(
    name="Technical Support Agent",
    instructions=(
        "Handle technical issues. Prefer restart_service when appropriate; otherwise check_service_status."
    ),
    tools=[restart_service, check_service_status],
)

general_agent = Agent(
    name="General Info Agent",
    instructions="Provide concise general help using general_faq.",
    tools=[general_faq],
)

# Helper to merge config with context
ndefault_config = dict(config) if isinstance(config, dict) else {}

def run_with_context(agent: Agent, text: str):
    run_cfg = {**ndefault_config, "context": CTX.dict()}
    result = Runner.run(agent, text, run_config=run_cfg)
    result.final_output = guard_output(getattr(result, "final_output", ""))
    return result

# ==============================
# CLI Orchestration
# ==============================
if __name__ == "__main__":
    print("\n🛠️ Console-Based Support Agent System (OpenAI Agents SDK)\n")
    # Collect user profile for context
    name = input("Your name: ").strip() or "Guest"
    premium = input("Are you a premium user? (y/n): ").strip().lower().startswith("y")

    CTX.name = name
    CTX.is_premium_user = premium

    print("\nType your question (e.g., 'I want a refund', 'app keeps crashing'). Type 'exit' to quit.\n")

    while True:
        user_text = input("You: ").strip()
        if user_text.lower() in {"exit", "quit"}:
            print("Goodbye!")
            break

        # 1) TRIAGE
        triage_res = run_with_context(triage_agent, user_text)
        issue_type = (triage_res.final_output or "").strip().lower()
        if issue_type not in {"billing", "technical", "general"}:
            issue_type = "general"
        CTX.issue_type = issue_type
        CTX.last_agent = "triage"
        print(f"→ Handoff: Triage classified issue as '{issue_type}'.")

        # 2) ROUTE / HANDOFF
        if issue_type == "billing":
            if re.search(r"refund|chargeback|money back", user_text, re.I):
                hint = "refund"
            else:
                hint = "invoice"
            res = run_with_context(billing_agent, hint)
        elif issue_type == "technical":
            hint = "restart" if re.search(r"restart|crash|down|error", user_text, re.I) else "status"
            res = run_with_context(technical_agent, hint)
        else:
            res = run_with_context(general_agent, user_text)

        # 3) OUTPUT
        print(f"{CTX.issue_type.title()} Agent → {res.final_output}\n")

        # 4) Simple loop status
        CTX.last_agent = CTX.issue_type
        CTX.issue_type = None
