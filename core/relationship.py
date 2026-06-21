import pandas as pd









# -----------------------------------
# DIRECT RELATIONSHIP
# -----------------------------------
def direct_contacts(df1, df2):
    required = ["owner_number", "contact_number"]
    if not all(col in df1.columns for col in required) or not all(col in df2.columns for col in required):
        return {"error": "Missing required columns"}
    
    required_columns = [
        "owner_number",
        "contact_number"
    ]

    for col in required_columns:

        if (
            col not in df1.columns
            or
            col not in df2.columns
        ):
            return {
                "error": f"Missing column: {col}"
            }

    owner_1_list = (
        df1["owner_number"]
        .replace("", pd.NA)
        .dropna()
        .unique()
    )

    owner_2_list = (
        df2["owner_number"]
        .replace("", pd.NA)
        .dropna()
        .unique()
    )

    if len(owner_1_list) == 0:

        return {
            "error": "CDR 1 owner not found"
        }

    if len(owner_2_list) == 0:

        return {
            "error": "CDR 2 owner not found"
        }

    owner_1 = str(owner_1_list[0])
    owner_2 = str(owner_2_list[0])

    calls_1_to_2 = df1[
        df1["contact_number"] == owner_2
    ]

    calls_2_to_1 = df2[
        df2["contact_number"] == owner_1
    ]

    duration_1 = pd.to_numeric(
        calls_1_to_2["duration"],
        errors="coerce"
    ).fillna(0).sum()

    duration_2 = pd.to_numeric(
        calls_2_to_1["duration"],
        errors="coerce"
    ).fillna(0).sum()

    # ── IMEI-switch context ────────────────────────────────────────
    # Surface whether either number changed handsets during the
    # period covered by this CDR — useful context for investigators
    # when evaluating a relationship.
    cdr_1_imei_switches = 0
    cdr_2_imei_switches = 0

    if "imei_switch" in df1.columns:
        cdr_1_imei_switches = int(df1["imei_switch"].sum())

    if "imei_switch" in df2.columns:
        cdr_2_imei_switches = int(df2["imei_switch"].sum())

    return {

        "cdr_1_owner": owner_1,

        "cdr_2_owner": owner_2,

        "cdr_1_to_cdr_2_calls": int(len(calls_1_to_2)),

        "cdr_2_to_cdr_1_calls": int(len(calls_2_to_1)),

        "cdr_1_to_cdr_2_duration_seconds": int(duration_1),

        "cdr_2_to_cdr_1_duration_seconds": int(duration_2),

        "cdr_1_imei_switches": cdr_1_imei_switches,

        "cdr_2_imei_switches": cdr_2_imei_switches,

        "direct_relationship": (
            len(calls_1_to_2) > 0
            or
            len(calls_2_to_1) > 0
        )
    }
# -----------------------------------
# FORMAT DURATION
# -----------------------------------
def format_duration(seconds):

    try:

        seconds = int(seconds)

        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        return f"{hours:02}:{minutes:02}:{secs:02}"

    except:

        return "00:00:00"


# -----------------------------------
# RELATIONSHIP SCORE ENGINE
# -----------------------------------
def relationship_score_engine(df1, df2, direct_relation, common_contacts, meetings):
    # no column access inside, so no check needed here
    pass

    score = 0

    reasons = []

    # -----------------------------------
    # DIRECT RELATIONSHIP
    # -----------------------------------
    if direct_relation.get(
        "direct_relationship"
    ):

        score += 40

        reasons.append(
            "Direct communication detected"
        )

    # -----------------------------------
    # DIRECT CALL COUNT
    # -----------------------------------
    total_direct_calls = (

        direct_relation.get(
            "cdr_1_to_cdr_2_calls",
            0
        )

        +

        direct_relation.get(
            "cdr_2_to_cdr_1_calls",
            0
        )
    )

    if total_direct_calls >= 5:

        score += 20

        reasons.append(
            "Frequent direct calls"
        )

    elif total_direct_calls >= 1:

        score += 10

        reasons.append(
            "Limited direct calls"
        )

    # -----------------------------------
    # SAME TOWER MEETINGS
    # -----------------------------------
    total_meetings = len(meetings)

    if total_meetings >= 5:

        score += 30

        reasons.append(
            "Multiple same tower meetings"
        )

    elif total_meetings >= 1:

        score += 15

        reasons.append(
            "Possible physical meetings"
        )

    # -----------------------------------
    # COMMON CONTACTS
    # -----------------------------------
    common_count = len(common_contacts)

    if common_count >= 10:

        score += 20

        reasons.append(
            "Large shared contact network"
        )

    elif common_count >= 3:

        score += 10

        reasons.append(
            "Shared contact network"
        )

    # -----------------------------------
    # NIGHT ACTIVITY
    # -----------------------------------
    night_calls = 0

    if "call_time" in df1.columns:

        for _, row in df1.iterrows():

            try:

                hour = int(
                    str(
                        row["call_time"]
                    )[0:2]
                )

                if (
                    hour >= 22
                    or
                    hour <= 6
                ):

                    night_calls += 1

            except:
                pass

    if night_calls >= 5:

        score += 20

        reasons.append(
            "Frequent night activity"
        )

    elif night_calls >= 1:

        score += 10

        reasons.append(
            "Night communication observed"
        )

    # -----------------------------------
    # TOTAL DURATION
    # -----------------------------------
    total_duration = (

        direct_relation.get(
            "cdr_1_to_cdr_2_duration_seconds",
            0
        )

        +

        direct_relation.get(
            "cdr_2_to_cdr_1_duration_seconds",
            0
        )
    )

    if total_duration >= 3600:

        score += 20

        reasons.append(
            "Long communication duration"
        )

    elif total_duration >= 300:

        score += 10

        reasons.append(
            "Moderate communication duration"
        )

    # -----------------------------------
    # IMEI SWITCH CONTEXT (informational)
    # -----------------------------------
    cdr_1_switches = direct_relation.get("cdr_1_imei_switches", 0)
    cdr_2_switches = direct_relation.get("cdr_2_imei_switches", 0)

    if cdr_1_switches > 0 or cdr_2_switches > 0:

        reasons.append(
            "Handset (IMEI) change detected during CDR period — "
            f"CDR1: {cdr_1_switches}, CDR2: {cdr_2_switches}"
        )

    # -----------------------------------
    # LIMIT SCORE
    # -----------------------------------
    if score > 100:

        score = 100

    # -----------------------------------
    # RELATIONSHIP LEVEL
    # -----------------------------------
    if score >= 75:

        level = "HIGH"

    elif score >= 40:

        level = "MEDIUM"

    else:

        level = "LOW"

    return {

        "relationship_score":
            score,

        "relationship_level":
            level,

        "reasons":
            reasons,

        "total_direct_calls":
            total_direct_calls,

        "total_possible_meetings":
            total_meetings,

        "common_contacts":
            common_count,

        "total_direct_duration":
            format_duration(
                total_duration
            )
    }


# -----------------------------------
# FORMAT SCORE
# -----------------------------------
def classify_risk(score):

    if score >= 70:
        return "HIGH"

    if score >= 40:
        return "MEDIUM"

    return "LOW"


# -----------------------------------
# RELATIONSHIP ANALYSIS
# -----------------------------------
def relationship_intelligence(df):
    required = ["contact_number", "duration", "call_time"]
    if not all(col in df.columns for col in required):
        return []
    
    required_columns = [

        "contact_number",
        "duration",
        "call_time"
    ]

    for col in required_columns:

        if col not in df.columns:

            return []

    temp = df.copy()

    temp["duration"] = pd.to_numeric(

        temp["duration"],
        errors="coerce"

    ).fillna(0)

    results = []

    contacts = (

        temp["contact_number"]
        .dropna()
        .unique()
    )

    for contact in contacts:

        person = temp[

            temp["contact_number"]
            == contact
        ]

        total_calls = len(person)

        total_duration = (

            person["duration"]
            .sum()
        )

        # ------------------------
        # NIGHT CONTACT SCORE
        # ------------------------
        night_calls = 0

        for _, row in person.iterrows():

            try:

                hour = int(
                    str(
                        row["call_time"]
                    )[0:2]
                )

                if (
                    hour >= 22
                    or
                    hour <= 6
                ):

                    night_calls += 1

            except:
                pass

        # ------------------------
        # SCORING
        # ------------------------
        score = 0

        # call frequency
        if total_calls >= 20:
            score += 25

        elif total_calls >= 10:
            score += 15

        elif total_calls >= 5:
            score += 10

        # duration
        if total_duration >= 3600:
            score += 25

        elif total_duration >= 1800:
            score += 15

        elif total_duration >= 600:
            score += 10

        # night activity
        if night_calls >= 10:
            score += 30

        elif night_calls >= 5:
            score += 20

        elif night_calls >= 1:
            score += 10

        # ------------------------
        # IMEI SWITCH CONTEXT
        # ------------------------
        imei_switches_during_contact = 0

        if "imei_switch" in person.columns:

            imei_switches_during_contact = int(
                person["imei_switch"].sum()
            )

        results.append({

            "contact_number":
                contact,

            "total_calls":
                int(total_calls),

            "total_duration_seconds":
                int(total_duration),

            "night_calls":
                int(night_calls),

            "imei_switches_during_contact":
                imei_switches_during_contact,

            "relationship_score":
                int(score),

            "risk_level":
                classify_risk(score)
        })

    results = sorted(

        results,

        key=lambda x:
        x["relationship_score"],

        reverse=True
    )

    return results