from typing import Dict
from .constants import SIGNS

def norm360(x: float) -> float:
    return x % 360.0

def sign_index(lon: float) -> int:
    return int(norm360(lon) // 30)

def deg_in_sign(lon: float) -> float:
    return norm360(lon) % 30.0

# Existing formatter (kept): truncates minutes (Astro-Seek style)
def format_deg_sign(lon: float) -> str:
    sidx = sign_index(lon)
    deg = deg_in_sign(lon)
    deg_i = int(deg)
    minutes = int((deg - deg_i) * 60)
    return f"{deg_i}°{minutes:02d}' {SIGNS[sidx]}"

def whole_sign_house_for_lon(lon: float, asc_sign_idx: int) -> int:
    p_sign = sign_index(lon)
    return ((p_sign - asc_sign_idx) % 12) + 1

def planet_payload(lon: float, asc_sign_idx: int) -> Dict:
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

def format_lon_ddmmss_sign(lon: float) -> str:
    lon = norm360(lon)
    sidx = sign_index(lon)
    sign = SIGNS[sidx]

    within = lon - (sidx * 30.0)
    deg = int(within)
    minutes_full = (within - deg) * 60.0
    minutes = int(minutes_full)

    seconds_full = (minutes_full - minutes) * 60.0
    
# ROUND HALF UP (only for seconds)
    sec = int(seconds_full + 0.5)

    # rollover only if seconds hit 60
    if sec == 60:
        sec = 0
        minute += 1

    if minute == 60:
        minute = 0
        deg += 1

    if deg == 30:
        deg = 0
        sidx = (sidx + 1) % 12
        sign = SIGNS[sidx]

    return f"{deg}°{minute:02d}′{sec:02d}″ {sign}"
