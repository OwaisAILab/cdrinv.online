import pandas as pd


# -----------------------------------
# CONTACT STRENGTH
# -----------------------------------
def get_contact_strength(
    total_calls,
    total_duration
):

    if total_calls >= 20:
        return "HIGH"

    elif total_calls >= 10:
        return "MEDIUM"

    return "LOW"


# -----------------------------------
# BUILD NETWORK DATA
# -----------------------------------
def build_network_data(df):

    if (
        "owner_number" not in df.columns
        or
        "contact_number" not in df.columns
    ):
        return {
            "nodes": [],
            "edges": []
        }

    nodes = {}
    edges = {}

    # -----------------------------------
    # OWNER NUMBER
    # -----------------------------------
    owner_number = None

    owner_series = (
        df["owner_number"]
        .replace("", pd.NA)
        .dropna()
    )

    if len(owner_series) > 0:

        owner_number = str(
            owner_series.iloc[0]
        )

    # -----------------------------------
    # NIGHT CONTACTS
    # -----------------------------------
    night_contacts = set()

    if "call_time" in df.columns:

        for _, row in df.iterrows():

            try:

                hour = int(
                    str(
                        row["call_time"]
                    )[0:2]
                )

                if hour >= 22 or hour <= 6:

                    night_contacts.add(
                        str(
                            row["contact_number"]
                        ).strip()
                    )

            except:
                pass

    # -----------------------------------
    # BUILD NODES / EDGES
    # -----------------------------------
    for _, row in df.iterrows():

        owner = str(
            row["owner_number"]
        ).strip()

        contact = str(
            row["contact_number"]
        ).strip()

        if owner == "" or contact == "":
            continue

        # OWNER NODE
        if owner not in nodes:

            nodes[owner] = {

                "id": owner,

                "label": owner,

                "calls": 0
            }

        # CONTACT NODE
        if contact not in nodes:

            nodes[contact] = {

                "id": contact,

                "label": contact,

                "calls": 0
            }

        nodes[owner]["calls"] += 1
        nodes[contact]["calls"] += 1

        key = (owner, contact)

        if key not in edges:

            edges[key] = {

                "from": owner,

                "to": contact,

                "calls": 0,

                "duration": 0
            }

        edges[key]["calls"] += 1

        try:

            duration = float(
                row.get(
                    "duration",
                    0
                )
            )

        except:

            duration = 0

        edges[key]["duration"] += duration

    # -----------------------------------
    # VIS NODES
    # -----------------------------------
    vis_nodes = []

    for node in nodes.values():

        node_id = node["id"]

        shape = "dot"
        size = 20
        title = ""

        # OWNER
        if node_id == owner_number:

            shape = "star"
            size = 50

            title = (
                "CDR OWNER"
            )

        # NIGHT CONTACT
        elif node_id in night_contacts:

            shape = "diamond"

            title = (
                "Night Contact"
            )

        vis_nodes.append({

            "id": node_id,

            "label": node["label"],

            "value": node["calls"],

            "shape": shape,

            "size": size,

            "title": title
        })

    # -----------------------------------
    # VIS EDGES
    # -----------------------------------
    vis_edges = []

    for edge in edges.values():

        strength = get_contact_strength(

            edge["calls"],

            edge["duration"]
        )

        if strength == "HIGH":

            color = "red"

        elif strength == "MEDIUM":

            color = "orange"

        else:

            color = "gray"

        vis_edges.append({

            "from":
                edge["from"],

            "to":
                edge["to"],

            "value":
                edge["calls"],

            "color":
                color,

            "title":
                (
                    f"Calls: {edge['calls']}<br>"
                    f"Duration: {int(edge['duration'])} sec<br>"
                    f"Relationship: {strength}"
                )
        })

    # -----------------------------------
    # TOP ASSOCIATES
    # -----------------------------------
    associates = []

    for edge in edges.values():

        associates.append({

            "number":
                edge["to"],

            "calls":
                edge["calls"],

            "duration_seconds":
                int(
                    edge["duration"]
                ),

            "strength":
                get_contact_strength(
                    edge["calls"],
                    edge["duration"]
                )
        })

    associates = sorted(

        associates,

        key=lambda x:

        (
            x["calls"],
            x["duration_seconds"]
        ),

        reverse=True
    )

    return {

        "nodes":
            vis_nodes,

        "edges":
            vis_edges,

        "top_associates":
            associates[:20]
    }