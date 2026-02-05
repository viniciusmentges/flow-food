# src/services/sheets.py
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from urllib.parse import quote
from datetime import date


# ==========================
# CLIENT / AUTH
# ==========================
def get_gspread_client():
    creds_info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    credentials = Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(credentials)


# ==========================
# READ SHEETS -> DF
# ==========================
@st.cache_data(ttl=60)
def load_sheet_df(worksheet_name: str, spreadsheet_id: str | None = None) -> pd.DataFrame:
    """
    Lê uma aba do Google Sheets e retorna DataFrame.
    Se spreadsheet_id não for passado, usa st.secrets["SPREADSHEET_ID"].
    """
    if not spreadsheet_id:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]

    client = get_gspread_client()
    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet_name)

    data = ws.get_all_values()
    if not data:
        return pd.DataFrame()

    headers = data[0]
    rows = data[1:]

    df = pd.DataFrame(rows, columns=headers)

    # Remove colunas com header vazio (sobras comuns no Sheets)
    valid_cols = [col for col in df.columns if str(col).strip() != ""]
    df = df[valid_cols]

    # Normaliza nomes das colunas
    df.columns = [str(c).strip() for c in df.columns]

    return df


# ==========================
# HELPERS
# ==========================
def make_wa_link(whatsapp_num: str, message: str) -> str:
    num = "".join([c for c in str(whatsapp_num) if c.isdigit()])
    if not num.startswith("55"):
        num = "55" + num
    return f"https://wa.me/{num}?text={quote(message or '')}"


# ==========================
# LISTA FIXA
# ==========================
def gerar_lista_fixa(df_crm: pd.DataFrame, df_cfg: pd.DataFrame) -> pd.DataFrame:
    hoje = pd.to_datetime(date.today())

    # seed diário: muda a cada dia, mas fica estável no dia
    seed_diario = int(pd.to_datetime(date.today()).strftime("%Y%m%d"))

    df_base = df_crm.copy()

    # Converte datas (se existir)
    if "PROXIMO CONTATO PERMITIDO" in df_base.columns:
        df_base["PROXIMO CONTATO PERMITIDO"] = pd.to_datetime(
            df_base["PROXIMO CONTATO PERMITIDO"], errors="coerce"
        )

    # ✅ Filtra elegível SIM (se existir)
    if "ELEGIVEL" in df_base.columns:
        df_base = df_base[
            df_base["ELEGIVEL"].astype(str).str.upper().str.strip().eq("SIM")
        ]

    # ✅ Respeita "próximo contato permitido" (se existir)
    if "PROXIMO CONTATO PERMITIDO" in df_base.columns:
        df_base = df_base[
            df_base["PROXIMO CONTATO PERMITIDO"].isna()
            | (df_base["PROXIMO CONTATO PERMITIDO"] <= hoje)
        ]

    # ✅ Normaliza STATUS no CRM (resolve ATIVO/vip/espaços/minúsculas)
    if "STATUS" in df_base.columns:
        df_base["STATUS_N"] = df_base["STATUS"].astype(str).str.upper().str.strip()
    else:
        df_base["STATUS_N"] = ""

    # Regras do CONFIG
    regras = df_cfg.dropna(subset=["STATUS", "QTD POR DIA"]).copy()

    # ✅ Normaliza STATUS no CONFIG também
    regras["STATUS_N"] = regras["STATUS"].astype(str).str.upper().str.strip()

    saida = []

    for _, r in regras.iterrows():
        status_n = str(r.get("STATUS_N", "")).strip()

        try:
            qtd_val = str(r.get("QTD POR DIA", "")).strip()
            qtd = int(float(qtd_val)) if qtd_val else 0
        except (ValueError, TypeError):
            qtd = 0

        if qtd <= 0:
            continue

        campanha = str(r.get("CAMPANHA", "")).strip()
        mensagem = str(r.get("MENSAGEM", "")).strip()

        # Filtra por status normalizado
        df_s = df_base[df_base["STATUS_N"].eq(status_n)].copy()
        if df_s.empty:
            continue

        # Aleatoriedade por status (estável no dia)
        if len(df_s) > 1:
            df_s = df_s.sample(frac=1, random_state=seed_diario).reset_index(drop=True)

        df_pick = df_s.head(qtd).copy()

        df_out = pd.DataFrame({
            "WHATSAPP": df_pick.get("WHATSAPP"),
            "NOME": df_pick.get("NOME"),
            "TOTAL_PEDIDOS": df_pick.get("TOTAL DE PEDIDOS"),
            "DIAS_INATIVIDADE": df_pick.get("DIAS DE INATIVIDADE"),
            "STATUS": df_pick.get("STATUS"),          # mantém o original para exibição
            "PRIORIDADE": df_pick.get("PRIORIDADE"),
            "CAMPANHA": campanha,
            "MENSAGEM": mensagem,
        })

        df_out["LINK"] = [make_wa_link(w, mensagem) for w in df_out["WHATSAPP"].tolist()]
        df_out["ENVIADO?"] = False

        saida.append(df_out)

    if not saida:
        return pd.DataFrame()

    return pd.concat(saida, ignore_index=True)


# ==========================
# LISTA PONTUAL (LEITURA)
# ==========================
def ler_lista_pontual_sheets(spreadsheet_id: str | None = None) -> pd.DataFrame:
    """
    Lê a aba LISTA_PONTUAL e devolve no padrão:
    whatsapp, nome, status, campanha, enviado (bool)
    """
    if not spreadsheet_id:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]

    client = get_gspread_client()
    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet("LISTA_PONTUAL")

    data = ws.get_all_values()
    if not data:
        return pd.DataFrame(columns=["whatsapp", "nome", "status", "campanha", "enviado"])

    headers = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=headers)

    # Remove colunas com header vazio
    valid_cols = [col for col in df.columns if str(col).strip() != ""]
    df = df[valid_cols]
    df.columns = [str(c).strip() for c in df.columns]

    # Renomeia para padrão da UI
    rename_map = {
        "WHATSAPP": "whatsapp",
        "NOME": "nome",
        "STATUS": "status",
        "CAMPANHA": "campanha",
        "ENVIADO?": "enviado",
    }
    df = df.rename(columns=rename_map)

    # Garante colunas necessárias
    for col in ["whatsapp", "nome", "status", "campanha"]:
        if col not in df.columns:
            df[col] = ""

    if "enviado" not in df.columns:
        df["enviado"] = False

    # Normaliza enviado para boolean
    df["enviado"] = df["enviado"].astype(str).str.upper().isin(
        ["TRUE", "VERDADEIRO", "SIM", "1"]
    )

    return df[["whatsapp", "nome", "status", "campanha", "enviado"]]
