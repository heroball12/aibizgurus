"""Conservative major-brand matching from listing data; no extra HTTP requests.

Keep this catalog limited to widely established chains. A brand tag, multiple
locations, a manufacturer, or a shared booking host alone is not chain evidence.
Unknown businesses stay eligible; this is not a certification of independence.
"""

import re
import unicodedata
from urllib.parse import urlsplit


# Display name, additional exact names, official website domains. Franchised
# locations count as part of their brand, regardless of local ownership.
MAJOR_CHAINS = (
    ("McDonald's", ("McDonalds",), ("mcdonalds.com",)),
    ("Starbucks", ("Starbucks Coffee",), ("starbucks.com",)),
    ("Subway", (), ("subway.com",)),
    ("Burger King", (), ("burgerking.com", "bk.com")),
    ("Wendy's", (), ("wendys.com",)),
    ("Taco Bell", (), ("tacobell.com",)),
    ("KFC", ("Kentucky Fried Chicken",), ("kfc.com",)),
    ("Chick-fil-A", (), ("chick-fil-a.com",)),
    ("Chipotle", ("Chipotle Mexican Grill",), ("chipotle.com",)),
    ("Popeyes", ("Popeyes Louisiana Kitchen",), ("popeyes.com",)),
    ("Dunkin'", ("Dunkin Donuts",), ("dunkindonuts.com",)),
    ("Panera Bread", ("Panera",), ("panerabread.com",)),
    ("Bruegger's Bagels", ("Brueggers", "Bruegger's"), ("brueggers.com",)),
    ("Einstein Bros. Bagels", ("Einstein Brothers Bagels",), ("einsteinbros.com",)),
    ("Domino's", ("Domino's Pizza",), ("dominos.com",)),
    ("Pizza Hut", (), ("pizzahut.com",)),
    ("Papa Johns", ("Papa John's Pizza",), ("papajohns.com",)),
    ("Little Caesars", ("Little Caesars Pizza",), ("littlecaesars.com",)),
    ("Dairy Queen", ("DQ Grill & Chill",), ("dairyqueen.com",)),
    ("Sonic Drive-In", ("Sonic",), ("sonicdrivein.com",)),
    ("Arby's", (), ("arbys.com",)),
    ("Jack in the Box", (), ("jackinthebox.com",)),
    ("Panda Express", (), ("pandaexpress.com",)),
    ("Five Guys", ("Five Guys Burgers and Fries",), ("fiveguys.com",)),
    ("Jersey Mike's", ("Jersey Mike's Subs",), ("jerseymikes.com",)),
    ("Jimmy John's", (), ("jimmyjohns.com",)),
    ("Firehouse Subs", (), ("firehousesubs.com",)),
    ("Wingstop", (), ("wingstop.com",)),
    ("Buffalo Wild Wings", (), ("buffalowildwings.com",)),
    ("Applebee's", ("Applebee's Grill + Bar",), ("applebees.com",)),
    ("Chili's", ("Chili's Grill & Bar",), ("chilis.com",)),
    ("Olive Garden", (), ("olivegarden.com",)),
    ("Denny's", (), ("dennys.com",)),
    ("IHOP", ("International House of Pancakes",), ("ihop.com",)),
    ("Cracker Barrel", ("Cracker Barrel Old Country Store",), ("crackerbarrel.com",)),
    ("Outback Steakhouse", (), ("outback.com",)),
    ("Texas Roadhouse", (), ("texasroadhouse.com",)),
    ("Walmart", ("Walmart Supercenter", "Walmart Neighborhood Market"), ("walmart.com",)),
    ("Target", (), ("target.com",)),
    ("Costco", ("Costco Wholesale",), ("costco.com",)),
    ("Sam's Club", (), ("samsclub.com",)),
    ("The Home Depot", ("Home Depot",), ("homedepot.com",)),
    ("Lowe's", ("Lowe's Home Improvement",), ("lowes.com",)),
    ("Walgreens", (), ("walgreens.com",)),
    ("CVS", ("CVS Pharmacy",), ("cvs.com",)),
    ("Dollar General", (), ("dollargeneral.com",)),
    ("Dollar Tree", (), ("dollartree.com",)),
    ("7-Eleven", (), ("7-eleven.com",)),
    ("Circle K", (), ("circlek.com",)),
    ("Best Buy", (), ("bestbuy.com",)),
    ("PetSmart", (), ("petsmart.com",)),
    ("Petco", (), ("petco.com",)),
    ("Great Clips", (), ("greatclips.com",)),
    ("Supercuts", (), ("supercuts.com",)),
    ("Sport Clips", ("Sport Clips Haircuts",), ("sportclips.com",)),
    ("Ulta Beauty", ("Ulta",), ("ulta.com",)),
    ("Sephora", (), ("sephora.com",)),
    ("Massage Envy", (), ("massageenvy.com",)),
    ("European Wax Center", (), ("waxcenter.com",)),
    ("Aspen Dental", (), ("aspendental.com",)),
    ("Gentle Dental", (), ("interdent.com",)),
    ("The Joint Chiropractic", (), ("thejoint.com",)),
    ("Jiffy Lube", (), ("jiffylube.com",)),
    ("Valvoline Instant Oil Change", (), ("vioc.com",)),
    ("Midas", (), ("midas.com",)),
    ("Meineke", ("Meineke Car Care Center",), ("meineke.com",)),
    ("Firestone Complete Auto Care", (), ("firestonecompleteautocare.com",)),
    ("Pep Boys", (), ("pepboys.com",)),
    ("Discount Tire", (), ("discounttire.com",)),
    ("AutoZone", (), ("autozone.com",)),
    ("O'Reilly Auto Parts", (), ("oreillyauto.com",)),
    ("Advance Auto Parts", (), ("advanceautoparts.com",)),
    ("CarMax", (), ("carmax.com",)),
    ("AutoNation", (), ("autonation.com",)),
    ("Carvana", (), ("carvana.com",)),
    ("State Farm", ("State Farm Insurance", "State Farm Insurance Agent"), ("statefarm.com",)),
    ("Allstate", ("Allstate Insurance",), ("allstate.com",)),
    ("GEICO", ("GEICO Insurance",), ("geico.com",)),
    ("Farmers Insurance", (), ("farmers.com",)),
    ("Progressive Insurance", (), ("progressive.com",)),
    ("Liberty Mutual", ("Liberty Mutual Insurance",), ("libertymutual.com",)),
    ("Bank of America", (), ("bankofamerica.com",)),
    ("Chase Bank", ("Chase",), ("chase.com",)),
    ("Wells Fargo", ("Wells Fargo Bank",), ("wellsfargo.com",)),
    ("Edward Jones", (), ("edwardjones.com",)),
    ("H&R Block", (), ("hrblock.com",)),
    ("Jackson Hewitt", ("Jackson Hewitt Tax Service",), ("jacksonhewitt.com",)),
    ("Liberty Tax", ("Liberty Tax Service",), ("libertytax.com",)),
    ("RE/MAX", ("REMAX",), ("remax.com", "remaxcommercial.com")),
    ("Keller Williams", ("Keller Williams Realty",), ("kw.com",)),
    ("Century 21", (), ("century21.com",)),
    ("Coldwell Banker", (), ("coldwellbanker.com",)),
    ("Servpro", (), ("servpro.com",)),
    ("ServiceMaster", ("ServiceMaster Restore",), ("servicemasterrestore.com",)),
    ("Roto-Rooter", (), ("rotorooter.com",)),
    ("Mr. Rooter", ("Mr. Rooter Plumbing",), ("mrrooter.com",)),
    ("Mr. Electric", (), ("mrelectric.com",)),
    ("One Hour Heating & Air Conditioning", (), ("onehourheatandair.com",)),
    ("TruGreen", (), ("trugreen.com",)),
    ("Orkin", (), ("orkin.com",)),
    ("Terminix", (), ("terminix.com",)),
    ("Trulieve", (), ("trulieve.com",)),
    ("Curaleaf", (), ("curaleaf.com",)),
    ("MedMen", (), ("medmen.com",)),
)


def normalized_name(value):
    value = unicodedata.normalize("NFKD", str(value)).casefold().replace("&", "and")
    return re.sub(r"[^a-z0-9]", "", value)


_NAMES = {normalized_name(alias): name for name, aliases, _ in MAJOR_CHAINS for alias in (name, *aliases)}
_DOMAINS = {domain: name for name, _, domains in MAJOR_CHAINS for domain in domains}


def major_chain_name(name="", website="", tags=None):
    """Return a known chain's name, or empty when the evidence is inconclusive."""
    tags = tags or {}
    for key in ("brand", "brand:en", "operator"):
        for value in str(tags.get(key) or "").split(";"):
            if match := _NAMES.get(normalized_name(value)):
                return match
    # Never match arbitrary substrings (e.g. Target Marketing or Subway Auto).
    # Allow explicit branch separators and store numbers, not free-form suffixes.
    value = re.sub(r"\s*(?:#|\bstore\s*#?)\s*\d+\s*$", "", str(name), flags=re.I)
    for part in [value, *re.split(r"\s+[-–—|]\s+", value)]:
        if match := _NAMES.get(normalized_name(part)):
            return match
    try:
        host = (urlsplit(website if "://" in website else "https://" + website).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    # A subdomain counts; a lookalike domain or URL path does not.
    for domain, brand in _DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return brand
    return ""
