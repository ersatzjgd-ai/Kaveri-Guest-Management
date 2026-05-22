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

today_start = f"{datetime.now().strftime('%Y-%m-%d')}T00:00:00"

# Data States initialized securely
expected_guests_df = pd.DataFrame(columns=["id", "guest_name", "session_type"])
active_guests_df = pd.DataFrame(columns=["id", "guest_name", "lounge", "lmw_status", "demo_status", "ready_to_meet_gurudev", "met_gurudev"])
report_guests_df = pd.DataFrame(columns=["guest_name", "session_type", "lounge", "lmw_status", "demo_status", "met_gurudev", "jai_gurudev"])

search_incoming = ""
session_type_options = ["Morning", "Evening"]
session_type = "Morning"
guest_names_input = ""
manager_lounge = "Unassigned"
manager_photo = "" 

search_active = ""
lounge_filter_options = ["All", "Unassigned", "L1", "L2", "L3", "BR", "L5"]
selected_view = "All"
team_photo = "" 
pdf_path = ""

# CRITICAL FIX: Initialize all selections STRICTLY as empty lists to prevent null.length crashes
selected_expected_guest = []
selected_active_guest = []

table_lovs = {
    "lounge": ["Unassigned", "L1", "L2", "L3", "BR", "L5"],
    "lmw_status": ["Not yet", "Started", "Done"],
    "demo_status": ["Not yet", "Started", "Done"]
}

# --- HELPER FUNCTIONS ---
def has_selection(val):
    """Safely checks if a table row is currently selected without crashing."""
    if val is None: return False
    if isinstance(val, list) and len(val) == 0: return False
    if isinstance(val, str) and val == "": return False
    return True

def get_wa_url(active_df, sel_idx):
    """Dynamically generates the WhatsApp URL based on the selected row."""
    if not has_selection(sel_idx): return ""
    try:
        idx = sel_idx[0] if isinstance(sel_idx, list) else int(sel_idx)
        if idx >= len(active_df): return ""
        guest = active_df.iloc[idx]
        msg = f"*{guest['lounge']}*\n{guest['guest_name']}\n📺 LMW: {guest['lmw_status']}\n💻 IP Demo: {guest['demo_status']}\n⏳ Ready: {'✅' if guest['ready_to_meet_gurudev'] else '❌'}\n🤝 Met: {'✅' if guest['met_gurudev'] else '❌'}"
        return f"https://wa.me/?text={urllib.parse.quote(msg)}"
    except Exception:
        return ""

def fetch_data(state: State):
    global today_start
    res_exp = supabase.table("guests").select("*").eq("is_active", False).eq("has_left_kaveri", False).gte("created_at", today_start).order("created_at").execute()
    exp_df = pd.DataFrame(res_exp.data) if res_exp.data else pd.DataFrame(columns=["id", "guest_name", "session_type"])
    if not exp_df.empty and state.search_incoming:
        exp_df = exp_df[exp_df["guest_name"].str.contains(state.search_incoming, case=False, na=False)]
    state.expected_guests_df = exp_df

    res_act = supabase.table("guests").select("*").eq("is_active", True).eq("jai_gurudev", False).gte("created_at", today_start).order("created_at").execute()
    act_df = pd.DataFrame(res_act.data) if res_act.data else pd.DataFrame(columns=["id", "guest_name", "lounge", "lmw_status", "demo_status", "ready_to_meet_gurudev", "met_gurudev"])
    
    if not act_df.empty:
        if state.search_active:
            act_df = act_df[act_df["guest_name"].str.contains(state.search_active, case=False, na=False)]
        if state.selected_view != "All":
            act_df = act_df[act_df["lounge"] == state.selected_view]
    state.active_guests_df = act_df

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
    state.guest
    
