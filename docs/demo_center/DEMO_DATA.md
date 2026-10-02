# Synthetic data and content versions

`core/experience/data.py` is the reviewed seed source. `python manage.py seed_demo_center` safely creates the experience/revision without publishing or overwriting manager edits. `--publish` explicitly enables public access. `--restore-seed` changes the current pointer for new sessions to the seeded version; historical sessions keep their snapshots. No real clients, CRM leads, staff, calendar appointments or external messages are seeded.

Velocity Motors contains 60 deterministically generated stock records: 20 model families across new, used and certified variants. These use familiar model names but **all prices, mileages, specifications, special prices and availability are fictional illustrations**, not manufacturer/dealer offers. Stock IDs begin VM-; VIN-like IDs begin DEMO- and are not real VINs. Available, pending and sold are separate; only available stock is bookable. Special prices participate in price filtering.

The knowledge set covers departments/hours, fictional staff and languages, business contact placeholders, finance process, trades, test drives, service, privacy, safety/escalation, pricing, warranties, promotions and 16 FAQs. The supplied address and 555 phone are labeled fictional and are not navigation/contact targets.

Slots are synthetic and deterministic relative to the session's start date in the configured dealership timezone. The horizon is 14 days; earlier times on the start day are excluded. Sales offers 1:30, 3:00 and 4:30 PM. Service offers 8:00, 10:00 AM and 1:00 PM; Sunday is closed. After-hours sessions offer no same-day slots. A service appointment is intake, not a guaranteed completion time. Each session has independent availability; nothing competes with a real customer.

Manager JSON edits are validated and create a new revision, never mutate historical content. Retain scenario IDs and the field schema; use enabled=false to hide a scenario. The current publication controls apply immediately even to older active public sessions.

Vehicle imagery was generated specifically for this project using the built-in image-generation tool. It is labeled representative on every card and never represented as exact stock photography. See IMAGE_PROVENANCE.md for prompts and asset paths. Cards retain their text if an image fails.
