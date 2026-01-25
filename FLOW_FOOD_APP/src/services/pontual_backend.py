# src/services/pontual_backend.py
from __future__ import annotations

import re
import time
from datetime import date  # ✅ trocado (antes era datetime)

import pandas as pd
import gspread
from gspread import Cell
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials


# ==========================
# HELPERS
# ==========================
def _digits_only(s: str) -> str:
    s = "" if s is None else str(s)
    return re.sub(r"\D", "", s)


def _retry_quota(fn, max_tries: int = 6):
    """
    Retry com backoff exponencial para erros de quota (429).
    """
    backoff = 1
    for _ in range(max_tries):
        try:
            return fn()
        except APIError as e:
            msg = str(e)
            if "429" in msg or "Quota exceeded" in msg:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise


# ==========================
# AJUSTE AQUI (nomes das abas)
# ==========================
ABA_CRM = "CRM_GERAL"
ABA_LOG = "LOG_ENVIO"

# ==========================
# AJUSTE AQUI (nomes das colunas NO SHEETS)
# (EXATAMENTE como está na linha 1 da planilha)
# ==========================
COL_WPP = "WHATSAPP"
COL_ULTIMO_CONTATO = "ULTIMO CONTATO"
COL_CAMPANHA_DIA = "CAMPANHA DO DIA"

# LOG_ENVIO (colunas)
LOG_COL_DATA = "DATA ENVIO"
LOG_COL_WPP = "WHATSAPP"
LOG_COL_STATUS = "STATUS DO DIA"
LOG_COL_CAMPANHA = "CAMPANHA"


def _get_gspread_client_from_streamlit_secrets(st):
    """
    Usa st.secrets (padrão Streamlit) para autenticar.
    """
    info = dict(st.secrets["gcp_service_account"])

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)


def atualizar_crm_por_lista_real(st, spreadsheet_id: str, lista_df: pd.DataFrame) -> dict:
    """
    Atualiza CRM_GERAL + LOG_ENVIO no Google Sheets.

    Regras:
    - Só atualiza quem estiver com enviado == True
    - Não faz nada automaticamente: só roda quando você chamar (botão)
    """
    enviados = lista_df[lista_df["enviado"] == True].copy()
    if enviados.empty:
        return {"updated": 0, "log_added": 0}

    gc = _get_gspread_client_from_streamlit_secrets(st)
    sh = gc.open_by_key(spreadsheet_id)

    ws_crm = sh.worksheet(ABA_CRM)
    ws_log = sh.worksheet(ABA_LOG)

    # -------------------------
    # MAPEIA CRM
    # -------------------------
    crm_header = ws_crm.row_values(1)
    crm_map = {h.strip(): idx for idx, h in enumerate(crm_header)}  # 0-based

    for col in [COL_WPP, COL_ULTIMO_CONTATO, COL_CAMPANHA_DIA]:
        if col not in crm_map:
            raise ValueError(f"CRM_GERAL: coluna '{col}' não encontrada no cabeçalho.")

    wpp_col_index_1based = crm_map[COL_WPP] + 1
    crm_wpps = ws_crm.col_values(wpp_col_index_1based)[1:]  # sem header

    wpp_to_row = {}
    for i, w in enumerate(crm_wpps, start=2):
        w = _digits_only(w)
        if w:
            wpp_to_row[w] = i

    # ✅ AGORA grava só DATA (sem hora)
    hoje = date.today().isoformat()  # 2026-01-23
    # Se quiser BR, troque a linha acima por:
    # hoje = date.today().strftime("%d/%m/%Y")

    # -------------------------
    # BATCH UPDATE CRM_GERAL
    # -------------------------
    updated = 0
    cells_to_update = []

    col_ult_1b = crm_map[COL_ULTIMO_CONTATO] + 1
    col_camp_1b = crm_map[COL_CAMPANHA_DIA] + 1

    for _, r in enviados.iterrows():
        wpp = _digits_only(r["whatsapp"])
        campanha = str(r.get("campanha", "")).strip()

        row_number = wpp_to_row.get(wpp)
        if not row_number:
            continue

        cells_to_update.append(Cell(row_number, col_ult_1b, hoje))
        cells_to_update.append(Cell(row_number, col_camp_1b, campanha))
        updated += 1

    if cells_to_update:
        try:
            _retry_quota(lambda: ws_crm.update_cells(cells_to_update, value_input_option="USER_ENTERED"))
        except APIError as e:
            msg = str(e)
            if "400" in msg and "protected" in msg:
                st.error("ERRO DE PERMISSÃO: O sistema tentou editar células protegidas na aba CRM_GERAL.")
                st.info("A conta de serviço não tem permissão para editar as colunas 'ULTIMO CONTATO' ou 'CAMPANHA DO DIA'.")
                st.warning("Solução: No Google Sheets, vá em 'Dados > Proteger páginas e intervalos' e verifique se essas colunas estão bloqueadas. Se estiverem, adicione o e-mail da conta de serviço como editor ou remova a proteção.")
                st.stop()
            else:
                raise e

    # -------------------------
    # LOG_ENVIO (append)
    # -------------------------
    log_header = ws_log.row_values(1)
    log_map = {h.strip(): idx for idx, h in enumerate(log_header)}

    for col in [LOG_COL_DATA, LOG_COL_WPP, LOG_COL_STATUS, LOG_COL_CAMPANHA]:
        if col not in log_map:
            raise ValueError(f"LOG_ENVIO: coluna '{col}' não encontrada no cabeçalho.")

    rows_to_append = []
    for _, r in enviados.iterrows():
        row = [""] * len(log_header)
        row[log_map[LOG_COL_DATA]] = hoje
        row[log_map[LOG_COL_WPP]] = _digits_only(r["whatsapp"])
        row[log_map[LOG_COL_STATUS]] = str(r.get("status", "")).strip()
        row[log_map[LOG_COL_CAMPANHA]] = str(r.get("campanha", "")).strip()
        rows_to_append.append(row)

    if rows_to_append:
        _retry_quota(lambda: ws_log.append_rows(rows_to_append, value_input_option="USER_ENTERED"))

    return {"updated": updated, "log_added": len(rows_to_append)}
def _parse_date_any(s):
    """
    Tenta converter datas vindas do Sheets (ISO ou BR). Retorna date() ou None.
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
        if pd.isna(dt):
            return None
        return dt.date()
    except Exception:
        return None


def gerar_lista_pontual_por_status_real(
    st,
    spreadsheet_id: str,
    status_escolhido: str,
    total: int = 37,
    campanha: str = "",
) -> pd.DataFrame:
    """
    Gera uma lista pontual de 'total' clientes SOMENTE de um STATUS,
    respeitando cooldown via coluna 'PROXIMO CONTATO PERMITIDO' no CRM_GERAL.

    Retorna DataFrame padronizado para o app:
      whatsapp, nome, status, campanha, enviado
    """
    status_escolhido = "" if status_escolhido is None else str(status_escolhido).strip()
    if not status_escolhido:
        raise ValueError("Status escolhido vazio.")

    gc = _get_gspread_client_from_streamlit_secrets(st)
    sh = gc.open_by_key(spreadsheet_id)
    ws_crm = sh.worksheet(ABA_CRM)

    # Lê CRM inteiro (tabela)
    records = _retry_quota(lambda: ws_crm.get_all_records())
    df = pd.DataFrame(records)

    # Colunas esperadas do CRM
    col_status = "STATUS"
    col_wpp = "WHATSAPP"
    col_nome = "NOME"
    col_prio = "PRIORIDADE"
    col_dias = "DIAS DE INATIVIDADE"
    col_prox = "PROXIMO CONTATO PERMITIDO"

    for c in [col_status, col_wpp, col_nome, col_prox]:
        if c not in df.columns:
            raise ValueError(f"CRM_GERAL: coluna '{c}' não encontrada.")

    hoje = date.today()

    # Filtra por status
    df["__status"] = df[col_status].astype(str).str.strip()
    df = df[df["__status"].str.upper() == status_escolhido.upper()].copy()

    # Filtra cooldown: PROXIMO CONTATO PERMITIDO <= hoje (ou vazio = pode)
    df["__prox_date"] = df[col_prox].apply(_parse_date_any)
    df = df[(df["__prox_date"].isna()) | (df["__prox_date"] <= hoje)].copy()

    # Tira whatsapp inválido
    df["__wpp"] = df[col_wpp].apply(_digits_only)
    df = df[df["__wpp"].astype(str).str.len() >= 10].copy()

    # Ordena para pegar “os melhores” (sem aleatoriedade):
    # prioridade DESC, dias_inatividade DESC
    if col_prio in df.columns:
        df["__prio"] = pd.to_numeric(df[col_prio], errors="coerce").fillna(0)
    else:
        df["__prio"] = 0

    if col_dias in df.columns:
        df["__dias"] = pd.to_numeric(df[col_dias], errors="coerce").fillna(0)
    else:
        df["__dias"] = 0

    df = df.sort_values(["__prio", "__dias"], ascending=[False, False])

    # Corta no total desejado
    df = df.head(int(total)).copy()

    # Monta DF final no padrão do app
    out = pd.DataFrame(
        {
            "whatsapp": df["__wpp"],
            "nome": df[col_nome].astype(str).str.strip(),
            "status": df["__status"],
            "campanha": ("" if campanha is None else str(campanha).strip()),
            "enviado": False,
        }
    )

    return out.reset_index(drop=True)

