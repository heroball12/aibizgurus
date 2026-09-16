"""Public prices shared by the website and video concierge."""

PRICING_PLANS = [
    {
        "eyebrow": "Starter",
        "name": "Starter",
        "setup": "Starting at $2,500 setup",
        "monthly": "Starting at $997/month",
        "features": ["AI chatbot or focused AI Employee", "Business knowledge setup", "Website embed", "Lead capture dashboard"],
        "featured": False,
    },
    {
        "eyebrow": "Most popular",
        "name": "Growth",
        "setup": "Starting at $5,000 setup",
        "monthly": "Starting at $1,997/month",
        "features": ["Multi-workflow AI assistant", "Automation and CRM routing", "Lead alerts", "Monthly optimization support"],
        "featured": True,
    },
    {
        "eyebrow": "AI Workforce",
        "name": "AI Workforce",
        "setup": "Starting at $10,000 setup",
        "monthly": "Starting at $3,997/month",
        "features": ["Multiple AI Employees", "Voice/SMS workflows", "Advanced integrations", "Executive growth roadmap"],
        "featured": False,
    },
]
