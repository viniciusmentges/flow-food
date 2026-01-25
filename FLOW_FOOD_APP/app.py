import streamlit as st
from src.config import APP_MODE, CLIENT_MENU, ADMIN_MENU
from src.ui.layout import render_sidebar

from src.ui.pages.lista_do_dia import page_lista_fixa
from src.ui.pages.campanha_pontual import page_campanha_pontual

# páginas extras (opcionais, só para ADMIN)
try:
    from src.ui.pages.crm import page_crm
except Exception:
    page_crm = None

try:
    from src.ui.pages.admin import page_admin
except Exception:
    page_admin = None

st.set_page_config(page_title="Flow Food", layout="wide")

PAGES = {
    "Lista Fixa": page_lista_fixa,
    "Campanha Pontual": page_campanha_pontual,
}

if APP_MODE == "ADMIN":
    if page_crm: PAGES["CRM"] = page_crm
    if page_admin: PAGES["Admin"] = page_admin

menu_list = CLIENT_MENU if APP_MODE == "CLIENT" else ADMIN_MENU


selected = render_sidebar(menu_list)

PAGES[selected]()
