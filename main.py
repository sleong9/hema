import streamlit as st
import sqlite3
import pandas as pd
import requests

import math
from datetime import datetime, timedelta, timezone

# Database Connection
def connect_to_database():
    return sqlite3.connect('your_database.db')

def close_database_connection(conn):
    conn.close()

# Medication Check
def has_medication(user):
    conn = connect_to_database()
    cursor = conn.cursor()
    cursor.execute("SELECT DESCRIPTION FROM medications WHERE PATIENT = ? AND (DESCRIPTION LIKE ? OR DESCRIPTION LIKE ?)",
                   (user, "%metformin%", "%aspirin%"))
    result = cursor.fetchone()
    close_database_connection(conn)
    return result is not None

# User Authentication
def authenticate_user(username, password):
    conn = connect_to_database()
    cursor = conn.cursor()
    cursor.execute("SELECT username, password, rank, patient_id FROM users WHERE username = ? AND password = ?", (username, password))
    result = cursor.fetchone()
    close_database_connection(conn)
    if result:
        _, _, rank, patient_id = result  # Unpack the result
        return True, username, rank, patient_id
    else:
        return False, None, None

# Save User Data
def save_user_data(user, rest_minutes, work_minutes, activity_taken, urine_color, location, uniform_type, medication, input_date):
    conn = connect_to_database()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_data (id INTEGER PRIMARY KEY, user TEXT, rest_minutes INTEGER, work_minutes INTEGER, activity TEXT,urine TEXT, location TEXT, uniform TEXT, medication TEXT, input_date TEXT)
    ''')
    cursor.execute("INSERT INTO user_data (user, rest_minutes, work_minutes, activity, urine, location, uniform, medication, input_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (user, rest_minutes, work_minutes, activity_taken, urine_color, location, uniform_type, medication, input_date))
    conn.commit()
    close_database_connection(conn)

def calculate_WBGT(T, rh):
    # Convert rh from percentage to fraction
    Tw = T * math.atan(0.151977 * (rh + 8.313659)**0.5) + math.atan(T + rh) - math.atan(rh - 1.676331) + 0.00391838 * (rh**1.5) * math.atan(0.023101 * rh) - 4.686035
    Tg = 17.68 + T * 0.993 - (0.0737 * 2.5) - (0.754 * rh / 100)
    WBGT = (0.7 * Tw) + (0.2 * Tg) + (0.1 * T)
    return WBGT

def classify_heat_risk(wbgt):
    if wbgt <= 29.9:
        return "White"
    elif 30.0 <= wbgt <= 30.9:
        return "Green"
    elif 31.0 <= wbgt <= 31.9:
        return "Yellow"
    elif 32.0 <= wbgt <= 32.9:
        return "Red"
    elif wbgt >= 33.0:
        return "Black"
    else:
        return "Undefined"

def classify_wbgt_min_excerise(wbgt):
    if wbgt <= 29.9:
        return 60
    elif 30.0 <= wbgt <= 30.9:
        return 45
    elif 31.0 <= wbgt <= 32.9:
        return 30
    elif wbgt >= 33.0:
        return 15
    else:
        return "Undefined"

def classify_urine_risk(urine_color):
    if isinstance(urine_color, str):
        if urine_color == "Clear":
            return 0
        elif urine_color == "Pale Yellow":
            return 0.5
        elif urine_color == "Dark Brown":
            return 5
        else:
            return 0  # Return 0 for other cases (or any suitable default value)
    else:
        # If it's a Pandas Series, use apply to process each element
        return urine_color.apply(lambda x: 0 if x == "Clear" else (0.5 if x == "Pale Yellow" else (5 if x == "Dark Brown" else 0)))

def classify_uniform_risk(uniform_type):
    if isinstance(uniform_type, str):
        if uniform_type == "PT Kit":
            return 0
        elif uniform_type == "Full Battle Order":
            return 3
        else:
            return 0  # Return 0 for other cases (or any suitable default value)
    else:
        # If it's a Pandas Series, use apply to process each element
        return uniform_type.apply(lambda x: 0 if x == "PT Kit" else (3 if x == "Full Battle Order" else 0))
def classify_camp_code(location):
    if location == "Changi Camp":
        return "S24"
    if location == "Clementi Camp":
        return "S50"
    else:
        return "Undefined"

def is_work_rest_ratio_within_recommended(work, wbgt, inputted_ratio):
    # Define the recommended work/rest ratios based on Work and WBGT thresholds
    recommended_ratios = {
        "Light": {
            (0, 29.9): 0.25,
            (30.0, 30.9): 0.33,
            (31.0, 31.9): 0.5,
            (32.0, 32.9): 1.0,
            (33.0, float('inf')): 2.0
        },
        "Moderate": {
            (0, 29.9): 0.5,
            (29.9, 30.9): 0.58,
            (31.0, 31.9): 0.75,
            (32.0, 32.9): 1.25,
            (33.0, float('inf')): 2.25
        },
        "Heavy": {
            (0, 29.9): 0.75,
            (29.9, 30.9): 0.83,
            (31.0, 31.9): 1.0,
            (32.0, 32.9): 1.5,
            (33.0, float('inf')): 2.5
        }
    }

    for range_key, recommended_ratio in recommended_ratios[work].items():
        if range_key[0] <= wbgt <= range_key[1]:
            #st.write(recommended_ratio)
            return inputted_ratio >= recommended_ratio

    return False

# Function to extract the latest temperature for a specific station from API response
def extract_latest_temperature(station_id, data):
    for item in data['items']:
        readings = item['readings']
        for reading in readings:
            if reading['station_id'] == station_id:
                return item['timestamp'], reading['value']
    return None, None  # Return None if the station's latest temperature is not found

def get_air_temperature_for_location(camp_location, desired_date):
    api_url_air = "https://api.data.gov.sg/v1/environment/air-temperature"

    try:
        # Make a request to the Air Temperature API
        response_air = requests.get(api_url_air, params={'date': desired_date})

        if response_air.status_code == 200:
            data_air = response_air.json()
            station_id = classify_camp_code(camp_location)
            timestamp, latest_temperature_air = extract_latest_temperature(station_id, data_air)

            if latest_temperature_air is not None:
                return timestamp, latest_temperature_air
            else:
                return "Temperature data not available for this location."
        else:
            return f"Error: Unable to retrieve Air Temperature data. Status code: {response_air.status_code}"

    except requests.exceptions.RequestException as e:
        return f"Request error for Air Temperature: {e}"

def get_humiditiy_for_location(camp_location, desired_date):
    api_url_air = "https://api.data.gov.sg/v1/environment/relative-humidity"

    try:
        # Make a request to the Air Temperature API
        response_humidity = requests.get(api_url_air, params={'date': desired_date})

        if response_humidity.status_code == 200:
            data_humidity = response_humidity.json()
            station_id = classify_camp_code(camp_location)
            latest_humidity = extract_latest_temperature(station_id, data_humidity)

            if latest_humidity is not None:
                return latest_humidity
            else:
                return "Humidity data not available for this location."
        else:
            return f"Error: Unable to retrieve Humidity data. Status code: {response_humidity.status_code}"

    except requests.exceptions.RequestException as e:
        return f"Request error for Humidity: {e}"

# Self-Assessment
def self_assessment():
    st.title("Heat Risk Self-Assessment")
    user = st.session_state.authenticated_user

    # Collect input from the user
    urine_color = st.selectbox("Urine Color", ["Clear", "Pale Yellow", "Dark Yellow"], key="urine")
    uniform_type = st.selectbox("Uniform Type", ["PT Kit", "Full Battle Order"], key="uniform")
    activity_taken = st.selectbox("Activity Level", ["Light", "Moderate", "Heavy"], key="activity")
    location = st.selectbox("Location", ["Changi Camp", "Clementi Camp"], key="location")

    work_minutes = st.number_input("Exercise Minutes", key="work_minutes", min_value=1, max_value=720, step=1)
    rest_minutes = st.number_input("Rest Minutes", key="rest_minutes", min_value=1, max_value=720, step=1)

    work_ratio = rest_minutes / work_minutes

    # Process and display the results
    if st.button("Submit"):
        st.write(f"**Weather Condition at {location}**")
        # Get the current date and time in the desired format
        current_time = datetime.now()
        formatted_time = current_time.strftime("%Y-%m-%d")

        input_date = current_time.strftime("%Y-%m-%d, %H:%M:%S")
        timestamp, latest_temperature_air = get_air_temperature_for_location(location, formatted_time)
        timestamp2, latest_humidity = get_humiditiy_for_location(location, formatted_time)
        st.write(f"Air temperature:  {latest_temperature_air} °C")
        st.write(f"Relative Humidity: {latest_humidity} %")
        st.write(f"Time: {timestamp}")

        calculated_WBGT = calculate_WBGT(latest_temperature_air, latest_humidity)
        st.write(f'WBGT Reading: {calculated_WBGT:.2f} ')

        st.write(f"**Self-Assessment Results:**")

        st.write(f"Rest Minutes: {rest_minutes} Minutes")
        st.write(f"Work Minutes: {work_minutes} Minutes")
        st.write(f"Activity Level: {activity_taken}")
        st.write(f"Urine Color: {urine_color}")
        st.write(f"Uniform Type: {uniform_type}")
        st.write(f"Work Ratio: {work_ratio}")

        user_has_medication = has_medication(st.session_state.patient_id)

        if user_has_medication:
            st.write("User has taken medication that affect their heat loss.")
            medication = "Yes"
        else:
            st.write("User has not taken medication that affect their heat loss.")
            medication = "No"

        wbgt_value_risk = calculated_WBGT + classify_urine_risk(urine_color) + classify_uniform_risk(uniform_type)
        st.write(f"WBGT Read: {wbgt_value_risk}")
        heat_risk = classify_heat_risk(wbgt_value_risk)
        st.write(f"WBGT Heat Color: {heat_risk}")

        user_inputted_ratio = work_ratio  # Replace with the user's input

        if classify_wbgt_min_excerise(wbgt_value_risk) > work_minutes:
            st.write(f"Heat Risk: Low")
        else:
            is_within_recommended_range = is_work_rest_ratio_within_recommended(activity_taken, wbgt_value_risk,
                                                                            user_inputted_ratio)
            if is_within_recommended_range:
                st.write("The inputted work/rest ratio is within the recommended range.")
            else:
                st.write("The inputted work/rest ratio is not within the recommended range.")

        # Save user data to SQLite
        save_user_data(user, rest_minutes, work_minutes, activity_taken, urine_color, location, uniform_type, medication, input_date)

# Function for Commander Dashboard with Scorecard
def commander_dashboard():
    st.title("Commander Dashboard")

    current_time = datetime.now()
    formatted_time = current_time.strftime("%Y-%m-%d")

    camp_location = st.selectbox("Select Camp Location", ["Changi Camp", "Clementi Camp"])
    timestamp, latest_temperature_air = get_air_temperature_for_location(camp_location,formatted_time)
    timestamp2, latest_humidity = get_air_temperature_for_location(camp_location, formatted_time)
    calculated_WBGT = calculate_WBGT(latest_temperature_air, latest_humidity)
    WBGT_color = classify_heat_risk(calculated_WBGT)

    cleansed_time = datetime.fromisoformat(timestamp).astimezone(timezone.utc)

    col1, col2, col3, col4 = st.columns(4)

    conn = sqlite3.connect('your_database.db')  # Replace with your SQLite database file
    query = "SELECT * FROM user_data WHERE location = ?"

    query = """
        WITH RankedUserData AS (
            SELECT
                *,
                ROW_NUMBER() OVER (PARTITION BY user ORDER BY input_date DESC) AS row_num
            FROM
                user_data
            WHERE
                location = ?
        )
        SELECT *
        FROM
            RankedUserData
        WHERE
            row_num = 1;
    """


    data = pd.read_sql_query(query, conn, params=(camp_location,))
    conn.close()

    if not data.empty:
        st.write(
            """
            <style>
            [data-testid="stMetricDelta"] svg {
                display: none;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        col1.metric(label="Air Temperature", value=f"{latest_temperature_air:.2f} °C")
        col2.metric(label="WBGT Reading", value=f"{calculated_WBGT:.2f}", delta=f"({WBGT_color})")

        data["Work Ratio"] = data['rest_minutes'] / data['work_minutes']
        data['Work Ratio'] = data['Work Ratio'].apply(lambda x: f"{x:.2f}")

        data['calculated wbgt'] = calculated_WBGT + classify_uniform_risk(data['uniform']) + classify_urine_risk(data['urine'])

        data["Heat Risk"] = data.apply(lambda row: is_work_rest_ratio_within_recommended(row['activity'], calculated_WBGT, row['rest_minutes'] / row['work_minutes']), axis=1)

        data["Heat Risk"] = data["Heat Risk"].map({True: "Low", False: "High"})

        high_heat_risk_count = (data['Heat Risk'] == "High").sum()
        num_rows = data.shape[0]

        col3.metric(label="Total Soldiers", value=num_rows, delta=None)
        col4.metric(label="Number of High Risk", value=high_heat_risk_count, delta=None)

        col1a, col2a = st.columns((7,3))


        col2a.caption(f"Data as at: {cleansed_time}")


        import plotly.express as px
        fig = px.pie(data, names='Heat Risk', title='Heat Risk Distribution')
        col1a.plotly_chart(fig, use_container_width=True)

        average_work_time = data['work_minutes'].mean()
        average_rest_time = data['rest_minutes'].mean()
        data['Work Ratio2'] = pd.to_numeric(data['Work Ratio'], errors='coerce')
        average_work_ratio = data['Work Ratio2'].mean()

        col2a.metric(label="Average Work Time", value=f"{average_work_time:.2f} Mins")
        col2a.metric(label="Average Rest Time", value=f"{average_rest_time:.2f} Mins")
        col2a.metric(label="Average Work Ratio", value=f"{average_work_ratio:.2f} Mins")

        with st.expander("See Details"):
            if not data.empty:
                st.write("User Data Entries:")
                data = data.drop(columns=['id', 'calculated wbgt', 'Work Ratio'])
                st.dataframe(data)
            else:
                st.write("No entries found in the database.")
    else:
        st.write("No entries found in the database.")
def logout():
    # Clear the authenticated user from the session state
    st.session_state.authenticated_user = None
    st.experimental_rerun()

def login_page():
    if st.session_state.authenticated_user is None:
        st.title("User Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Login"):
            authenticated, username, rank, patient_id = authenticate_user(username, password)
            if authenticated:
                st.success("Login successful!")
                st.session_state.authenticated_user = username
                st.session_state.user_rank = rank
                st.session_state.patient_id = patient_id
                st.experimental_rerun()
            else:
                st.error("Invalid username or password. Please try again")

# Main Streamlit app
if 'authenticated_user' not in st.session_state:
    st.session_state.authenticated_user = None

st.sidebar.title("Heat Exhaustion Management Application (HEMA)")

st.sidebar.subheader("Login Details")
# Display the sidebar for navigation
if st.session_state.authenticated_user is not None:
    # If a user is authenticated, show "Log Out" button
    st.sidebar.write(f"**Username:** {st.session_state.authenticated_user}")
    st.sidebar.write(f"**Rank:** {st.session_state.user_rank}")
    st.sidebar.write(f"**Patient ID:** {st.session_state.patient_id}")
    if st.sidebar.button("Log Out"):
        logout()

else:
    st.sidebar.write("Not logged in")

page = st.sidebar.selectbox("Select a Page", ["Self-Assessment", "Commander Dashboard"])

# Ensure that the "Login Page" is loaded if no user is logged in
if st.session_state.authenticated_user is None or page == "Login Page":
    login_page()

# Display other pages if the user is authenticated
if st.session_state.authenticated_user is not None:
    if st.session_state.user_rank == "Commander":
        # Commanders can access both "Commander Dashboard" and "Self-Assessment"
        if page == "Commander Dashboard":
            commander_dashboard()
        elif page == "Self-Assessment":
            self_assessment()
    else:
        # Handle other user ranks here
        if page == "Self-Assessment":
            self_assessment()