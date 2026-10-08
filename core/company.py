"""Verified public company contact details shared by the site and Guru."""
COMPANY = {
    "name": "AI Business Gurus",
    "phone": "(760) 847-8336",
    "phone_uri": "tel:+17608478336",
    "address": "41877 Enterprise Cir, Ste 200, Temecula, CA 92590",
    "street": "41877 Enterprise Cir, Ste 200",
    "city_state_zip": "Temecula, CA 92590",
    "directions_url": "https://www.google.com/maps/search/?api=1&query=41877+Enterprise+Cir+Ste+200+Temecula+CA+92590",
}


def company_contact(request):
    from django.contrib.staticfiles import finders
    film = "video/guru-welcome.mp4"
    return {"company": COMPANY, "guru_product_video": film if finders.find(film) else ""}
