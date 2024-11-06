from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
import pandas as pd
import http.client
import json
import time
import datetime
import threading

app = FastAPI()

# Airport data
airports = {
    "KORD": ("Chicago Intl", 41.97694028, -87.90814972),
    "KLAX": ("LOS ANGELES INTL", 33.94249639, -118.4080486),
    "KLAS": ("Las Vegas Intl", 36.08004389, -115.1522347),
    "KDFW": ("DALLAS-FORT WORTH, TX", 32.89723306, -97.03769472),
    "KSNA": ("SANTA ANA, CA", 33.67566194, -117.8682331),
    "KATL": ("Jackson Atlanta Intl, GA", 33.63669961, -84.427864),
    "KDEN": ("DENVER, CO", 39.86166667, -104.6731667),
    "KSFO": ("San Francisco Intl", 37.61880556, -122.3754167),
    "KPHX": ("PHOENIX, AZ", 33.43427778, -112.0115833),
    "KMDW": ("CHICAGO Midway INTL, IL", 41.78597222, -87.75241667),
    "KLGA": ("Laguardia NEW YORK, NY", 40.77725, -73.87261111),
    "KJFK": ("John F Kennedy NEW YORK, NY", 40.63992806, -73.77869222),
    "KPHL": ("PHILADELPHIA, PA", 39.87208389, -75.24066306),
    "KCLT": ("CHARLOTTE, NC", 35.21375, -80.94905556),
    "KHOU": ("HOUSTON, TX", 29.64579983, -95.27723158),
    "KBOS": ("BOSTON, MA", 42.36294444, -71.00638889),
    "VIDP": ("Delhi International Airport", 28.55616, 77.100281)
}

# Initialize containers
flight_data_container = {icao: {} for icao in airports.keys()}
time_taken_dict = {icao: {} for icao in airports.keys()}
on_ground_dict = {icao: {} for icao in airports.keys()}

# Initialize DataFrames
df_aircraft_taken_off = {icao: pd.DataFrame(columns=['Flight', 'ACFT_Type', 'Time', 'Status']) for icao in airports.keys()}
df_on_ground = {icao: pd.DataFrame(columns=['Flight', 'ACFT_Type', 'Time']) for icao in airports.keys()}

conn = http.client.HTTPSConnection("adsbexchange-com1.p.rapidapi.com")

headers = {
    'X-RapidAPI-Key': "a3d369739bmshe28db4d6c15add4p19d395jsnd5e7e69853",
    'X-RapidAPI-Host': "adsbexchange-com1.p.rapidapi.com"
}

def fetch_data(lat, lon):
    conn.request("GET", f"/v2/lat/{lat}/lon/{lon}/dist/10/", headers=headers)
    res = conn.getresponse()
    data = res.read()
    decoded_data = data.decode("utf-8")
    return json.loads(decoded_data)

def update_flight_data(icao, parsed_data):
    for aircraft in parsed_data.get('ac', []):
        registration = aircraft.get('flight')
        acft_type = aircraft.get('t')
        if registration and acft_type:  # Skip if type is empty
            if registration not in flight_data_container[icao]:
                flight_data_container[icao][registration] = []
            flight_data_container[icao][registration].append(aircraft)
            # Update time tracking
            update_time_tracking(icao, aircraft)

def update_time_tracking(icao, row):
    if 'now' in row:
        row['Timestamp'] = datetime.datetime.fromtimestamp(row['now'] / 1000)
    else:
        row['Timestamp'] = datetime.datetime.now()
    reg = row['flight']

    # Convert alt_baro to an integer
    alt_baro = row.get('alt_baro', 0)
    if isinstance(alt_baro, str):
        alt_baro = int(alt_baro) if alt_baro.isdigit() else 0

    # Track aircraft with gs > 1 and alt_baro <= 50
    if row.get('gs', 0) > 1 and alt_baro <= 50:
        if reg not in time_taken_dict[icao]:
            time_taken_dict[icao][reg] = {'start': None, 'end': None, 'Flight': reg, 'ACFT_Type': row.get('t')}
        if time_taken_dict[icao][reg]['start'] is None:
            time_taken_dict[icao][reg]['start'] = row['Timestamp']

    # End tracking when alt_baro > 50 and calculate delta
    if alt_baro > 50 and reg in time_taken_dict[icao] and time_taken_dict[icao][reg]['start'] is not None:
        time_taken_dict[icao][reg]['end'] = row['Timestamp']
        delta = time_taken_dict[icao][reg]['end'] - time_taken_dict[icao][reg]['start']
        if delta.total_seconds() > 0:
            time_taken = f"{delta.seconds // 3600}h {(delta.seconds // 60) % 60}m {delta.seconds % 60}s"
            end_time_str = time_taken_dict[icao][reg]['end'].strftime("%Y-%m-%d %H:%M:%S")
            status = f"TKOF at {end_time_str}"
            df_aircraft_taken_off[icao].loc[reg] = {'Flight': reg, 'ACFT_Type': row.get('t'), 'Time': time_taken, 'Status': status}
        del time_taken_dict[icao][reg]

    # Track aircraft with gs == 0 and alt_baro == 0
    if row.get('gs', 1) == 0 and alt_baro == 0:
        if reg not in on_ground_dict[icao]:
            on_ground_dict[icao][reg] = {'Flight': reg, 'ACFT_Type': row.get('t'), 'Time': 'On_Ground'}

    # Remove from on_ground_dict if conditions no longer met
    if (row.get('gs', 1) != 0 or alt_baro != 0) and reg in on_ground_dict[icao]:
        del on_ground_dict[icao][reg]

    # Update the on-ground DataFrame
    compute_on_ground(icao)

def compute_on_ground(icao):
    global on_ground_dict, df_on_ground
    df_on_ground[icao] = pd.DataFrame.from_dict(on_ground_dict[icao], orient='index')
    df_on_ground[icao] = df_on_ground[icao].drop_duplicates(subset=['Flight'])

def update_data():
    while True:
        for icao, (name, lat, lon) in airports.items():
            parsed_data = fetch_data(lat, lon)
            update_flight_data(icao, parsed_data)
            compute_on_ground(icao)
            # Print DataFrames to console every 1 minute
            if time.time() % 60 < 5:
                print(f"Aircraft Taken Off for {name}:")
                print(df_aircraft_taken_off[icao])
                print(f"On Ground Aircraft for {name}:")
                print(df_on_ground[icao])
        time.sleep(5)

@app.on_event("startup")
async def startup_event():
    threading.Thread(target=update_data, daemon=True).start()

@app.get("/", response_class=HTMLResponse)
async def root():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <title>Aircraft Taxiing Time</title>
    <style>
        body {
            background-color: #1f2128;
            font-family: Arial, sans-serif;
            color: #FFFFFF;
        }
        table {
            width: 80%;
            margin: 20px auto;
            border-collapse: separate;
            border-spacing: 0;
            background-color: #252834;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 8px 8px 16px #191a1f, 
                        -8px -8px 16px #2f313a;
        }
        th, td {
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid #333a45;
        }
        th {
            background-color: #FF69B4;
            color: #FFFFFF;
        }
        tr:nth-child(even) {
            background-color: #2f313a;
        }
        tr:hover {
            background-color: #2d303e;
        }
        #takeoff-table td {
            color: #FFA500;
        }
        #takeoff-table td:nth-child(1) {
            color: #FFA500;
        }
        #takeoff-table td:nth-child(3), #takeoff-table td:nth-child(4) {
            color: #FFA500;
        }
        #ground-table td {
            color: #FFFFFF;
        }
        #ground-table td:nth-child(1) {
            color: #28a745;
        }
        #ground-table td:nth-child(3) {
            color: #00BFFF;
        }
        #airport-dropdown {
            background-color: #252834;
            color: #FFA500;
            border: 1px solid #333a45;
            padding: 10px;
            font-size: 16px;
            border-radius: 5px;
        }
        #airport-dropdown option {
            background-color: #1f2128;
            color: #FFFFFF;
        }
    </style>
    <script>
    async function fetchData(icao) {
        const response = await fetch(`/dataframes?icao=${icao}`);
        const html = await response.text();
        document.getElementById('content').innerHTML = html;
    }

    function init() {
        const dropdown = document.getElementById('airport-dropdown');
        const selectedAirport = localStorage.getItem('selectedAirport');
        if (selectedAirport) {
            dropdown.value = selectedAirport;
            fetchData(selectedAirport);
        }
        dropdown.addEventListener('change', function() {
            const icao = dropdown.value;
            localStorage.setItem('selectedAirport', icao);
            fetchData(icao);
        });
    }
    window.onload = init;
    </script>
    </head>
    <body>
    <h1 style="text-align: center; color: #FFFFFF;">Airport Tracking</h1>
    <div style="text-align: center; margin-bottom: 20px;">
        <label for="airport-dropdown" style="color: #FFFFFF;">Select Airport: </label>
        <select id="airport-dropdown">
            <option value="KORD">Chicago Intl</option>
            <option value="KLAX">LOS ANGELES INTL</option>
            <option value="KLAS">Las Vegas Intl</option>
            <option value="KDFW">DALLAS-FORT WORTH, TX</option>
            <option value="KSNA">SANTA ANA, CA</option>
            <option value="KATL">Jackson Atlanta Intl, GA</option>
            <option value="KDEN">DENVER, CO</option>
            <option value="KSFO">San Francisco Intl</option>
            <option value="KPHX">PHOENIX, AZ</option>
            <option value="KMDW">CHICAGO Midway INTL, IL</option>
            <option value="KLGA">Laguardia NEW YORK, NY</option>
            <option value="KJFK">John F Kennedy NEW YORK, NY</option>
            <option value="KPHL">PHILADELPHIA, PA</option>
            <option value="KCLT">CHARLOTTE, NC</option>
            <option value="KHOU">HOUSTON, TX</option>
            <option value="KBOS">BOSTON, MA</option>
            <option value="VIDP">Delhi International Airport</option>
        </select>
    </div>
    <div id="content">
        <!-- Data will be loaded here -->
    </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/dataframes", response_class=HTMLResponse)
async def get_dataframes(icao: str = Query(...)):
    aircraft_taken_off_html = df_aircraft_taken_off[icao].to_html(classes='table table-striped', index=False)
    on_ground_html = df_on_ground[icao].to_html(classes='table table-striped', index=False)

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <title>DataFrames</title>
    <style>
        body {{
            background-color: #1f2128; /* Dark background */
            font-family: Arial, sans-serif;
            color: #28a745; /* Vivid Green text */
        }}
        table {{
            width: 80%;
            margin: 20px auto;
            border-collapse: separate;
            border-spacing: 0;
            background-color: #252834; /* Darker background for the table */
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 8px 8px 16px #191a1f, 
                        -8px -8px 16px #2f313a; /* Subtle 3D effect */
        }}
        th, td {{
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid #333a45; /* Even darker line for separation */
        }}
        th {{
            background-color: #2a2d3a; /* Slightly lighter background for headers */
            color: #FFA500; /* Bright orange text */
        }}
        tr:nth-child(even) {{
            background-color: #252834; /* Maintain the same color as the table background */
        }}
        tr:hover {{
            background-color: #2d303e; /* Slightly lighter for hover */
        }}
    </style>
    </head>
    <body>

    <h2 style="text-align: center; color: #fff;">Aircraft Taken Off</h2>
    {aircraft_taken_off_html}

    <h2 style="text-align: center; color: #fff;">On Ground Aircraft</h2>
    {on_ground_html}

    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
