# src/mock_backend.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import pandas as pd


@dataclass
class MockState:
    crm_geral: pd.DataFrame
    log_envio: pd.DataFrame


def init_state() -> MockState:
    crm = pd.DataFrame(
        [
            {"whatsapp": "85999990001", "nome": "Cliente A", "status": "7-15", "ultimo_contato": "", "campanha_do_dia": ""},
            {"whatsapp": "85999990002", "nome": "Cliente B", "status": "16-30", "ultimo_contato": "", "campanha_do_dia": ""},
            {"whatsapp": "85999990003", "nome": "Cliente C", "status": "31-60", "ultimo_contato": "", "campanha_do_dia": ""},
            {"whatsapp": "85999990004", "nome": "Cliente D", "status": "61-90", "ultimo_contato": "", "campanha_do_dia": ""},
        ]
    )

    log = pd.DataFrame(columns=["data", "whatsapp", "status", "campanha"])
    return MockState(crm_geral=crm, log_envio=log)


def ensure_session_state(st) -> None:
    if "mock_state" not in st.session_state:
        st.session_state["mock_state"] = init_state()


def gerar_lista_fixa_mock(state: MockState) -> pd.DataFrame:
    # Emula "gerar lista fixa": pega alguns do CRM e monta uma lista
    lista = state.crm_geral.copy()
    lista["campanha"] = "FIXA"
    lista["enviado"] = False
    return lista[["whatsapp", "nome", "status", "campanha", "enviado"]].head(2)


def gerar_lista_pontual_mock(state: MockState, campanha: str) -> pd.DataFrame:
    lista = state.crm_geral.copy()
    lista["campanha"] = campanha
    lista["enviado"] = False
    return lista[["whatsapp", "nome", "status", "campanha", "enviado"]].head(2)


def atualizar_crm_por_lista(state: MockState, lista_df: pd.DataFrame) -> dict:
    # Emula "atualizarCRM_*": só pega enviados=True
    enviados = lista_df[lista_df["enviado"] == True].copy()
    if enviados.empty:
        return {"updated": 0, "log_added": 0}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Atualiza CRM_GERAL
    for _, row in enviados.iterrows():
        wpp = str(row["whatsapp"])
        campanha = str(row.get("campanha", ""))

        state.crm_geral.loc[state.crm_geral["whatsapp"] == wpp, "ultimo_contato"] = now
        state.crm_geral.loc[state.crm_geral["whatsapp"] == wpp, "campanha_do_dia"] = campanha

    # LOG_ENVIO
    new_logs = pd.DataFrame(
        [
            {
                "data": now,
                "whatsapp": str(r["whatsapp"]),
                "status": str(r.get("status", "")),
                "campanha": str(r.get("campanha", "")),
            }
            for _, r in enviados.iterrows()
        ]
    )
    state.log_envio = pd.concat([state.log_envio, new_logs], ignore_index=True)

    return {"updated": len(enviados), "log_added": len(enviados)}
