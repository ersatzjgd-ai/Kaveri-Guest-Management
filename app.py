import os
import base64
import tempfile
import urllib.parse
from datetime import datetime
import pandas as pd
from fpdf import FPDF

from taipy.gui import Gui, State, notify
from supabase import create_client, Client

# --- CONFIG & SUPABASE CONNECTION ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "your_supabase_url")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "your_supabase_key")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- GLOBAL STATE INITIALIZATION ---
role_options = ["On-Ground Team 🏃", "Manager 👔"]
role = "On-Ground Team 🏃"

manager_logged_in = False
pwd_input = ""
MANAGER_PASSWORD = os.environ.get("MANAGER_PASSWORD", "kaveri_admin")

# Data States (FIX: Pre-fill columns to prevent React .length crashes)
today_start = f"{datetime.now().strftime('%Y-%m-%d')}T00:00:00"
expected_guests_df = pd.DataFrame(columns=["id", "guest_name", "session_type"])
active_guests_df = pd.DataFrame(columns=["id", "guest_name", "lounge", "lmw_status", "demo_status", "ready_to_meet_gurudev", "met_gurudev"])
report_guests_df = pd.DataFrame(columns=["guest_name", "session_type", "lounge", "lmw_status", "demo_status", "met_gurudev", "jai_gurudev"])

# Manager Inputs
search_incoming = ""
session_type_options = ["Morning", "Evening"]
session_type = "Morning"
guest_names_input = ""
selected_expected_guest = [] # FIX: Changed from None to empty list
manager_lounge = "Unassigned"
manager_camera = None

# Team Inputs
search_active = ""
lounge_filter_options = ["All", "Unassigned", "L1", "L2", "L3", "BR", "L5"]
selected_view = "All"
selected_active_guest = [] # FIX: Changed from None to empty list
team_camera = None
wa_url = ""
pdf_path = ""

# --- HELPER FUNCTIONS ---
def fetch_data(state: State):
    """Fetches all necessary data from Supabase and updates dataframes."""
    global today_start
    
    # 1. Expected Guests
    res_exp = supabase.table("guests").select("*").eq("is_active", False).eq("has_left_kaveri", False).gte("created_at", today_start).order("created_at").execute()
    exp_df = pd.DataFrame(res_exp.data) if res_exp.data else pd.DataFrame(columns=["id", "guest_name", "session_type"])
    if not exp_df.empty and state.search_incoming:
        exp_df = exp_df[exp_df["guest_name"].str.contains(state.search_incoming, case=False, na=False)]
    state.expected_guests_df = exp_df

    # 2. Active Guests
    res_act = supabase.table("guests").select("*").eq("is_active", True).eq("jai_gurudev", False).gte("created_at", today_start).order("created_at").execute()
    act_df = pd.DataFrame(res_act.data) if res_act.data else pd.DataFrame(columns=["id", "guest_name", "lounge", "lmw_status", "demo_status", "ready_to_meet_gurudev", "met_gurudev"])
    
    if not act_df.empty:
        if state.search_active:
            act_df = act_df[act_df["guest_name"].str.contains(state.search_active, case=False, na=False)]
        if state.selected_view != "All":
            act_df = act_df[act_df["lounge"] == state.selected_view]
            
    state.active_guests_df = act_df

    # 3. Report Guests
    res_rep = supabase.table("guests").select("*").gte("created_at", today_start).order("created_at").execute()
    state.report_guests_df = pd.DataFrame(res_rep.data) if res_rep.data else pd.DataFrame(columns=["guest_name", "session_type", "lounge", "lmw_status", "demo_status", "met_gurudev", "jai_gurudev"])

# --- MANAGER CALLBACKS ---
def check_login(state: State):
    if state.pwd_input == MANAGER_PASSWORD:
        state.manager_logged_in = True
        state.pwd_input = ""
        fetch_data(state)
        notify(state, "success", "Logged in successfully")
    else:
        notify(state, "error", "Incorrect password")

def logout(state: State):
    state.manager_logged_in = False

def add_expected_guests(state: State):
    if not state.guest_names_input.strip():
        notify(state, "error", "Please enter at least one guest name.")
        return
        
    names_list = [n.strip() for n in state.guest_names_input.split('\n') if n.strip()]
    insert_data = [{"guest_name": name, "session_type": state.session_type} for name in names_list]
    
    supabase.table("guests").insert(insert_data).execute()
    state.guest_names_input = ""
    fetch_data(state)
    notify(state, "success", f"Added {len(names_list)} guests!")

def check_in_guest(state: State):
    if not state.selected_expected_guest or state.expected_guests_df.empty:
        notify(state, "error", "Please select a guest first.")
        return
        
    idx = state.selected_expected_guest[0] if isinstance(state.selected_expected_guest, list) else state.selected_expected_guest
    guest_id = state.expected_guests_df.iloc[idx]["id"]
    guest_name = state.expected_guests_df.iloc[idx]["guest_name"]
    
    update_data = {
        "is_active": True,
        "lounge": state.manager_lounge
    }
    
    if state.manager_camera:
        with open(state.manager_camera, "rb") as f:
            update_data["photo_data"] = base64.b64encode(f.read()).decode()
            
    supabase.table("guests").update(update_data).eq("id", guest_id).execute()
    
    state.manager_lounge = "Unassigned"
    state.manager_camera = None
    state.selected_expected_guest = []
    fetch_data(state)
    notify(state, "success", f"{guest_name} checked in to {state.manager_lounge}!")

def generate_pdf_report(state: State):
    if state.report_guests_df.empty:
        notify(state, "info", "No guests to report.")
        return
        
    guests_data = state.report_guests_df.to_dict('records')
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, txt=f"Kaveri GM - End of Session Report", ln=True, align='C')
    pdf.ln(5)
    
    for g in guests_data:
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 8, txt=f"Guest: {g.get('guest_name', '')} ({g.get('session_type', 'N/A')})", ln=True)
        pdf.set_font("Arial", '', 10)
        pdf.cell(0, 6, txt=f"Lounge: {g.get('lounge', 'Not Assigned')}", ln=True)
        pdf.cell(0, 6, txt=f"LMW: {g.get('lmw_status', 'Not yet')} | Demo: {g.get('demo_status', 'Not yet')}", ln=True)
        pdf.ln(5)
        
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(tmp_file.name)
    state.pdf_path = tmp_file.name
    notify(state, "success", "PDF generated! Click download.")

# --- TEAM CALLBACKS ---
def team_table_edited(state: State, var_name, payload):
    index = payload["index"]
    col = payload["col"]
    new_val = payload["value"]
    
    guest_id = state.active_guests_df.iloc[index]["id"]
    
    supabase.table("guests").update({col: new_val}).eq("id", guest_id).execute()
    
    temp_df = state.active_guests_df.copy()
    temp_df.at[index, col] = new_val
    state.active_guests_df = temp_df
    notify(state, "success", "Updated successfully!")

def on_team_guest_select(state: State, var_name, payload):
    if not payload: return
    idx = payload[0]
    guest = state.active_guests_df.iloc[idx]
    
    msg = (
        f"*{guest['lounge']}*\n"
        f"{guest['guest_name']}\n"
        f"📺 LMW: {guest['lmw_status']}\n"
        f"💻 IP Demo: {guest['demo_status']}\n"
        f"⏳ Ready for Vyas: {'✅' if guest['ready_to_meet_gurudev'] else '❌'}\n"
        f"🤝 Met Gurudev: {'✅' if guest['met_gurudev'] else '❌'}"
    )
    state.wa_url = f"https://wa.me/?text={urllib.parse.quote(msg)}"

def save_team_photo(state: State):
    if not state.selected_active_guest or not state.team_camera:
        notify(state, "error", "Select guest and take a photo first.")
        return
        
    idx = state.selected_active_guest[0]
    guest_id = state.active_guests_df.iloc[idx]["id"]
    
    with open(state.team_camera, "rb") as f:
        encoded_pic = base64.b64encode(f.read()).decode()
        
    supabase.table("guests").update({"photo_data": encoded_pic}).eq("id", guest_id).execute()
    state.team_camera = None
    notify(state, "success", "Photo saved!")

def complete_visit(state: State):
    if not state.selected_active_guest: return
    idx = state.selected_active_guest[0]
    guest_id = state.active_guests_df.iloc[idx]["id"]
    guest_name = state.active_guests_df.iloc[idx]["guest_name"]
    
    supabase.table("guests").update({"jai_gurudev": True}).eq("id", guest_id).execute()
    state.selected_active_guest = []
    fetch_data(state)
    notify(state, "success", f"Visit complete for {guest_name}! Removed from list.")

# --- TAIPY PAGES (UI) ---

login_page = """
### 🔒 Manager Access
<|{pwd_input}|input|password=True|label=Enter Admin Password|>
<|Login|button|on_action=check_login|>
"""

manager_dashboard = """
