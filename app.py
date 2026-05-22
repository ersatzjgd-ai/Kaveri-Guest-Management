import os
import datetime
import base64
from taipy.gui import Gui, notify, invoke_callback
from supabase import create_client, Client
from fpdf import FPDF
import pandas as pd

# ==========================================
# 1. DATABASE & CONFIGURATION
# ==========================================
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://your-project.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "your-anon-key")
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Supabase init error: {e}")

# ==========================================
# 2. STATE VARIABLES
# ==========================================
current_view = "On-Ground Team"
manager_logged_in = False
manager_password = ""

# Manager State
new_guest_names = ""
new_guest_session = "Morning"
search_incoming = ""
incoming_df = pd.DataFrame()
pdf_path = ""

# On-Ground State
lounge_filter = "All"
search_active = ""
active_df = pd.DataFrame()

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def get_today_start():
    """Returns midnight of the current day in ISO format."""
    now = datetime.datetime.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

def fetch_data(state):
    """Fetches data from Supabase and updates DataFrames based on filters."""
    try:
        today = get_today_start()
        
        # Fetch Incoming Guests (Manager View)
        res_in = supabase.table("guests").select("*").eq("is_active", False).eq("has_left_kaveri", False).gte("created_at", today).execute()
        df_in = pd.DataFrame(res_in.data)
        if not df_in.empty:
            if state.search_incoming:
                df_in = df_in[df_in['guest_name'].str.contains(state.search_incoming, case=False, na=False)]
            df_in = df_in[['id', 'guest_name', 'session_type', 'created_at']]
        state.incoming_df = df_in

        # Fetch Active Guests (On-Ground View)
        res_act = supabase.table("guests").select("*").eq("is_active", True).eq("jai_gurudev", False).gte("created_at", today).execute()
        df_act = pd.DataFrame(res_act.data)
        if not df_act.empty:
            if state.lounge_filter != "All":
                df_act = df_act[df_act['lounge'] == state.lounge_filter]
            if state.search_active:
                df_act = df_act[df_act['guest_name'].str.contains(state.search_active, case=False, na=False)]
            
            # Custom sorting: Room hierarchy then created_at
            lounge_order = {"Unassigned": 0, "L1": 1, "L2": 2, "L3": 3, "BR": 4, "L5": 5}
            df_act['lounge_rank'] = df_act['lounge'].map(lounge_order)
            df_act = df_act.sort_values(by=['lounge_rank', 'created_at'])
            df_act = df_act[['id', 'guest_name', 'lounge', 'lmw_status', 'demo_status', 'ready_to_meet_gurudev', 'met_gurudev']]
        state.active_df = df_act
    except Exception as e:
        print(f"Data fetch error: {e}")

# ==========================================
# 4. CALLBACK FUNCTIONS
# ==========================================
def login_manager(state):
    if state.manager_password == "kaveri_admin":
        state.manager_logged_in = True
        state.manager_password = ""
        fetch_data(state)
        notify(state, "success", "Logged in successfully!")
    else:
        notify(state, "error", "Incorrect Password")

def logout_manager(state):
    state.manager_logged_in = False
    notify(state, "info", "Logged out.")

def add_guests(state):
    names = [name.strip() for name in state.new_guest_names.split("\n") if name.strip()]
    if not names:
        notify(state, "warning", "No names provided.")
        return
    
    payload = []
    for name in names:
        payload.append({
            "guest_name": name,
            "session_type": state.new_guest_session,
            "is_active": False,
            "has_left_kaveri": False,
            "jai_gurudev": False,
            "lounge": "Unassigned",
            "lmw_status": "Not yet",
            "demo_status": "Not yet",
            "ready_to_meet_gurudev": False,
            "met_gurudev": False
        })
    
    try:
        supabase.table("guests").insert(payload).execute()
        state.new_guest_names = ""
        fetch_data(state)
        notify(state, "success", f"Added {len(names)} guests!")
    except Exception as e:
        notify(state, "error", f"Error adding guests: {e}")

def checkin_guest(state, var_name, action, payload):
    """Triggered by the action button on the incoming guests table"""
    row_idx = payload["index"]
    guest_id = state.incoming_df.iloc[row_idx]["id"]
    
    try:
        supabase.table("guests").update({"is_active": True}).eq("id", guest_id).execute()
        fetch_data(state)
        notify(state, "success", "Guest Checked In!")
    except Exception as e:
        notify(state, "error", "Update failed.")

def update_active_guest(state, var_name, payload):
    """Triggered when a cell is edited in the active guests table (On-Ground view)"""
    row_idx = payload["index"]
    col_name = payload["col"]
    new_value = payload["value"]
    guest_id = state.active_df.iloc[row_idx]["id"]

    try:
        supabase.table("guests").update({col_name: new_value}).eq("id", guest_id).execute()
        fetch_data(state)
        notify(state, "success", "Status updated!")
    except Exception as e:
        notify(state, "error", "Failed to update status.")

def mark_complete(state, var_name, action, payload):
    """Action button to mark a guest's visit as complete"""
    row_idx = payload["index"]
    guest_id = state.active_df.iloc[row_idx]["id"]
    
    try:
        supabase.table("guests").update({"jai_gurudev": True}).eq("id", guest_id).execute()
        fetch_data(state)
        notify(state, "success", "Visit Completed!")
    except Exception as e:
        notify(state, "error", "Update failed.")

def generate_pdf(state):
    """Generates an end-of-session PDF report."""
    today = get_today_start()
    res = supabase.table("guests").select("*").gte("created_at", today).execute()
    data = res.data
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(200, 10, txt=f"Kaveri Guest Report - {datetime.date.today()}", ln=True, align="C")
    
    pdf.set_font("Arial", size=12)
    for guest in data:
        name = guest.get('guest_name', 'Unknown').replace("'", "'").replace('"', '"')
        status = "Complete" if guest.get('jai_gurudev') else "In Progress"
        
        pdf.cell(200, 10, txt=f"Name: {name} | Session: {guest.get('session_type')} | Room: {guest.get('lounge')}", ln=True)
        pdf.cell(200, 10, txt=f"LMW: {guest.get('lmw_status')} | Demo: {guest.get('demo_status')} | Status: {status}", ln=True)
        pdf.cell(200, 5, txt="-"*50, ln=True)

    filename = f"Kaveri_Report_{datetime.date.today().strftime('%Y%m%d')}.pdf"
    pdf.output(filename)
    state.pdf_path = filename
    notify(state, "success", "Report generated! Ready to download.")

def on_init(state):
    fetch_data(state)

# ==========================================
# 5. UI LAYOUT (Taipy Markdown)
# ==========================================
page_md = """
# 🏛️ Kaveri GM

<|{current_view}|toggle|lov=On-Ground Team;Manager|>

<|part|render={current_view == 'Manager'}|
    <|part|render={not manager_logged_in}|
        ## Manager Login
        <|{manager_password}|input|password=True|label=Enter Password|>
        <|Login|button|on_action=login_manager|>
    |>

    <|part|render={manager_logged_in}|
        <|Logout|button|on_action=logout_manager|>

        ### ⏳ Incoming Guests
        <|{search_incoming}|input|label=Search Incoming...|on_change=fetch_data|>
        
        <|{incoming_df}|table|on_action=checkin_guest|action_columns={{"checkin": "Check-In ➡️"}}|>

        <hr/>

        ### ➕ Add Expected Guests
        <|{new_guest_session}|selector|lov=Morning;Evening|>
        <|{new_guest_names}|input|multiline=True|label=Paste Names (one per line)|>
        <|Add Guests|button|on_action=add_guests|>

        <hr/>

        ### 📊 End of Session Report
        <|Generate PDF|button|on_action=generate_pdf|>
        <|{pdf_path}|file_download|label=Download Report|render={pdf_path != ""}|>
    |>
|>

<|part|render={current_view == 'On-Ground Team'}|
    ### 🏃 On-Ground Dashboard
    
    <|Refresh Data|button|on_action=fetch_data|>
    <|{lounge_filter}|selector|lov=All;Unassigned;L1;L2;L3;BR;L5|on_change=fetch_data|>
    <|{search_active}|input|label=Search Active...|on_change=fetch_data|>

    *Tip: Click directly on Lounge, LMW, or Demo cells to update them instantly.*
    <|{active_df}|table|editable=True|on_edit=update_active_guest|on_action=mark_complete|action_columns={{"complete": "✅ Complete Visit"}}|>
|>
"""

if __name__ == "__main__":
    Gui(page=page_md).run(title="Kaveri GM", dark_mode=False, port=5000)
    
