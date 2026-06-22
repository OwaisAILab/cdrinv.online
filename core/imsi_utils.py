"""
IMSI Utilities – parse MCC+MNC from IMSI and lookup network from PLMN mapping.
"""
import os
import pandas as pd

_PLMN_DF = None

def load_plmn_database(filepath=None):
    """Load PLMN mapping CSV with columns: PLMN, Network."""
    global _PLMN_DF
    if _PLMN_DF is not None:
        return _PLMN_DF

    if filepath is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = [
            os.path.join(base_dir, 'data', 'plmn.csv'),
            os.path.join(base_dir, 'data', 'mcc_mnc.csv'),
            os.path.join(base_dir, 'plmn.csv'),
        ]
        for cand in candidates:
            if os.path.exists(cand):
                filepath = cand
                break
        else:
            print("⚠️  PLMN mapping file not found. Network info will be unavailable.")
            return None

    # Try multiple encodings
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'utf-16']
    df = None
    for enc in encodings:
        try:
            df = pd.read_csv(filepath, dtype=str, encoding=enc)
            print(f"✅ Read CSV with encoding: {enc}")
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"⚠️  Error reading CSV with {enc}: {e}")
            continue

    if df is None:
        print(f"⚠️  Failed to read CSV with any encoding.")
        return None

    # Normalise column names
    df.columns = [c.strip().lower() for c in df.columns]

    # Expect exactly two columns: plmn and network
    if 'plmn' not in df.columns or 'network' not in df.columns:
        raise ValueError("CSV must contain columns: 'PLMN' and 'Network'")

    # Clean PLMN (remove non‑digits)
    df['plmn'] = df['plmn'].astype(str).str.replace(r'\D', '', regex=True)
    # Drop rows with empty PLMN
    df = df[df['plmn'] != '']
    df = df.drop_duplicates(subset=['plmn'], keep='first')

    _PLMN_DF = df
    print(f"✅ Loaded PLMN database: {len(df)} entries")
    return _PLMN_DF


def parse_imsi(imsi):
    """
    Parse IMSI into MCC and MNC.
    Returns (mcc, mnc, full_imsi) or (None, None, None)
    """
    if not imsi:
        return None, None, None
    imsi = ''.join(filter(str.isdigit, str(imsi)))
    length = len(imsi)
    if length == 15:
        mcc = imsi[:3]
        mnc = imsi[3:5]
    elif length == 16:
        mcc = imsi[:3]
        mnc = imsi[3:6]
    else:
        return None, None, None
    return mcc, mnc, imsi


def lookup_network_from_plmn(mcc, mnc):
    """Look up network name from PLMN (MCC+MNC)."""
    if _PLMN_DF is None:
        return None
    plmn = f"{mcc}{mnc}"
    result = _PLMN_DF[_PLMN_DF['plmn'] == plmn]
    if result.empty:
        return None
    return result.iloc[0]['network']


def get_network_info_from_imsi(imsi):
    """
    Given an IMSI, return a dict: {imsi, mcc, mnc, network}.
    Returns None if not found.
    """
    mcc, mnc, full_imsi = parse_imsi(imsi)
    if not mcc or not mnc:
        return None
    network = lookup_network_from_plmn(mcc, mnc)
    if not network:
        return None
    return {
        'imsi': full_imsi,
        'mcc': mcc,
        'mnc': mnc,
        'network': network
    }