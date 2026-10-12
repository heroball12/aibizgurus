"""Public contact details; the office street address is for confirmed visits."""
COMPANY = {
    "name": "AI Business Gurus",
    "phone": "(760) 847-8336",
    "phone_uri": "tel:+17608478336",
    "address": "Temecula, CA 92590",
    "city_state_zip": "Temecula, CA 92590",
    "office_visits": "By appointment only. The full street address and directions are provided after an in-person booking is confirmed.",
}

# Do not include these details in public templates or AI knowledge. Only the
# confirmed booking view, its emails, and its calendar invitation use them.
OFFICE_LOCATION = {
    "address": "41877 Enterprise Cir, Ste 200, Temecula, CA 92590",
    "street": "41877 Enterprise Cir, Ste 200",
    "directions_url": "https://www.google.com/maps/search/?api=1&query=41877+Enterprise+Cir+Ste+200+Temecula+CA+92590",
}


def company_contact(request):
    from django.contrib.staticfiles import finders
    film = "video/guru-welcome.mp4"
    return {"company": COMPANY, "guru_product_video": film if finders.find(film) else ""}
