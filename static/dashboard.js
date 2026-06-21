fetch("/dashboard-data")

.then(r => r.json())

.then(data => {

    buildSummary(data);

    buildResidence(data);

    buildWorkplace(data);

    buildMovement(data);

    buildRelationship(data);

    buildContacts(data);

});
function buildSummary(data){

    document.getElementById(
        "summary"
    ).innerHTML = `

        <h3>
            Records:
            ${data.summary.records}
        </h3>

        <h3>
            Contacts:
            ${data.summary.contacts}
        </h3>

        <h3>
            Towers:
            ${data.summary.towers}
        </h3>
    `;
}
function buildResidence(data){

    let html = "";

    data.residence
    .slice(0,2)
    .forEach(zone => {

        html += `

        <div>

            <b>Tower:</b>
            ${zone.tower_address}

            <br>

            <b>Sector:</b>
            ${zone.sector}

            <br>

            <b>Score:</b>
            ${zone.score}

            <br><br>

        </div>
        `;
    });

    html += `
        <a href="/residence-map">
            Open Residence Map
        </a>
    `;

    document.getElementById(
        "residence"
    ).innerHTML = html;
}
function buildWorkplace(data){

    let html = "";

    data.workplace
    .slice(0,5)
    .forEach((row,index)=>{

        html += `

        <div>

            <b>#${index+1}</b><br>

            ${row.tower_address}

            <br>

            Visits:
            ${row.visits}

            <br><br>

        </div>

        `;
    });

    document.getElementById(
        "workplace"
    ).innerHTML = html;
}

function buildMovement(data){

    let m = data.movement_radius;

    let html = `

    <h4>
        Max Distance:
        ${m.max_distance_km} km
    </h4>

    <h4>
        Average Distance:
        ${m.average_distance_km} km
    </h4>

    <h4>
        Travel Type:
        ${m.travel_type}
    </h4>

    <a href="/map">
        Open Movement Map
    </a>

    <hr>

    <h4>
        Top Routes
    </h4>

    `;

    data.route_frequency
    .slice(0,10)
    .forEach(route=>{

        html += `

        <div>

            ${route.from}

            <br>

            ↓

            <br>

            ${route.to}

            <br>

            Frequency:
            ${route.frequency}

            <br><br>

        </div>

        `;
    });

    document.getElementById(
        "movement"
    ).innerHTML = html;
}
function buildRelationship(data){

    let html = "";

    data.relationship
    .slice(0,10)
    .forEach(row=>{

        html += `

        <div>

            <b>${row.contact_number}</b>

            <br>

            Calls:
            ${row.total_calls}

            <br>

            Night Calls:
            ${row.night_calls}

            <br>

            Score:
            ${row.relationship_score}

            <br>

            Risk:
            ${row.risk_level}

            <br><br>

        </div>

        `;
    });

    document.getElementById(
        "relationship"
    ).innerHTML = html;
}

function buildContacts(data){

    let html = `

    <table border="1">

        <tr>

            <th>Contact Number</th>

            <th>Calls</th>

            <th>Duration</th>
            <th>Night Calls</th>
            <th>Risk</th>

        </tr>
    `;

    data.top_contacts.forEach(row => {

        html += `

        <tr>

            <td>${row.contact_number}</td>

            <td>${row.total_calls}</td>

            <td>${row.total_duration}</td>
            <td>${row.night_calls ?? '-'}</td>
            <td>${row.risk_level ?? '-'}</td>

        </tr>
        `;
    });

    html += "</table>";

    document.getElementById(
        "contacts"
    ).innerHTML = html;
}
// Date range is now handled inline in dashboard.html filterMapByDate section