"""Fictional, explicitly labelled sample businesses for the public Demo Center."""
SCENARIOS = [
    {
        "id": "home-services", "label": "Home services", "icon": "⌂", "industry": "HVAC", "template_name": "HVAC",
        "business": "Summit Home Comfort", "role": "AI Receptionist", "initials": "SH",
        "headline": "The next job starts with a conversation.",
        "description": "An after-hours AC inquiry becomes a clear request for your service team.",
        "customer": "Alex Morgan", "need": "AC repair", "priority": "Urgent service request", "next": "Team confirms availability",
        "greeting": "Hi! Welcome to Summit Home Comfort. I can help with heating and cooling questions or start a service request. What can I help with?",
        "prompts": ["My AC stopped cooling", "Can I get a repair quote?", "Do you offer maintenance?"],
        "facts": "Fictional HVAC business. Services: AC repair, heating, and maintenance. Office hours: Monday–Friday, 8am–5pm. Serves San Diego. Pricing requires an assessment. Staff must confirm all service times. Do not give hazardous repair instructions.",
        "steps": [
            {"label": "Answer", "detail": "Respond when the customer reaches out.", "customer": "My AC stopped cooling. Can someone help tomorrow?", "reply": "I can help start a repair request. Are you in San Diego, and is the system blowing warm air or not turning on?"},
            {"label": "Qualify", "detail": "Understand the need and urgency.", "customer": "San Diego. It’s running, but the air is warm.", "reply": "Thanks — I’ll include that detail. What name and phone number should the service team use to follow up?"},
            {"label": "Capture", "detail": "Keep the details together in one lead.", "customer": "Alex Morgan. Use the sample contact on this demo.", "reply": "Your sample request is ready: Alex Morgan, AC repair, San Diego, tomorrow preferred."},
            {"label": "Handoff", "detail": "Give your team a clear next step.", "customer": "Perfect. What happens next?", "reply": "The next step is for the service team to confirm availability and pricing. This is a demonstration, so no actual appointment has been made."},
        ],
    },
    {
        "id": "dental", "label": "Dental care", "icon": "✧", "industry": "Dental", "template_name": "Dental",
        "business": "Lumière Dental", "role": "Patient Concierge", "initials": "LD",
        "headline": "A warmer welcome. Before the first visit.", "description": "Help a new patient understand the next step and request an appointment.",
        "customer": "Jamie Taylor", "need": "New patient visit", "priority": "New patient inquiry", "next": "Front desk confirms visit",
        "greeting": "Welcome to Lumière Dental! I can help with general practice questions or start a new-patient appointment request.",
        "prompts": ["I’m looking for a new dentist", "Can I request a cleaning?", "Do you accept my insurance?"],
        "facts": "Fictional dental practice. Services: routine cleanings, exams, cosmetic consultations. Office hours Monday–Friday, 9am–5pm. Insurance eligibility, treatment advice and appointment times must be confirmed by staff. Do not give medical diagnosis or ask for sensitive medical information in the demo.",
        "steps": [
            {"label": "Answer", "detail": "Welcome a new patient.", "customer": "I’m looking for a dentist. Are you taking new patients?", "reply": "I can start a new-patient inquiry for the front desk. Are you interested in a routine exam and cleaning?"},
            {"label": "Qualify", "detail": "Understand the appointment request.", "customer": "Yes, an exam and cleaning. Mornings work best.", "reply": "Great. I’ll note your morning preference. What name should I include with the request?"},
            {"label": "Capture", "detail": "Prepare a clear patient inquiry.", "customer": "Jamie Taylor. Use the sample contact here.", "reply": "The sample inquiry is ready: Jamie Taylor, new-patient exam and cleaning, morning preferred."},
            {"label": "Handoff", "detail": "Let the front desk confirm the details.", "customer": "Can you confirm a time?", "reply": "The front desk would confirm availability and insurance directly. This demonstration does not book a real visit."},
        ],
    },
    {
        "id": "real-estate", "label": "Real estate", "icon": "◇", "industry": "Real Estate", "template_name": "Real Estate",
        "business": "Forma Property Group", "role": "Buyer Assistant", "initials": "FP",
        "headline": "Turn browsing into a better introduction.", "description": "Gather a buyer’s preferences so an agent can pick up with context.",
        "customer": "Sam Rivera", "need": "Buyer consultation", "priority": "Ready to explore", "next": "Agent follows up",
        "greeting": "Hi! I’m the assistant for Forma Property Group. I can help start a buyer inquiry and share your preferences with an agent.",
        "prompts": ["I’d like to tour a home", "I’m buying my first home", "Can an agent contact me?"],
        "facts": "Fictional real estate agency serving San Diego. Helps buyers and sellers connect with an agent. No live listings or market data. Never invent available homes, property prices, loan approval, financial advice or confirmed tours. Ask about requested location, timing, and contact preference.",
        "steps": [
            {"label": "Answer", "detail": "Meet the buyer at the moment of interest.", "customer": "I’m looking for a home in San Diego.", "reply": "I can help start a buyer inquiry. What type of home are you looking for, and when do you hope to move?"},
            {"label": "Qualify", "detail": "Collect useful search preferences.", "customer": "A three-bedroom home. In about three months.", "reply": "I’ll include those preferences for the agent. What name should I put on the inquiry?"},
            {"label": "Capture", "detail": "Create an introduction with context.", "customer": "Sam Rivera. Use the demo contact.", "reply": "Your sample inquiry is ready: Sam Rivera, three bedrooms, San Diego, approximately three months."},
            {"label": "Handoff", "detail": "Give the agent a useful starting point.", "customer": "Can you arrange a tour?", "reply": "An agent would follow up to discuss current listings and tour availability. No real tour is scheduled in this demo."},
        ],
    },
    {
        "id": "auto", "label": "Auto services", "icon": "↗", "industry": "Auto Repair", "template_name": "Auto Repair",
        "business": "Apex Auto Studio", "role": "Service Assistant", "initials": "AA",
        "headline": "Keep the conversation moving.", "description": "Capture the vehicle, concern, and preferred visit before your team calls back.",
        "customer": "Jordan Lee", "need": "Brake inspection", "priority": "Service inquiry", "next": "Service advisor follows up",
        "greeting": "Welcome to Apex Auto Studio. I can answer general service questions or help start an inspection request.",
        "prompts": ["My brakes are squeaking", "Can I book an oil change?", "How much is an inspection?"],
        "facts": "Fictional auto repair business. Services: oil changes, brake inspections, routine maintenance. Hours Monday–Friday, 8am–6pm. Quotes depend on inspection. Staff confirm availability. Never diagnose a car or say an unsafe vehicle is safe to drive.",
        "steps": [
            {"label": "Answer", "detail": "Start with the customer’s concern.", "customer": "My brakes are squeaking. Can you inspect them?", "reply": "I can start an inspection request. What is the year, make, and model of your vehicle?"},
            {"label": "Qualify", "detail": "Gather the right service context.", "customer": "A 2020 Toyota Camry. Friday would be ideal.", "reply": "I’ll note the vehicle and your Friday preference. What name should the service advisor use?"},
            {"label": "Capture", "detail": "Save the request and vehicle details.", "customer": "Jordan Lee. Use the sample details.", "reply": "The sample request is ready: Jordan Lee, 2020 Toyota Camry, brake inspection, Friday preferred."},
            {"label": "Handoff", "detail": "Put the advisor in position to help.", "customer": "Will I get a quote?", "reply": "The service advisor would confirm timing and explain inspection and quote options. This demonstration does not schedule an actual repair."},
        ],
    },
]


def sample_reply(scenario, message):
    text = message.lower()
    if any(term in text for term in ["price", "cost", "quote", "how much", "insurance"]):
        return f"The {scenario['business']} team would confirm pricing and any eligibility details directly. I can help outline your request. What service are you interested in?"
    if any(term in text for term in ["book", "appointment", "tour", "visit", "schedule"]):
        return "I can help draft that request. What would you like help with, and what day or time do you prefer? This is a sample conversation, so no real booking will be made."
    if any(term in text for term in ["hours", "open", "close"]):
        return "This is a fictional business preview. Your own assistant can answer using the business hours and policies you add to its profile. What else would you like to try?"
    return f"I can help start a {scenario['need'].lower()} inquiry. Tell me a little more about what you need and your preferred timing. Please use sample details in this demo."
