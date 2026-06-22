"""
TAC Utilities – extract TAC from IMEI and lookup device brand & model from TAC database.
"""
import os
import pandas as pd

_TAC_DF = None

def load_tac_database(filepath=None):
    """Load TAC CSV with columns: GSMA TAC, Brand Name, Mobile Device, etc."""
    global _TAC_DF
    if _TAC_DF is not None:
        return _TAC_DF

    if filepath is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates = [
            os.path.join(base_dir, 'data', 'tacs.csv'),
            os.path.join(base_dir, 'data', 'tac.csv'),
            os.path.join(base_dir, 'tacs.csv'),
        ]
        for cand in candidates:
            if os.path.exists(cand):
                filepath = cand
                break
        else:
            print("⚠️  TAC database file not found. Device info will be unavailable.")
            return None

    # Try multiple encodings
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'utf-16']
    df = None
    for enc in encodings:
        try:
            df = pd.read_csv(filepath, dtype=str, encoding=enc)
            print(f"✅ Read TAC CSV with encoding: {enc}")
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"⚠️  Error reading TAC CSV with {enc}: {e}")
            continue

    if df is None:
        print("⚠️  Failed to read TAC CSV with any encoding.")
        return None

    # Normalise column names
    df.columns = [c.strip().lower() for c in df.columns]

    # Identify required columns
    tac_col = None
    brand_col = None
    model_col = None
    for col in df.columns:
        if col in ('gsma tac', 'tac', 'type allocation code', 'code'):
            tac_col = col
        elif col in ('brand name', 'brand', 'manufacturer', 'menufacturer'):
            brand_col = col
        elif col in ('mobile device', 'model', 'model as per gsma', 'device'):
            model_col = col

    if tac_col is None:
        raise ValueError("TAC CSV must contain a column like 'GSMA TAC' or 'TAC'")
    if brand_col is None or model_col is None:
        print("⚠️  Brand or Model column not found; will use available columns.")

    # Keep only needed columns
    keep_cols = [tac_col]
    if brand_col:
        keep_cols.append(brand_col)
    if model_col:
        keep_cols.append(model_col)
    df = df[keep_cols].copy()

    # Rename to standard names
    rename_map = {tac_col: 'tac'}
    if brand_col:
        rename_map[brand_col] = 'brand'
    if model_col:
        rename_map[model_col] = 'model'
    df = df.rename(columns=rename_map)

    # Clean TAC (remove non‑digits)
    df['tac'] = df['tac'].astype(str).str.replace(r'\D', '', regex=True)
    # Keep only 8‑digit TACs
    df = df[df['tac'].str.len() == 8]
    df = df.drop_duplicates(subset=['tac'], keep='first')

    _TAC_DF = df
    print(f"✅ Loaded TAC database: {len(df)} entries")
    return _TAC_DF


def lookup_device(tac):
    """Return (brand, model) for a given 8‑digit TAC."""
    if not tac or _TAC_DF is None:
        return None, None
    tac = str(tac).strip()
    if not tac.isdigit() or len(tac) != 8:
        return None, None
    result = _TAC_DF[_TAC_DF['tac'] == tac]
    if result.empty:
        return None, None
    row = result.iloc[0]
    brand = row.get('brand')
    model = row.get('model')
    return brand, model


def get_device_info_from_imei(imei):
    """
    Extract TAC from IMEI and lookup device info.
    ALWAYS returns a dict with brand/model (Unknown if not found).
    Returns None only if IMEI is invalid (<8 digits).
    """
    if not imei:
        return None
    imei = ''.join(filter(str.isdigit, str(imei)))
    if len(imei) < 8:
        return None
    tac = imei[:8]
    brand, model = lookup_device(tac)
    # Always return a dict, even if not found
    return {
        'imei': imei,
        'tac': tac,
        'brand': brand if brand else 'Unknown',
        'model': model if model else 'Unknown'
    }