import os
import swisseph as swe

def init_ephemeris(ephe_path: str) -> None:
    """
    Configure Swiss Ephemeris to read data files from ephe_path.
    ephe_path must be a directory containing Swiss Ephemeris data files.
    """
    os.environ["SE_EPHE_PATH"] = ephe_path
    swe.set_ephe_path(ephe_path + os.sep)
