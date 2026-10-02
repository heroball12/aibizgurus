"""Deterministic, fictional data. No dealer feed, real VINs or customer records."""
from copy import deepcopy

VERSION = "velocity-2026.1.2"
PROMPT_VERSION = "concierge-2"
BUSINESS = {
    "name": "Velocity Motors", "employee": "Axel", "tagline": "Your next chapter. Your next drive.",
    "address": "100 Demo Drive, Example City, CA 00000 (fictional — do not navigate)",
    "phone": "+1 202-555-0146 (fictional demo number — not a contact channel)",
    "timezone": "America/Los_Angeles", "currency": "USD",
    "hours": {"sales": {"Mon–Fri": "9:00 AM–7:00 PM", "Saturday": "9:00 AM–6:00 PM", "Sunday": "11:00 AM–5:00 PM"},
              "service": {"Mon–Fri": "7:30 AM–5:30 PM", "Saturday": "8:00 AM–2:00 PM", "Sunday": "Closed"},
              "finance": {"Mon–Fri": "10:00 AM–6:00 PM", "Saturday": "10:00 AM–5:00 PM", "Sunday": "By appointment"},
              "bdc": {"Mon–Sat": "8:00 AM–6:00 PM", "Sunday": "11:00 AM–4:00 PM"}},
    "team": [
        {"name": "Elena Rivera", "department": "BDC", "role": "BDC director", "languages": ["English", "Spanish"]},
        {"name": "Marcus Reed", "department": "Sales", "role": "Product specialist", "languages": ["English"]},
        {"name": "Sofia Chen", "department": "Sales", "role": "Product specialist", "languages": ["English", "Spanish"]},
        {"name": "Jordan Ellis", "department": "Service", "role": "Service advisor", "languages": ["English"]},
        {"name": "Alex Morgan", "department": "Finance", "role": "Finance manager", "languages": ["English"]}],
    "departments": ["Sales", "BDC", "Service", "Finance", "Appraisal"],
    "policies": {
        "test_drive": "Demo test drives last 30 minutes. In a real visit, bring a valid driver license and proof of insurance. No payment or credit application is needed for this simulation. A demo slot does not reserve a real vehicle.",
        "appointments": "Use only returned demo slots. Ask the customer to choose before confirming. Sales visits and service drop-offs are different calendars. No calendar invites, calls or messages are actually sent. Service slots are intake/drop-off times, not promised completion times.",
        "availability": "Inventory is synthetic. Available, pending and sold are different statuses. Only available vehicles can be selected for a demo test drive. If a vehicle becomes unavailable, the BDC would contact the customer to discuss alternatives; never substitute without agreement.",
        "trade": "Capture year, make, model, trim if known, mileage, condition and payoff status if voluntarily offered. Do not request account numbers. Appraisal requires inspection, title and payoff verification. Do not give an exact or guaranteed value.",
        "finance": "The fictional finance team works with multiple lenders and accepts outside financing, subject to verification. Ask whether the customer wants dealership financing, their own bank, or to pay in full. On request, Axel can open a fictional application prefilled with known contact and vehicle details. The customer reviews a fixed sample financial profile and submits it to the fictional CRM. No lender submission, credit check or approval occurs; this demo has no real credit application. Never ask for SSN, DOB, bank details or a credit report. No guaranteed approvals, binding APRs, monthly payments, credit outcomes or legal/tax advice.",
        "prices": "All prices and specifications are illustrative demo data, not offers from a manufacturer or dealer. Demo prices exclude tax, title, licensing and any applicable fees; no out-the-door quote is available. A special price replaces the listed demo price where shown; do not invent discounts or stack specials.",
        "service": "Oil changes, tire rotations, brakes, battery checks, diagnostics and scheduled maintenance are offered. Vehicles need not have been purchased here. Ask vehicle/year, symptoms or requested service, and timing. Exact cost and duration require a service advisor. Do not diagnose failures or give repair instructions. For braking loss, smoke, overheating or unsafe drivability, recommend stopping safely and contacting qualified roadside/service help rather than driving to a demo appointment.",
        "recalls": "A service advisor must check the real VIN with manufacturer recall information. Do not collect a real VIN in this demo, claim a recall applies, or promise parts availability.",
        "warranty": "New, used and certified pre-owned are distinct inventory categories. Warranty coverage varies by vehicle and program and requires document verification. Do not promise remaining coverage, accident history, a clean title or a completed inspection absent explicit data.",
        "privacy": "Ask for name, phone and email naturally during intake; recommend a fictional name, 202-555-0146 and an example.com email. Respect a refusal. Contact details only stay in this temporary demo and are never used for outreach. No real address or financial details are needed. The application uses fixed sample financial profiles. Conversations and synthetic workflow state are retained briefly for demo operations; microphone recordings are not saved by the app.",
        "escalation": "BDC handles shopping, visit changes and next-business-day follow-up requests; Service handles repairs and recall questions; Finance handles credit questions; Appraisal handles trade valuation. Record a simulated handoff, never claim a real staff member was contacted.",
        "ai_business_gurus": "For a real business implementation, offer a complimentary 15–20 minute Growth Assessment with an AI Specialist. They review current operations, bottlenecks and systems, identify useful AI workflows, and propose an implementation strategy. Pricing is custom to the recommended build and only AI Specialists discuss it during the Growth Assessment. No guaranteed integrations, revenue, ROI or appointments."},
    "promotions": [
        {"name": "Family-ready showcase", "description": "Selected three-row SUVs carry an explicitly marked demo special price in inventory. No real offer or expiration promise."},
        {"name": "Explore electric", "description": "Ask a product specialist about charging routines and eligible demo EVs. No claim about tax credits or actual incentives."}],
    "faqs": [
        {"question": "Do you sell used or certified pre-owned vehicles?", "answer": "Yes. Search inventory by condition: new, used or certified. Certification and specific warranty terms need verification outside this demo."},
        {"question": "Do you have electric and hybrid vehicles?", "answer": "Yes; use inventory fuel_type to find electric or hybrid options. Range and efficiency figures here are illustrative, not guaranteed."},
        {"question": "Do you have Spanish-speaking staff?", "answer": "Elena Rivera in BDC and Sofia Chen in Sales speak Spanish. Axel can continue this demonstration in Spanish and note a language preference."},
        {"question": "Can I bring my own financing?", "answer": "Yes, outside financing is accepted subject to verification. The Finance team handles documentation; no real application is taken here."},
        {"question": "Can I get pre-approved?", "answer": "Axel can open a fictional financing application after you agree. Choose a sample profile, review the contact and vehicle details and submit to see it in the fictional CRM. This demo cannot issue pre-approval, process credit or guarantee terms."},
        {"question": "Can I bring a trade with a loan?", "answer": "Yes. Note payoff status if known. The appraisal team would verify the balance and title; do not share an account number or statement here."},
        {"question": "What should I bring for a test drive or purchase?", "answer": "For a real test drive: valid driver license and proof of insurance. For a trade: title/registration and keys. A specialist would explain any additional finance documents privately; don't upload them here."},
        {"question": "What if the vehicle sells before my visit?", "answer": "The BDC would contact you to discuss alternatives or rescheduling. This demo doesn't hold vehicles; only available synthetic vehicles can be booked."},
        {"question": "Do you service vehicles bought elsewhere?", "answer": "Yes. Give a fictional vehicle/year and service request, and we can demonstrate an intake appointment. An advisor must confirm real compatibility and pricing."},
        {"question": "Is there Saturday service?", "answer": "Service is open Saturday 8 AM–2 PM, closed Sunday. Use the service calendar tool for actual simulated slot availability."},
        {"question": "Can someone call me tomorrow?", "answer": "Axel can record a simulated next-day BDC follow-up preference. No call will actually be placed; a real business inquiry goes through the Growth Assessment form."},
        {"question": "Do you deliver or sell remotely?", "answer": "Remote product questions are welcome. Delivery eligibility, location and fees require a human review; there is no demo delivery promise."},
        {"question": "How long will my repair take?", "answer": "A service advisor needs to inspect the concern and confirm parts availability. Demo slots are drop-off times, not completion guarantees."},
        {"question": "Can I reserve a vehicle with a deposit?", "answer": "This demo does not accept deposits, payments or real reservations. We can show a simulated test-drive appointment."},
        {"question": "Can I cancel or reschedule?", "answer": "Yes; in this demo ask for new available slots and replace the simulated appointment after choosing one. No external calendar is connected."},
        {"question": "What CRM is connected?", "answer": "The dealership view is an example CRM handoff using only this conversation. It is not connected to DealerSocket, VinSolutions, CDK, Reynolds or another dealership CRM. Integration feasibility is reviewed in a Growth Assessment."},
    ],
}
# make, model, trim, body, base price, seats, drivetrain, fuel, engine, illustrative efficiency
VEHICLES = [
    ("Hyundai", "Palisade", "SEL", "SUV", 43800, 8, "AWD", "gas", "3.8L V6", "21 MPG combined"),
    ("Kia", "Telluride", "EX", "SUV", 44900, 8, "AWD", "gas", "3.8L V6", "21 MPG combined"),
    ("Toyota", "Highlander", "XLE", "SUV", 45900, 7, "AWD", "hybrid", "2.5L hybrid", "35 MPG combined"),
    ("Ford", "Explorer", "Active", "SUV", 41900, 7, "AWD", "gas", "2.3L turbo", "23 MPG combined"),
    ("Honda", "Pilot", "EX-L", "SUV", 46900, 8, "AWD", "gas", "3.5L V6", "21 MPG combined"),
    ("Chevrolet", "Traverse", "LT", "SUV", 42900, 8, "AWD", "gas", "2.5L turbo", "22 MPG combined"),
    ("Hyundai", "Santa Fe", "SEL", "SUV", 39900, 7, "AWD", "hybrid", "1.6L turbo hybrid", "34 MPG combined"),
    ("Toyota", "RAV4", "XLE", "SUV", 35900, 5, "AWD", "hybrid", "2.5L hybrid", "40 MPG combined"),
    ("Honda", "CR-V", "Sport", "SUV", 35900, 5, "AWD", "hybrid", "2.0L hybrid", "37 MPG combined"),
    ("Honda", "Civic", "Sport", "sedan", 26900, 5, "FWD", "gas", "2.0L four cylinder", "33 MPG combined"),
    ("Toyota", "Corolla", "LE", "sedan", 23500, 5, "FWD", "gas", "2.0L four cylinder", "35 MPG combined"),
    ("Toyota", "Camry", "SE", "sedan", 31500, 5, "FWD", "hybrid", "2.5L hybrid", "46 MPG combined"),
    ("Honda", "Accord", "EX-L", "sedan", 34500, 5, "FWD", "hybrid", "2.0L hybrid", "48 MPG combined"),
    ("Ford", "F-150", "XLT", "truck", 53500, 5, "4WD", "gas", "3.5L turbo V6", "20 MPG combined"),
    ("Ram", "1500", "Big Horn", "truck", 51900, 5, "4WD", "gas", "3.0L turbo six cylinder", "20 MPG combined"),
    ("Chevrolet", "Silverado", "LT", "truck", 49900, 6, "4WD", "gas", "5.3L V8", "18 MPG combined"),
    ("Hyundai", "IONIQ 5", "SEL", "SUV", 47900, 5, "AWD", "electric", "Dual motor electric", "260 mile illustrative range"),
    ("Tesla", "Model Y", "Long Range", "SUV", 46900, 5, "AWD", "electric", "Dual motor electric", "300 mile illustrative range"),
    ("Mazda", "MX-5 Miata", "Club", "convertible", 34500, 2, "RWD", "gas", "2.0L four cylinder", "29 MPG combined"),
    ("BMW", "330i", "Sport", "sedan", 47900, 5, "RWD", "gas", "2.0L turbo", "29 MPG combined"),
]


def inventory():
    result = []
    for i, row in enumerate(VEHICLES):
        make, model, trim, body, price, seats, drive, fuel, engine, efficiency = row
        for j, condition in enumerate(["new", "used", "certified"]):
            stock = f"VM-{i + 1:02d}{j + 1:02d}"
            amount = price - j * 4200
            result.append({"id": stock, "stock": stock, "demo_identifier": f"DEMO-VELOCITY-{i + 1:03d}-{j + 1}",
                "year": 2026 - j, "make": make, "model": model, "trim": trim,
                "body_style": body, "price": amount, "msrp": price + 1800 if j == 0 else None,
                "special_price": amount - 700 if i in (0, 3, 7) and j == 0 else None,
                "mileage": 12 + i if j == 0 else 16000 * j + i * 500,
                "condition": condition, "drivetrain": drive, "fuel_type": fuel, "engine": engine,
                "exterior_color": ["Pearl white", "Midnight blue", "Graphite silver"][(i + j) % 3],
                "interior_color": "Charcoal", "seating": seats, "rows": 3 if seats >= 7 else 2,
                "efficiency": efficiency, "features": ["Rear camera", "Apple CarPlay", "Blind-spot monitoring"] +
                    (["Three-row seating", "Flexible cargo space"] if seats >= 7 else ["Split-folding rear seats"] if seats > 2 else ["Convertible roof"]) +
                    (["Heated seats", "Power liftgate"] if body == "SUV" else ["Cruise control"]),
                "status": "sold" if (i, j) in ((18, 1), (19, 2)) else "pending" if (i, j) in ((8, 2), (15, 0)) else "available",
                "image": f"img/experience/{'electric' if fuel == 'electric' else body.lower()}.jpg", "synthetic": True})
    return result


SCENARIOS = [
    ("vehicle-shopping", "Find your next vehicle", "Vehicle shopping", "Inventory questions", "You are welcoming a new shopper. Discover their needs, search real demo inventory, and ask one useful question at a time.", "I need an AWD SUV with three rows under $50,000."),
    ("fresh-lead", "A lead, answered", "Fresh internet lead", "Slow lead response", "This is a simulated fresh website inquiry. No third-party lead provider or outbound channel is connected. Engage promptly, find vehicle interest and timing, then offer a logical next step.", "I just asked about your Palisade. Is it available?"),
    ("after-hours", "11:47 PM. Still here.", "After-hours lead", "After-hours gaps", "Scenario clock is 11:47 PM; dealership staff are offline. Search current synthetic inventory, offer next-day slots and prepare a simulated morning BDC handoff. Never claim humans are online.", "Is that used F-150 still available? Can I come tomorrow?"),
    ("trade-in", "Make the next move", "Trade-in", "Incomplete trade leads", "Discover purchase interest and collect trade details conversationally. Explain appraisal verification, never fabricate a trade value.", "I have a 2022 Accord with about 60,000 miles to trade."),
    ("test-drive", "From interest to visit", "Test drive / appointment", "Appointment friction", "Find an available vehicle and offer returned sales slots. Create a synthetic appointment only after the customer chooses a slot. No external booking occurs.", "Can I test-drive a Palisade tomorrow afternoon?"),
    ("service", "Service, simplified", "Service scheduling", "Service workload", "Collect vehicle, year, service request and preferred timing; offer synthetic service intake slots. Avoid diagnosis, exact cost or completion promises.", "I need brakes and an oil change for my 2021 Honda CR-V."),
    ("missed-call", "A missed call, recovered", "Missed call", "Missed calls", "Simulate responding to a missed call; ask how to help and route to sales or service. This is an on-screen conversation, not a connected phone call or sent callback.", "I tried calling about a vehicle earlier. Can you help?"),
    ("reactivation", "A conversation reopened", "Database reactivation", "Untouched old leads", "Simulated old lead: fictional Marcus asked about an F-150 90 days ago. Ask whether still shopping. If already purchased or declines follow-up, mark no_longer_in_market/do_not_follow_up and stop selling. Adapt if needs change to an SUV; do not persist with the truck. No outbound message is sent.", "I'm still looking, but now I need an SUV instead of a truck."),
    ("financing", "Answers without pressure", "Financing application", "Finance uncertainty", "Ask about the preferred purchase plan. Explain the financing process and offer to open the fictional application; only open it after the customer agrees. The customer reviews sample financial data and submits it to the fictional CRM. No real applications, credit decisions, guaranteed approvals, binding APR or payment quotes.", "Can I bring my own financing, and do you take trades with a loan?"),
    ("inventory", "Know every option", "Inventory questions", "Repetitive questions", "Use search/get/compare tools for all specific inventory questions. Differentiate available, pending, sold and unknown. Never invent features or availability.", "Do you have used hybrid SUVs under $35,000?"),
]


def seed_content():
    return {"business": deepcopy(BUSINESS), "inventory": inventory(), "prompt_version": PROMPT_VERSION,
            "scenarios": [{"slug": s, "title": t, "label": l, "pain": p, "context": c, "starter": q, "enabled": True}
                          for s, t, l, p, c, q in SCENARIOS],
            "old_leads": [{"name": "Marcus", "interest": "Ford F-150", "days_since_inquiry": 90, "synthetic": True}]}
