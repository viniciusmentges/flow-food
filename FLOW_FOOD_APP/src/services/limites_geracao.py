import time
from datetime import date

import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials


ABA_CONTROLE = "CONTROLE_APP"
COL_CHAVE = "CHAVE"
COL_VALOR = "VALOR"


def _retry_quota(fn, max_tries: int = 6):
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


def _get_client_from_secrets(st):
    info = dict(st.secrets["gcp_service_account"])
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)


def _get_value_by_key(ws, key: str) -> str:
    # procura na coluna A (CHAVE) e retorna valor da coluna B
    keys = ws.col_values(1)  # A
    for i, k in enumerate(keys, start=1):
        if str(k).strip() == key:
            return str(ws.cell(i, 2).value or "").strip()
    return ""


def _set_value_by_key(ws, key: str, value: str):
    keys = ws.col_values(1)
    for i, k in enumerate(keys, start=1):
        if str(k).strip() == key:
            ws.update_cell(i, 2, value)
            return
    # se não achar a chave, cria uma linha nova
    ws.append_row([key, value], value_input_option="USER_ENTERED")


def pode_gerar_lista_hoje(st, spreadsheet_id: str, chave: str, is_admin: bool) -> bool:
    """
    Se is_admin=True -> sempre pode (modo teste/dev).
    Se is_admin=False -> só pode 1x por dia para cada chave.
    """
    if is_admin:
        return True

    hoje = date.today().isoformat()  # salva em ISO pra não quebrar
    gc = _get_client_from_secrets(st)
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(ABA_CONTROLE)

    last = _retry_quota(lambda: _get_value_by_key(ws, chave))

    # se já gerou hoje, bloqueia
    if last == hoje:
        return False

    return True


def registrar_geracao_lista(st, spreadsheet_id: str, chave: str):
    hoje = date.today().isoformat()
    gc = _get_client_from_secrets(st)
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(ABA_CONTROLE)

    _retry_quota(lambda: _set_value_by_key(ws, chave, hoje))
