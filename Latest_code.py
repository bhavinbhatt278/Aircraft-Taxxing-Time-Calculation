from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import pandas as pd
import http.client
import json
import time
import datetime
import threading

app = FastAPI()

# Initialize containers
flight_data_container = {}
time_taken_dict = {}
on_ground_dict = {}

# Initialize DataFrames
df_aircraft_taken_off = pd.DataFrame(columns=['Flight', 'ACFT_Type', 'Time', 'Status'])
df_on_ground = pd.DataFrame(columns=['Flight', 'ACFT_Type', 'Time'])

conn = http.client.HTTPSConnection("adsbexchange-com1.p.rapidapi.com")

headers = {
    'X-RapidAPI-Key': "******************************",
    'X-RapidAPI-Host': "adsbexchange-com1.p.rapidapi.com"
}


def fetch_data():
    conn.request("GET", "/v2/lat/28.556160/lon/77.100281/dist/10/", headers=headers)
    res = conn.getresponse()
    data = res.read()
    decoded_data = data.decode("utf-8")
    return json.loads(decoded_data)


def update_flight_data(parsed_data):
    global flight_data_container
    for aircraft in parsed_data.get('ac', []):
        registration = aircraft.get('flight')
        acft_type = aircraft.get('t')
        if registration and acft_type:  # Skip if type is empty
            if registration not in flight_data_container:
                flight_data_container[registration] = []
            flight_data_container[registration].append(aircraft)
            # Update time tracking
            update_time_tracking(aircraft)


def update_time_tracking(row):
    global time_taken_dict, on_ground_dict, df_aircraft_taken_off, df_on_ground
    if 'now' in row:
        row['Timestamp'] = datetime.datetime.fromtimestamp(row['now'] / 1000)
    else:
        row['Timestamp'] = datetime.datetime.now()
    reg = row['flight']

    # Convert alt_baro to an integer
    if isinstance(row['alt_baro'], str):
        alt_baro = int(row['alt_baro']) if row['alt_baro'].isdigit() else 0
    else:
        alt_baro = row['alt_baro']

    # Track aircraft with gs > 1 and alt_baro <= 50
    if row.get('gs', 0) > 1 and alt_baro <= 50:
        if reg not in time_taken_dict:
            time_taken_dict[reg] = {'start': None, 'end': None, 'Flight': reg, 'ACFT_Type': row.get('t')}
        if time_taken_dict[reg]['start'] is None:
            time_taken_dict[reg]['start'] = row['Timestamp']

    # End tracking when alt_baro > 50 and calculate delta
    if alt_baro > 50 and reg in time_taken_dict and time_taken_dict[reg]['start'] is not None:
        time_taken_dict[reg]['end'] = row['Timestamp']
        delta = time_taken_dict[reg]['end'] - time_taken_dict[reg]['start']
        if delta.total_seconds() > 0:
            time_taken = f"{delta.seconds // 3600}h {(delta.seconds // 60) % 60}m {delta.seconds % 60}s"
            end_time_str = time_taken_dict[reg]['end'].strftime("%Y-%m-%d %H:%M:%S")
            status = f"TKOF at {end_time_str}"
            df_aircraft_taken_off.loc[reg] = {'Flight': reg, 'ACFT_Type': row.get('t'), 'Time': time_taken, 'Status': status}
        del time_taken_dict[reg]

    # Track aircraft with gs == 0 and alt_baro == 0
    if row.get('gs', 1) == 0 and alt_baro == 0:
        if reg not in on_ground_dict:
            on_ground_dict[reg] = {'Flight': reg, 'ACFT_Type': row.get('t'), 'Status': 'On_Ground'}

    # Remove from on_ground_dict if conditions no longer met
    if (row.get('gs', 1) != 0 or alt_baro != 0) and reg in on_ground_dict:
        del on_ground_dict[reg]

    # Update the on-ground DataFrame
    compute_on_ground()


def compute_on_ground():
    global on_ground_dict, df_on_ground
    df_on_ground = pd.DataFrame.from_dict(on_ground_dict, orient='index')
    df_on_ground = df_on_ground.drop_duplicates(subset=['Flight'])


def update_data():
    global df_aircraft_taken_off, df_on_ground
    while True:
        parsed_data = fetch_data()
        update_flight_data(parsed_data)
        compute_on_ground()
        # Print DataFrames to console every 1 minute
        if time.time() % 60 < 5:
            print("Aircraft Taken Off:")
            print(df_aircraft_taken_off)
            print("On Ground Aircraft:")
            print(df_on_ground)
        time.sleep(5)


@app.on_event("startup")
async def startup_event():
    threading.Thread(target=update_data, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
async def root():
    return "<h1>Welcome to the Flight Tracking API</h1><p>Use the <a href='/dataframes'>/dataframes</a> endpoint to view the report.</p>"


@app.get("/dataframes", response_class=HTMLResponse)
async def get_dataframes():
    aircraft_taken_off_html = df_aircraft_taken_off.to_html(classes='table table-striped', index=False)
    on_ground_html = df_on_ground.to_html(classes='table table-striped', index=False)

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
