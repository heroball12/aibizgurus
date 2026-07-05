import json
from pathlib import Path

def load_industries():
    # Primary source: Python module data.
    try:
        from .industry_data import INDUSTRIES
        if INDUSTRIES:
            return list(INDUSTRIES), "python"
    except Exception:
        pass

    # Secondary source: JSON file.
    try:
        data_path = Path(__file__).resolve().parent / "industry_data.json"
        if data_path.exists():
            data = json.loads(data_path.read_text(encoding="utf-8"))
            if data:
                return data, "json"
    except Exception:
        pass

    # Emergency source: never let demo have only one option.
    names = [
        ("General", "Generic Local Service"),
        ("Home Services", "HVAC"),
        ("Home Services", "Plumbing"),
        ("Home Services", "Electrician"),
        ("Home Services", "Roofing"),
        ("Home Services", "Landscaping"),
        ("Home Services", "Pest Control"),
        ("Beauty & Wellness", "Med Spa"),
        ("Beauty & Wellness", "Hair Salon"),
        ("Beauty & Wellness", "Barbershop"),
        ("Healthcare", "Dental Office"),
        ("Healthcare", "Chiropractor"),
        ("Automotive", "Auto Repair"),
        ("Automotive", "Car Dealership"),
        ("Food & Hospitality", "Restaurant"),
        ("Food & Hospitality", "Catering"),
        ("Cannabis", "Cannabis Delivery"),
        ("Cannabis", "Dispensary"),
        ("Professional Services", "Law Firm"),
        ("Professional Services", "Accounting Firm"),
        ("Real Estate", "Real Estate Agent"),
        ("B2B Services", "Marketing Agency"),
    ]
    fallback = []
    for category, name in names:
        fallback.append({
            "name": name,
            "category": category,
            "summary": f"AI receptionist template for {name} businesses. Captures leads, answers FAQs, and routes requests.",
            "default_greeting": f"Hi! I’m the AI assistant for this {name} business. How can I help today?",
            "system_prompt": f"You are an AI receptionist for a {name} business. Answer questions using business info, capture leads, and escalate high-intent requests. Collect name, phone, email, need/request, urgency, and preferred follow-up time.",
            "lead_fields": ["name", "phone", "email", "need/request", "urgency", "preferred follow-up time"],
            "common_questions": ["What are your hours?", "How much does it cost?", "Can I book today?", "Do you serve my area?", "Can someone call me back?"],
            "escalation_rules": "Escalate urgent requests, booking/order requests, pricing requests, angry customers, safety issues, and anything outside the provided business info.",
        })
    return fallback, "emergency"
