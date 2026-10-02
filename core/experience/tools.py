"""Only synthetic, revision-pinned data and the caller's isolated session are reachable."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
from django.db import transaction
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from typing import Literal


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Search(Arguments):
    query: str | None = Field(default=None, max_length=100)
    max_price: int | None = Field(default=None, ge=0, le=500000)
    min_price: int | None = Field(default=None, ge=0, le=500000)
    body_style: Literal["SUV", "sedan", "truck", "convertible"] | None = None
    min_seating: int | None = Field(default=None, ge=1, le=12)
    rows: int | None = Field(default=None, ge=1, le=3)
    drivetrain: Literal["AWD", "4WD", "FWD", "RWD"] | None = None
    condition: Literal["new", "used", "certified"] | None = None
    fuel_type: Literal["gas", "hybrid", "electric"] | None = None
    status: Literal["available", "pending", "sold", "all"] = "available"
    sort: Literal["price", "mileage", "year"] = "price"


class Vehicle(Arguments):
    stock: str = Field(min_length=1, max_length=30)


class Compare(Arguments):
    stocks: list[str] = Field(min_length=2, max_length=3)


class Business(Arguments):
    topic: Literal["overview", "team", "promotions", "test_drive", "appointments", "availability", "trade", "finance", "prices", "service", "recalls", "warranty", "privacy", "escalation", "ai_business_gurus"]


class Hours(Arguments):
    department: Literal["sales", "service", "finance", "bdc"]


class FAQ(Arguments):
    query: str = Field(min_length=1, max_length=160)


class Slots(Arguments):
    day: str = Field(description="YYYY-MM-DD, today, tomorrow or a weekday (e.g. Saturday).", max_length=20)


class SalesAppointment(Arguments):
    slot_id: str = Field(max_length=80)
    stock: str = Field(max_length=30)
    confirmed_by_customer: bool = Field(description="True only after the customer selects the offered slot and agrees to this demo test drive.")


class ServiceAppointment(Arguments):
    slot_id: str = Field(max_length=80)
    vehicle: str = Field(min_length=3, max_length=120)
    request: str = Field(min_length=3, max_length=300)
    confirmed_by_customer: bool


class Customer(Arguments):
    name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=254)
    financing_preference: Literal["undecided", "dealer_financing", "own_financing", "cash"] | None = None
    interest: str | None = Field(default=None, max_length=200)
    budget: str | None = Field(default=None, max_length=100)
    priorities: list[str] | None = Field(default=None, max_length=8)
    timeframe: str | None = Field(default=None, max_length=100)
    language: str | None = Field(default=None, max_length=40)
    questions: str | None = Field(default=None, max_length=500)
    market_status: Literal["shopping", "no_longer_in_market", "do_not_follow_up"] | None = None

    @field_validator("phone", "email")
    @classmethod
    def contact_format(cls, value, info):
        if value is None:
            return value
        from .financing import clean_phone, clean_email
        return clean_phone(value) if info.field_name == "phone" else clean_email(value)


class FinanceApplication(Arguments):
    stock: str | None = Field(default=None, max_length=30, description="The customer's chosen available stock, or null if still deciding.")
    confirmed_by_customer: bool = Field(description="True only when the customer asks for or accepts opening the fictional financing application.")


class Trade(Arguments):
    year: int | None = Field(default=None, ge=1960, le=2028)
    make: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=60)
    trim: str | None = Field(default=None, max_length=60)
    mileage: int | None = Field(default=None, ge=0, le=1000000)
    condition: str | None = Field(default=None, max_length=250)
    payoff_status: str | None = Field(default=None, max_length=120)


class Handoff(Arguments):
    summary: str = Field(min_length=1, max_length=1000, description="Concise summary of what this customer actually said, without assumptions or invented facts.")
    recommended_follow_up: str = Field(max_length=350)
    temperature: Literal["new", "exploring", "qualified", "appointment", "not_in_market"]


TOOL_MODELS = {
    "search_inventory": (Search, "Search the pinned synthetic inventory. Use BEFORE giving vehicle prices, specs or availability. Available only by default; max 6 results."),
    "get_vehicle": (Vehicle, "Get exact synthetic vehicle specifications and availability by stock ID."),
    "compare_vehicles": (Compare, "Compare 2–3 actual stock IDs, including vehicles shown earlier in this conversation."),
    "get_business_info": (Business, "Retrieve approved fictional business facts or a specific policy. Do not guess policies."),
    "get_department_hours": (Hours, "Return approved hours for the selected fictional department."),
    "search_demo_faq": (FAQ, "Search approved dealership FAQs; unknown questions must be escalated without inventing answers."),
    "get_available_sales_slots": (Slots, "Return available synthetic test-drive times. Use before offering appointments."),
    "get_service_slots": (Slots, "Return available synthetic service intake/drop-off times. No completion-time guarantee."),
    "create_demo_sales_appointment": (SalesAppointment, "Book/replace a DEMO ONLY test drive after the customer chooses an offered slot. Writes only the session's fictional dealership CRM."),
    "create_demo_service_appointment": (ServiceAppointment, "Book/replace a DEMO ONLY service intake after the customer chooses an offered slot. No real calendar or outbound message."),
    "update_customer": (Customer, "Remember customer-stated name, phone, email, financing preference, needs and buying timeline. Ask for contact details naturally, recommend fictional examples for this demo, and respect a decline. Never invent contact information. On already purchased or stop requests mark not in market / do not follow up."),
    "open_demo_finance_application": (FinanceApplication, "Open the on-screen fictional financing application after the customer agrees. Prefills known contact and selected vehicle. Only the customer can review and submit the form. No real credit application, credit check or lender connection."),
    "create_demo_trade_lead": (Trade, "Record known trade information, leave unknown fields null. Never return or invent an exact valuation."),
    "create_demo_bdc_handoff": (Handoff, "Update the fictional dealership CRM with a grounded summary, next action and lead temperature. Do not claim real staff were contacted."),
}


def definitions():
    tools = []
    for name, (model, description) in TOOL_MODELS.items():
        schema = model.model_json_schema()
        # OpenAI strict mode requires all keys. Nullable fields represent unknown values.
        schema["required"] = list(schema["properties"])
        for prop in schema["properties"].values():
            prop.pop("default", None)
        tools.append({"type": "function", "function": {"name": name, "description": description, "strict": True, "parameters": schema}})
    return tools


def initial_state(scenario):
    state = {"customer": {"name": "Demo Customer", "market_status": "shopping"}, "trade": {},
             "appointments": {}, "vehicles": [], "cards": [], "slots": [], "offered_slots": {},
             "stage": "ready", "summary": "", "follow_up": "", "temperature": "new", "crm_actions": []}
    if scenario == "reactivation":
        state["customer"].update(name="Marcus", interest="Ford F-150 (fictional inquiry 90 days ago)")
    return state


def effective_price(vehicle):
    return vehicle.get("special_price") if vehicle.get("special_price") is not None else vehicle["price"]


def search_inventory(content, args):
    rows = content["inventory"]
    query = (args.get("query") or "").casefold().split()
    result = []
    for row in rows:
        price = effective_price(row)
        if args.get("max_price") is not None and price > args["max_price"]:
            continue
        if args.get("min_price") is not None and price < args["min_price"]:
            continue
        if args.get("min_seating") and row["seating"] < args["min_seating"]:
            continue
        if any(args.get(k) and row.get(k) != args[k] for k in ("body_style", "rows", "drivetrain", "condition", "fuel_type")):
            continue
        if args.get("status", "available") != "all" and row["status"] != args.get("status", "available"):
            continue
        haystack = " ".join(str(row[k]) for k in ("year", "make", "model", "trim", "stock", "features")).casefold()
        if not all(word in haystack for word in query):
            continue
        result.append(dict(row, display_price=price))
    key = args.get("sort", "price")
    result.sort(key=lambda v: -v["year"] if key == "year" else v["mileage"] if key == "mileage" else v["display_price"])
    return {"total": len(result), "vehicles": result[:6], "synthetic": True}


def get_vehicle(content, stock):
    vehicle = next((row for row in content["inventory"] if row["stock"] == stock), None)
    if vehicle is None:
        raise ValueError("That stock number is not in this demo inventory.")
    return dict(vehicle, display_price=effective_price(vehicle))


def available_slots(session, department, day):
    base = session.created_at.astimezone(ZoneInfo(session.revision.content["business"]["timezone"])).date()
    day = day.strip().lower()
    if day in ("today", "tomorrow"):
        target = base + timedelta(days=day == "tomorrow")
    elif day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        n = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(day)
        target = base + timedelta(days=(n - base.weekday()) % 7 or 7)
    else:
        try:
            target = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("Choose today, tomorrow, a weekday or YYYY-MM-DD.")
    if not base <= target <= base + timedelta(days=14):
        raise ValueError("Demo slots are available within the next 14 days.")
    if session.scenario == "after-hours" and target == base:
        return {"slots": [], "reason": "Staff are offline at the scenario time of 11:47 PM. Try tomorrow.", "synthetic": True}
    times = ["13:30", "15:00", "16:30"] if department == "sales" else ["08:00", "10:00", "13:00"]
    if department == "service" and target.weekday() == 6:
        times = []
    slots = [{"id": f"{department}:{target.isoformat()}:{t}", "department": department,
              "date": target.isoformat(), "time": t, "timezone": session.revision.content["business"]["timezone"],
              "label": f"{target.strftime('%a, %b %d')} · {datetime.strptime(t, '%H:%M').strftime('%I:%M %p').lstrip('0')} Pacific"} for t in times]
    local_start = session.created_at.astimezone(ZoneInfo(session.revision.content["business"]["timezone"]))
    if target == base:
        slots = [slot for slot in slots if slot["time"] > local_start.strftime("%H:%M")]
    session.state["slots"] = slots
    session.state["offered_slots"].update({s["id"]: s for s in slots})
    return {"slots": slots, "synthetic": True, "note": "Service times are intake only. No real calendar is connected."}


def _appointment(session, department, args):
    if not args["confirmed_by_customer"]:
        raise ValueError("Ask the customer to choose and agree to a demo slot first.")
    slot = session.state["offered_slots"].get(args["slot_id"])
    if not slot or slot["department"] != department:
        raise ValueError("Retrieve and offer a valid slot for this department first.")
    if session.state["customer"].get("market_status") in ("do_not_follow_up", "no_longer_in_market") and department == "sales":
        raise ValueError("This customer is no longer shopping. Respect their preference.")
    appointment = dict(slot, confirmation=f"DEMO-{str(session.pk)[:6].upper()}-{'S' if department == 'sales' else 'R'}", status="confirmed", synthetic=True)
    if department == "sales":
        vehicle = get_vehicle(session.revision.content, args["stock"])
        if vehicle["status"] != "available":
            raise ValueError("That vehicle is not available for a demo test drive.")
        appointment["vehicle"] = vehicle
    else:
        appointment.update(vehicle_description=args["vehicle"], request=args["request"])
    previous = session.state["appointments"].get(department)
    session.state["appointments"][department] = appointment
    session.state.update(stage="appointment", temperature="appointment")
    if previous != appointment:
        session.state["crm_actions"].append({"action": "Demo appointment rescheduled" if previous else "Demo appointment booked", "description": f"{department.title()} · {slot['label']} · {appointment['confirmation']}"})
    return appointment


def execute(session, name, raw):
    if name not in TOOL_MODELS:
        return {"error": "This operation is not available in the demo."}
    try:
        model = TOOL_MODELS[name][0]
        args = model.model_validate(raw).model_dump()
        content, state = session.revision.content, session.state
        if name == "search_inventory":
            result = search_inventory(content, args)
            state["cards"] = result["vehicles"]
            state["vehicles"] = list(dict.fromkeys(state["vehicles"] + [v["stock"] for v in result["vehicles"]]))[-18:]
            if state["stage"] == "ready":
                state["stage"] = "discovery"
            return result
        if name == "get_vehicle":
            result = get_vehicle(content, args["stock"])
            state["cards"] = [result]
            state["vehicles"] = list(dict.fromkeys(state["vehicles"] + [result["stock"]]))[-18:]
            return result
        if name == "compare_vehicles":
            if len(set(args["stocks"])) != len(args["stocks"]):
                raise ValueError("Choose distinct vehicles to compare.")
            result = [get_vehicle(content, stock) for stock in args["stocks"]]
            state["cards"] = result
            state["comparison"] = True
            return {"vehicles": result, "synthetic": True}
        if name == "get_business_info":
            topic = args["topic"]
            if topic == "overview":
                return {k: content["business"][k] for k in ("name", "address", "phone", "departments", "timezone")}
            return {topic: content["business"].get(topic, content["business"]["policies"].get(topic))}
        if name == "get_department_hours":
            return {"department": args["department"], "hours": content["business"]["hours"][args["department"]], "timezone": content["business"]["timezone"]}
        if name == "search_demo_faq":
            words = {s.strip('?!.,') for s in args["query"].lower().split() if len(s) > 2}
            ranked = sorted(((len(words & set((f["question"] + " " + f["answer"]).lower().split())), f) for f in content["business"]["faqs"]), key=lambda r: r[0], reverse=True)
            return {"faqs": [f for score, f in ranked[:4] if score], "unknown_policy": "If not answered, offer a simulated specialist handoff; do not invent facts."}
        if name in ("get_available_sales_slots", "get_service_slots"):
            return available_slots(session, "sales" if name == "get_available_sales_slots" else "service", args["day"])
        if name == "create_demo_sales_appointment":
            return _appointment(session, "sales", args)
        if name == "create_demo_service_appointment":
            return _appointment(session, "service", args)
        if name == "update_customer":
            previous = dict(state["customer"])
            state["customer"].update({k: v for k, v in args.items() if v is not None})
            if state["customer"].get("market_status") in ("no_longer_in_market", "do_not_follow_up"):
                state.update(stage="closed", temperature="not_in_market", follow_up="Respect the customer's preference. No sales follow-up.")
            elif state["customer"].get("interest") and state["stage"] != "appointment":
                state["stage"] = "qualified"
            elif state["stage"] == "ready" and any(state["customer"].get(key) for key in ("phone", "email")):
                state["stage"] = "discovery"
            if previous != state["customer"]:
                state["crm_actions"].append({"action": "Customer preferences captured", "description": "Axel updated customer-stated needs and follow-up preferences."})
            return state["customer"]
        if name == "open_demo_finance_application":
            if not args["confirmed_by_customer"]:
                raise ValueError("Ask whether the customer would like to open the demo financing application first.")
            from .financing import open_application
            return {"application": open_application(session, args["stock"]), "action": "open_finance_application", "note": "Explain that you are opening the fictional form. The customer reviews and submits it; no credit inquiry, lender transmission or approval occurs."}
        if name == "create_demo_trade_lead":
            previous = dict(state["trade"])
            state["trade"].update({k: v for k, v in args.items() if v is not None})
            if state["trade"] and state["stage"] == "ready":
                state["stage"] = "discovery"
            if previous != state["trade"]:
                state["crm_actions"].append({"action": "Trade details captured", "description": "Known trade details saved; no appraisal value was generated."})
            return {"trade": state["trade"], "valuation": None, "note": "Inspection, title and payoff verification required; no valuation provided."}
        if name == "create_demo_bdc_handoff":
            state.update(summary=args["summary"], follow_up=args["recommended_follow_up"], temperature=args["temperature"])
            if state["customer"].get("market_status") in ("no_longer_in_market", "do_not_follow_up"):
                state.update(temperature="not_in_market", follow_up="No sales follow-up; customer no longer in market.")
            state["crm_actions"].append({"action": "AI handoff prepared", "description": "Conversation summary and next step added to the fictional dealership CRM."})
            return {"saved": True, "destination": "Velocity Motors fictional CRM", "synthetic": True}
    except ValidationError:
        return {"error": "Invalid tool arguments. Use the declared schema and only known customer details."}
    except (ValueError, KeyError) as exc:
        return {"error": str(exc)[:200]}
    return {"error": "Unsupported operation."}


def handoff(session):
    s = session.state
    return {"customer": s.get("customer", {}), "trade": s.get("trade", {}), "appointments": s.get("appointments", {}),
            "vehicles": [get_vehicle(session.revision.content, stock) for stock in s.get("vehicles", [])],
            "summary": s.get("summary", ""), "follow_up": s.get("follow_up", ""), "temperature": s.get("temperature", "new"),
            "stage": s.get("stage", "ready"), "financing_application": s.get("financing_application"), "transcript": session.transcript, "synthetic": True}


@transaction.atomic
def sync_crm(session):
    from core.models import DemoCRMLead, DemoCRMActivity
    state = session.state
    if state.get("stage") == "ready" and not state.get("summary"):
        return None
    lead, created = DemoCRMLead.objects.get_or_create(session=session)
    lead = DemoCRMLead.objects.select_for_update().get(pk=lead.pk)
    snapshot = handoff(session)
    lead.customer_name = snapshot["customer"].get("name") or "Demo Customer"
    if created or lead.snapshot.get("stage") != snapshot["stage"]:
        lead.stage = snapshot["stage"]
    lead.snapshot = snapshot
    lead.save()
    if created:
        DemoCRMActivity.objects.create(lead=lead, action="Demo customer created", description="This demo's prospect was captured in the fictional Velocity Motors CRM.")
    for action in state.get("crm_actions", [])[-8:]:
        DemoCRMActivity.objects.create(lead=lead, **action)
    state["crm_actions"] = []
    return lead
