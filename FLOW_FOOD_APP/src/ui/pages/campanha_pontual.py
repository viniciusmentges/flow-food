import streamlit as st
import re
from urllib.parse import quote

from src.services.limites_geracao import (
    pode_gerar_lista_hoje,
    registrar_geracao_lista,
)
from src.services.sheets import ler_lista_pontual_sheets
from src.services.pontual_backend import (
    atualizar_crm_por_lista_real,
    gerar_lista_pontual_por_status_real,
)


def to_wa_me(phone_raw: str, msg: str = "") -> str:
    s = "" if phone_raw is None else str(phone_raw)
    digits = re.sub(r"\D", "", s)

    # remove 55 se vier no começo
    if digits.startswith("55"):
        digits = digits[2:]

    # precisa ter DDD + número
    if len(digits) < 10:
        return ""

    base = f"https://wa.me/55{digits}"

    msg = "" if msg is None else str(msg).strip()
    if not msg:
        return base

    encoded = quote(msg, safe="")
    return f"{base}?text={encoded}"


def page_campanha_pontual():
    st.header("Campanha Pontual")

    # ---------------------------
    # MODO ADMIN
    # ---------------------------
    st.toggle("Modo Admin (teste)", value=False, key="admin_mode")
    is_admin = st.session_state["admin_mode"]

    campanha = st.text_input("Campanha", placeholder="CUPOM10OFF")
    mensagem = st.text_area(
        "Mensagem",
        height=120,
        placeholder="Digite a mensagem que será enviada no WhatsApp",
    )

    # ---------------------------
    # TIPO DE LISTA PONTUAL
    # ---------------------------
    tipo_lista = st.selectbox(
        "Tipo de Lista Pontual",
        [
            "GERAL (37 divididos por status)",
            "POR STATUS (37 do mesmo status)",
        ],
        index=0,
    )

    status_escolhido = None
    if tipo_lista.startswith("POR STATUS"):
        status_escolhido = st.selectbox(
            "Escolha o STATUS",
            [
                "PROSPECT",
                "ATIVO",
                "ATIVO_VIP",
                "ESFRIANDO",
                "ESFRIANDO_VIP",
                "INATIVO",
                "INATIVO_VIP",
                "SUMIDO",
                "SUMIDO_VIP",
            ],
            index=0,
        )

    col1, col2 = st.columns(2)

    # ---------------------------
    # GERAR LISTA
    # ---------------------------
    with col1:
        if st.button("Gerar Lista Pontual", type="primary"):
            SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]

            if not pode_gerar_lista_hoje(
                st,
                SPREADSHEET_ID,
                "LISTA_PONTUAL_LAST_DATE",
                is_admin,
            ):
                st.warning("Você já gerou a Lista Pontual hoje. Tente novamente amanhã.")
                st.stop()

            # -------- MODO GERAL (planilha) --------
            if tipo_lista.startswith("GERAL"):
                df = ler_lista_pontual_sheets(st, SPREADSHEET_ID)

                if campanha and "campanha" in df.columns:
                    df["campanha"] = campanha

            # -------- MODO POR STATUS --------
            else:
                df = gerar_lista_pontual_por_status_real(
                    st,
                    SPREADSHEET_ID,
                    status_escolhido=status_escolhido,
                    total=37,
                    campanha=campanha,
                )

                if len(df) < 37:
                    st.warning(
                        f"⚠️ Só encontrei {len(df)} clientes elegíveis hoje "
                        f"no status '{status_escolhido}' (cooldown respeitado)."
                    )

            st.session_state["lista_pontual"] = df
            registrar_geracao_lista(
                st,
                SPREADSHEET_ID,
                "LISTA_PONTUAL_LAST_DATE",
            )

            st.success("Lista pontual gerada.")

    # ---------------------------
    # TABELA + MARCAÇÃO
    # ---------------------------
    with col2:
        if "lista_pontual" not in st.session_state:
            st.info("Gere a lista pontual antes de atualizar.")
        else:
            df_full = (
                st.session_state["lista_pontual"]
                .copy()
                .reset_index(drop=True)
            )

            # garante coluna enviado
            if "enviado" not in df_full.columns:
                df_full["enviado"] = False
            df_full["enviado"] = (
                df_full["enviado"]
                .fillna(False)
                .astype(bool)
            )

            msg_fallback = mensagem

            def pick_msg(row):
                if "mensagem" in row and str(row["mensagem"]).strip():
                    return row["mensagem"]
                if "MENSAGEM" in row and str(row["MENSAGEM"]).strip():
                    return row["MENSAGEM"]
                return msg_fallback

            df_full["link"] = df_full.apply(
                lambda r: to_wa_me(r.get("whatsapp"), pick_msg(r)),
                axis=1,
            )

            cols_show = []
            for c in ["link", "enviado", "nome", "whatsapp", "status", "campanha"]:
                if c in df_full.columns:
                    cols_show.append(c)

            df_view = df_full[cols_show].copy()

            with st.form("form_pontual_mark"):
                edited = st.data_editor(
                    df_view,
                    use_container_width=True,
                    num_rows="fixed",
                    hide_index=True,
                    key="editor_lista_pontual_form",
                    column_config={
                        "link": st.column_config.LinkColumn(
                            "ABRIR",
                            display_text="ABRIR",
                            help="Abrir conversa no WhatsApp",
                        ),
                        "enviado": st.column_config.CheckboxColumn(
                            "Enviado",
                            help="Marque após enviar no WhatsApp",
                        ),
                    },
                    disabled=[c for c in df_view.columns if c != "enviado"],
                )

                aplicar = st.form_submit_button("Aplicar Marcações")

            if aplicar:
                if "enviado" in edited.columns:
                    df_full["enviado"] = (
                        edited["enviado"]
                        .fillna(False)
                        .astype(bool)
                    )

                st.session_state["lista_pontual"] = df_full.drop(
                    columns=["link"],
                    errors="ignore",
                )

                st.success(
                    "Marcações aplicadas. Agora clique em "
                    "'Atualizar CRM (Pontual)'."
                )

            # ---------------------------
            # ATUALIZAR CRM
            # ---------------------------
            if st.button("Atualizar CRM (Pontual)"):
                df_send = st.session_state["lista_pontual"].copy()

                if (
                    "enviado" not in df_send.columns
                    or df_send["enviado"].sum() == 0
                ):
                    st.warning("Marque pelo menos 1 contato como ENVIADO.")
                    st.stop()

                SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
                res = atualizar_crm_por_lista_real(
                    st,
                    SPREADSHEET_ID,
                    df_send,
                )

                st.success(
                    f"Atualizado! {res['updated']} contatos gravados "
                    f"no CRM e no LOG."
                )

    st.divider()
