import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from urllib.parse import quote
from datetime import date

SHEET_ID = "1DKQo3AV4hryoODKrrLyUOWmJ8W7EWSfkj1lxTWBsTp4"

def get_gspread_client():
    creds_info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    credentials = Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(credentials)

@st.cache_data(ttl=60)
def load_sheet_df(worksheet_name: str) -> pd.DataFrame:
    client = get_gspread_client()
    sh = client.open_by_key(SHEET_ID)
    ws = sh.worksheet(worksheet_name)
    # get_all_records falha se tiver colunas sem título ou títulos duplicados
    # então vamos pegar como lista de listas
    data = ws.get_all_values()

    if not data:
        return pd.DataFrame()

    headers = data[0]
    rows = data[1:]

    df = pd.DataFrame(rows, columns=headers)
    
    # Remove colunas com header vazio (comum sobrar colunas em branco no Sheets)
    # Seleciona apenas colunas onde o nome não é string vazia
    valid_cols = [col for col in df.columns if str(col).strip() != ""]
    df = df[valid_cols]

    df.columns = [str(c).strip() for c in df.columns]
    return df

def make_wa_link(whatsapp_num: str, message: str) -> str:
    num = "".join([c for c in str(whatsapp_num) if c.isdigit()])
    if not num.startswith("55"):
        num = "55" + num
    return f"https://wa.me/{num}?text={quote(message or '')}"

def gerar_lista_fixa(df_crm: pd.DataFrame, df_cfg: pd.DataFrame) -> pd.DataFrame:
    hoje = pd.to_datetime(date.today())

    # ✅ seed diário: muda a cada dia, mas fica estável no dia
    seed_diario = int(pd.to_datetime(date.today()).strftime("%Y%m%d"))

    if "PROXIMO CONTATO PERMITIDO" in df_crm.columns:
        df_crm["PROXIMO CONTATO PERMITIDO"] = pd.to_datetime(
            df_crm["PROXIMO CONTATO PERMITIDO"], errors="coerce"
        )

    df_base = df_crm.copy()

    if "ELEGIVEL" in df_base.columns:
        df_base = df_base[df_base["ELEGIVEL"].astype(str).str.upper().str.strip().eq("SIM")]

    if "PROXIMO CONTATO PERMITIDO" in df_base.columns:
        df_base = df_base[
            df_base["PROXIMO CONTATO PERMITIDO"].isna()
            | (df_base["PROXIMO CONTATO PERMITIDO"] <= hoje)
        ]

    regras = df_cfg.dropna(subset=["STATUS", "QTD POR DIA"]).copy()

    saida = []

    for _, r in regras.iterrows():
        status = str(r["STATUS"]).strip()

        try:
            qtd_val = str(r["QTD POR DIA"]).strip()
            qtd = int(float(qtd_val)) if qtd_val else 0
        except (ValueError, TypeError):
            qtd = 0

        if qtd <= 0:
            continue

        campanha = str(r.get("CAMPANHA", "")).strip()
        mensagem = str(r.get("MENSAGEM", "")).strip()

        if "STATUS" not in df_base.columns:
            continue

        df_s = df_base[df_base["STATUS"].astype(str).str.strip().eq(status)].copy()

        if df_s.empty:
            continue

        # ✅ ALEATORIEDADE POR STATUS (estável no dia)
        # embaralha e pega qtd
        if len(df_s) > 1:
            df_s = df_s.sample(frac=1, random_state=seed_diario).reset_index(drop=True)

        df_pick = df_s.head(qtd).copy()

        df_out = pd.DataFrame({
            "WHATSAPP": df_pick.get("WHATSAPP"),
            "NOME": df_pick.get("NOME"),
            "TOTAL_PEDIDOS": df_pick.get("TOTAL DE PEDIDOS"),
            "DIAS_INATIVIDADE": df_pick.get("DIAS DE INATIVIDADE"),
            "STATUS": df_pick.get("STATUS"),
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

def ler_lista_pontual_sheets(st, spreadsheet_id: str) -> pd.DataFrame:
    # Reusa a função get_gspread_client existente (que já usa st.secrets)
    # Apenas certificando que ela está acessível ou criando uma versão compatível se necessário.
    # Como get_gspread_client já está definida no topo deste arquivo, podemos usá-la se adaptarmos a chamada.
    # Mas a função existente não recebe 'st' como argumento, ela pega st.secrets direto.
    # A função duplicada recebia st. Vamos usar a lógica interna aqui.
    
    client = get_gspread_client()
    sh = client.open_by_key(spreadsheet_id)

    ws = sh.worksheet("LISTA_PONTUAL")
    # get_all_records pode falhar, vamos usar get_all_values igual fizemos antes
    data = ws.get_all_values()
    
    if not data:
        return pd.DataFrame(columns=["whatsapp", "nome", "status", "campanha", "enviado"])

    headers = data[0]
    rows = data[1:]
    
    df = pd.DataFrame(rows, columns=headers)

    # Renomeia para o padrão que tua UI já usa hoje
    # No Sheets os headers devem ser maiúsculos conforme tua convenção anterior
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
    # Precisamos tratar valores vazios/strings
    df["enviado"] = df["enviado"].astype(str).str.upper().isin(["TRUE", "VERDADEIRO", "SIM", "1"])
    
    return df[["whatsapp", "nome", "status", "campanha", "enviado"]]

