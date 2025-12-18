from fastapi import FastAPI, HTTPException
import os
import swisseph as swe

app = FastAPI()

# Swiss Ephemeris setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EPHE_PATH = os.path.join(BASE_DIR, "ephe")

# Make it extra explicit for Swiss Ephemeris
os.environ["SE_EPHE_PATH"] = EPHE_PATH
swe.set_ephe_path(EPHE_PATH + os.sep)  # trailing slash helps sometimes

@app.get("/debug/ephe")
def debug_ephe():
    return {
        "base_dir": BASE_DIR,
        "ephe_path": EPHE_PATH,
        "ephe_exists": os.path.isdir(EPHE_PATH),
        "ephe_files": sorted(os.listdir(EPHE_PATH)) if os.path.isdir(EPHE_PATH) else [],
        "cwd": os.getcwd(),
    }


# -----------------------------
# Constants
# -----------------------------
SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

BODIES = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mercury": swe.MERCURY,
    "venus": swe.VENUS,
    "mars": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn": swe.SATURN,
    "uranus": swe.URANUS,
    "neptune": swe.NEPTUNE,
    "pluto": swe.PLUTO,

    # Extras
    "chiron": swe.CHIRON,

    # Nodes
    "north_node_true": swe.TRUE_NODE,
    "north_node_mean": swe.MEAN_NODE,
}

AYANAMSA_MAP = {
    "fagan_bradley": swe.SIDM_FAGAN_BRADLEY,
    "lahiri": swe.SIDM_LAHIRI,
    "krishnamurti": swe.SIDM_KRISHNAMURTI,
}

# -----------------------------
# Helpers
# -----------------------------
def norm360(x):
    return x % 360.0

def sign_index(lon):
    return int(norm360(lon) // 30)

def deg_in_sign(lon):
    return norm360(lon) % 30.0

def format_deg_sign(lon):
    sidx = sign_index(lon)
    deg = deg_in_sign(lon)
    deg_i = int(deg)
    minutes = int((deg - deg_i) * 60)
    return f"{deg_i}°{minutes:02d}' {SIGNS[sidx]}"

def whole_sign_house_for_lon(lon, asc_sign_idx):
    p_sign = sign_index(lon)
    return ((p_sign - asc_sign_idx) % 12) + 1

def planet_payload(lon, asc_sign_idx):
    lon = norm360(lon)
    sidx = sign_index(lon)
    house = whole_sign_house_for_lon(lon, asc_sign_idx)
    return {
        "longitude": float(lon),
        "sign": SIGNS[sidx],
        "deg_in_sign": float(deg_in_sign(lon)),
        "house_whole_sign": int(house),
        "display": f"{format_deg_sign(lon)} (House {house})",
    }

# -----------------------------
# Routes
# -----------------------------
@app.get("/")
def home():
    return {"status": "Swiss API is running"}

@app.get("/chart")
def chart(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: float = 0.0,
    lat: float = 0.0,
    lon: float = 0.0,
    zodiac: str = "tropical",          # "tropical" or "sidereal"
    ayanamsa: str = "fagan_bradley",   # used if zodiac="sidereal"
):
    try:
        # 1) Julian Day (UTC)
        h_float = hour + minute / 60.0 + second / 3600.0
        jd = swe.julday(year, month, day, h_float)

        # 2) Angles (computed in tropical; then converted to sidereal if needed)
        _, ascmc = swe.houses_ex(jd, lat, lon, b"P")
        asc_trop = norm360(ascmc[0])
        mc_trop = norm360(ascmc[1])

        zodiac = (zodiac or "tropical").lower().strip()
        ay_deg = None

        if zodiac == "sidereal":
            if ayanamsa not in AYANAMSA_MAP:
                raise ValueError(f"Unknown ayanamsa '{ayanamsa}'. Use one of: {list(AYANAMSA_MAP.keys())}")

            swe.set_sid_mode(AYANAMSA_MAP[ayanamsa], 0, 0)
            ay_deg = float(swe.get_ayanamsa_ut(jd))

            asc = norm360(asc_trop - ay_deg)
            mc = norm360(mc_trop - ay_deg)
            flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
        else:
            asc = asc_trop
            mc = mc_trop
            flags = swe.FLG_SWIEPH

        dsc = norm360(asc + 180.0)
        ic = norm360(mc + 180.0)

        asc_sign_idx = sign_index(asc)
        asc_sign_name = SIGNS[asc_sign_idx]
        mc_sign_name = SIGNS[sign_index(mc)]

        # 3) Whole Sign houses (by sign)
        houses = []
        for h in range(1, 13):
            sidx = (asc_sign_idx + h - 1) % 12
            houses.append({
                "house": h,
                "sign": SIGNS[sidx],
                "cusp_longitude": float(sidx * 30.0),
            })

        # 4) Bodies (planets, chiron, nodes)
        bodies_out = {}
        south_nodes_to_add = {}

        for name, code in BODIES.items():
            lon_ecl = norm360(swe.calc_ut(jd, code, flags)[0][0])
            bodies_out[name] = planet_payload(lon_ecl, asc_sign_idx)

            # Auto-create South Nodes
            if name == "north_node_true":
                south_lon = norm360(lon_ecl + 180.0)
                south_nodes_to_add["south_node_true"] = planet_payload(south_lon, asc_sign_idx)
            if name == "north_node_mean":
                south_lon = norm360(lon_ecl + 180.0)
                south_nodes_to_add["south_node_mean"] = planet_payload(south_lon, asc_sign_idx)

        bodies_out.update(south_nodes_to_add)

        return {
            "jd_utc": float(jd),
            "timezone": "UTC",
            "location": {"lat": float(lat), "lon": float(lon)},
            "zodiac": zodiac,
            "ayanamsa": {
                "name": ayanamsa if zodiac == "sidereal" else None,
                "degrees": ay_deg,
            },
            "angles": {
                "asc": float(asc),
                "asc_sign": asc_sign_name,
                "dsc": float(dsc),
                "mc": float(mc),
                "mc_sign": mc_sign_name,
                "ic": float(ic),
            },
            "houses_whole_sign": houses,
            "bodies": bodies_out,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
