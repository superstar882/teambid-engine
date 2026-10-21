"""Per-member region rules: paper size, page budget, CV-length advice, letter date style and time zone.

US: Letter paper, 1 page (2 from ~8 years), "October 20, 2026".
EU / UK: A4 paper, up to 2 pages from ~3 years (1-2 pages is the European norm), "20 October 2026".
"""
import datetime as dt
import re
from zoneinfo import ZoneInfo

from . import config

EU_COUNTRIES = ("Germany|France|Spain|Italy|Netherlands|Belgium|Austria|Switzerland|Ireland|Portugal|Poland|Czech|Czechia|"
                "Slovakia|Hungary|Romania|Bulgaria|Greece|Croatia|Slovenia|Serbia|Sweden|Denmark|Norway|Finland|Estonia|"
                "Latvia|Lithuania|Luxembourg|Malta|Cyprus|Ukraine|Iceland")
CITY_TZ = {
    "Europe/Berlin": "Berlin|Munich|Hamburg|Frankfurt|Cologne|Stuttgart|Dusseldorf|Düsseldorf|Leipzig|Germany",
    "Europe/Paris": "Paris|Lyon|Marseille|Toulouse|Nice|Bordeaux|Lille|France",
    "Europe/Amsterdam": "Amsterdam|Rotterdam|Utrecht|Eindhoven|The Hague|Netherlands",
    "Europe/Madrid": "Madrid|Barcelona|Valencia|Seville|Malaga|Málaga|Spain",
    "Europe/Rome": "Rome|Milan|Turin|Naples|Bologna|Florence|Italy",
    "Europe/Warsaw": "Warsaw|Warszawa|Krakow|Kraków|Wroclaw|Wrocław|Gdansk|Gdańsk|Gdynia|Poznan|Poznań|Lodz|Łódź|Katowice|Lublin|"
                     "Szczecin|Bydgoszcz|Rzeszow|Rzeszów|Bialystok|Białystok|Poland|Polska",
    "Europe/Belgrade": "Belgrade|Beograd|Novi Sad|Nis|Niš|Kragujevac|Subotica|Serbia|Srbija|Sarajevo|Bosnia|Podgorica|Montenegro|"
                       "Skopje|North Macedonia|Ljubljana|Slovenia|Zagreb|Croatia",
    "Europe/Sofia": "Sofia|Plovdiv|Varna|Bulgaria",
    "Europe/Dublin": "Dublin|Cork|Galway|Ireland",
    "Europe/Lisbon": "Lisbon|Porto|Portugal",
    "Europe/Stockholm": "Stockholm|Gothenburg|Malmo|Malmö|Sweden",
    "Europe/Copenhagen": "Copenhagen|København|Aarhus|Odense|Aalborg|Denmark|Danmark",
    "Europe/Oslo": "Oslo|Bergen|Norway",
    "Europe/Helsinki": "Helsinki|Espoo|Tampere|Finland",
    "Europe/Zurich": "Zurich|Zürich|Geneva|Basel|Bern|Lausanne|Switzerland",
    "Europe/Vienna": "Vienna|Graz|Linz|Austria",
    "Europe/Brussels": "Brussels|Antwerp|Ghent|Belgium",
    "Europe/Prague": "Prague|Brno|Czech|Czechia",
    "Europe/Budapest": "Budapest|Hungary",
    "Europe/Bucharest": "Bucharest|Cluj|Romania",
    "Europe/Athens": "Athens|Thessaloniki|Greece",
    "Europe/Kyiv": "Kyiv|Kiev|Lviv|Kharkiv|Ukraine",
    "Europe/Tallinn": "Tallinn|Estonia",
    "Europe/London": "London|Manchester|Edinburgh|Glasgow|Birmingham|Bristol|Leeds|Cambridge|Oxford|Belfast|Cardiff|UK|United Kingdom|England|Scotland|Wales",
    "Asia/Kolkata": "India|Bangalore|Bengaluru|Hyderabad|Pune|Chennai|Mumbai|Delhi|Gurgaon|Gurugram|Noida",
    "Asia/Tokyo": "Japan|Tokyo|Osaka|Kyoto",
    "Asia/Singapore": "Singapore",
    "Australia/Sydney": "Australia|Sydney|Melbourne|Brisbane",
    "America/Toronto": "Toronto|Ottawa|Montreal|Ontario|Quebec",
    "America/Vancouver": "Vancouver|British Columbia",
    # Latin America (its own region: A4 paper, day-first dates, LATAM remote jobs)
    "America/Sao_Paulo": "Brazil|Brasil|São Paulo|Sao Paulo|Rio de Janeiro|Belo Horizonte|Brasília|Brasilia|Curitiba|Porto Alegre|"
                         "Florianópolis|Florianopolis|Recife|Fortaleza|Campinas|Goiânia|Goiania|Manaus|Belém|Belem|Vitória|Natal|"
                         "Joinville|Uberlândia|Uberlandia",
    "America/Argentina/Buenos_Aires": "Argentina|Buenos Aires|Rosario|Mendoza",
    "America/Mexico_City": "Mexico|México|Mexico City|Guadalajara|Monterrey",
    "America/Bogota": "Colombia|Bogotá|Bogota|Medellín|Medellin|Cali",
    "America/Santiago": "Chile|Santiago",
    "America/Lima": "Peru|Perú|Lima",
    "America/Montevideo": "Uruguay|Montevideo",
    "America/Costa_Rica": "Costa Rica|San José, Costa Rica",
}
LATAM_TZ = ("America/Sao_Paulo", "America/Argentina/Buenos_Aires", "America/Mexico_City", "America/Bogota", "America/Santiago",
            "America/Lima", "America/Montevideo", "America/Costa_Rica")
US_TZ = {"America/Los_Angeles": "CA|WA|OR|NV", "America/Denver": "CO|UT|AZ|NM|ID|MT|WY",
         "America/Chicago": "TX|IL|MN|WI|MO|IA|KS|NE|OK|LA|AR|TN|AL|MS|ND|SD",
         "America/New_York": "NY|NJ|MA|PA|FL|GA|NC|SC|VA|MD|DC|CT|RI|NH|VT|ME|DE|OH|MI|IN|KY|WV"}


def detect(location):
    """'Berlin, Germany' -> {'region': 'EU', 'countries': ['Germany', 'Europe'], 'timezone': 'Europe/Berlin'}"""
    loc = location or ""
    tz = None
    for zone, pat in CITY_TZ.items():
        if re.search(rf"(?i)\b({pat})\b", loc):
            tz = zone
            break
    if re.search(r"(?i)\b(UK|United Kingdom|England|Scotland|Wales|London|Manchester|Edinburgh|Glasgow|Birmingham|Bristol|Leeds|Belfast)\b", loc):
        return {"region": "UK", "countries": ["UK", "Europe"], "timezone": "Europe/London"}
    if tz in LATAM_TZ:
        return {"region": "LATAM", "countries": ["LATAM"], "timezone": tz}
    if re.search(rf"(?i)\b({EU_COUNTRIES})\b", loc) or (tz or "").startswith("Europe/"):
        countries = ["Germany", "Europe"] if tz == "Europe/Berlin" else ["Europe"]
        return {"region": "EU", "countries": countries, "timezone": tz or "Europe/Berlin"}
    m = re.search(r",\s*([A-Z]{2})\b", loc)
    if m:
        for zone, states in US_TZ.items():
            if re.fullmatch(states, m[1]):
                return {"region": "US", "countries": ["US"], "timezone": zone}
    if tz:
        country = {"Asia/Kolkata": "India", "Asia/Tokyo": "Japan", "Asia/Singapore": "Singapore", "Australia/Sydney": "Australia",
                   "America/Toronto": "Canada", "America/Vancouver": "Canada"}.get(tz, "US")
        return {"region": "other", "countries": [country], "timezone": tz}
    return {"region": "US", "countries": ["US"], "timezone": str(config.TZ)}


EU_PLACES = "|".join(pat for zone, pat in CITY_TZ.items() if zone.startswith("Europe/") and zone != "Europe/London")


def job_region(location="", jd_text="", salary=""):
    """Where a job is based: 'US', 'EU', 'UK' or None (unclear). Location first, then currency, then the post text."""
    loc = f"{location} {salary}"
    if re.search(r"(?i)\b(UK|United Kingdom|England|London)\b|£|GBP", loc):
        return "UK"
    if re.search(r"(?i)\b(Europe|EMEA|EU|EEA|CET|Nordics?|DACH|Benelux|" + EU_COUNTRIES + "|" + EU_PLACES + r")\b|€|EUR", loc):
        return "EU"
    if re.search(r"\b(US|USA|U\.S\.|United States)\b|,\s*[A-Z]{2}\b|\$|USD", loc):
        return "US"
    head = (jd_text or "")[:1500]
    if re.search(r"€|\bEUR\b|\b(Europe|EMEA|EU)\b", head):
        return "EU"
    if re.search(r"£|\bGBP\b|\bUK\b", head):
        return "UK"
    if re.search(r"\$\s?\d|\bUSD\b|\b(United States|US-based|U\.S\.)", head):
        return "US"
    return None


def paper(region):
    return "a4" if region in ("EU", "UK", "LATAM") else "letter"


def from_countries(countries):
    """Region implied by where someone can work: lets an edited country list fix a CV without a location."""
    c = set(countries or [])
    if not c or "US" in c:
        return None
    if c <= {"UK"}:
        return {"region": "UK", "timezone": "Europe/London"}
    if "Europe" in c or "Germany" in c or c & {"UK"}:
        return {"region": "EU", "timezone": "Europe/Berlin"}
    if "LATAM" in c:
        return {"region": "LATAM", "timezone": "America/Sao_Paulo"}
    return {"region": "other", "timezone": None}


def page_budget(region, years):
    if region in ("EU", "UK", "LATAM"):
        return 2 if years >= 3 else 1
    return 2 if years >= 8 else 1


def tz(prefs):
    try:
        return ZoneInfo(prefs.get("timezone") or str(config.TZ))
    except Exception:
        return config.TZ


def today(prefs):
    return dt.datetime.now(tz(prefs)).date()


def letter_date(prefs):
    d = dt.datetime.now(tz(prefs))
    if prefs.get("region") in ("EU", "UK", "LATAM", "other"):
        return f"{d.day} {d:%B %Y}"
    return f"{d:%B} {d.day}, {d.year}"
