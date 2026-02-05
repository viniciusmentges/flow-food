import streamlit as st
import pandas as pd

from src.services.limites_geracao import pode_gerar_lista_hoje, registrar_geracao_lista
from src.services.sheets import load_sheet_df, gerar_lista_fixa
from src.services.pontual_backend import atualizar_crm_por_lista_real


def page_lista_fixa():
    st.header("Lista Fixa")

    # ✅ Modo admin com key (não reseta em rerun)
    st.toggle("Modo Admin (teste)", value=False, key="admin_mode")
    is_admin = st.session_state["admin_mode"]

    col1, col2 = st.columns(2)

    # ---------------------------
    # BOTÃO: GERAR LISTA (SHEETS)
    # ---------------------------
    with col1:
        if st.button("Gerar Lista Fixa", type="primary"):
            SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]

            # trava: cliente só 1x por dia (admin/teste libera)
            if not pode_gerar_lista_hoje(st, SPREADSHEET_ID, "LISTA_FIXA_LAST_DATE", is_admin):
                st.warning("Você já gerou a Lista Fixa hoje. Tente novamente amanhã.")
                st.stop()

            df_crm = load_sheet_df("CRM_GERAL")
            df_cfg = load_sheet_df("CONFIGURACAO")

            # ---------------------------
            # DIAGNÓSTICO (DEBUG)
            # ---------------------------
            st.divider()
            st.subheader("🧪 Diagnóstico (Lista Fixa)")

            st.write("✅ Status no CRM_GERAL (contagem):")
            if "STATUS" in df_crm.columns:
                st.write(df_crm["STATUS"].astype(str).value_counts(dropna=False))
            else:
                st.error("❌ Não achei a coluna STATUS no CRM_GERAL")

            st.write("✅ Regras no CONFIGURACAO (STATUS e QTD POR DIA):")
            if "STATUS" in df_cfg.columns and "QTD POR DIA" in df_cfg.columns:
                st.dataframe(df_cfg[["STATUS", "QTD POR DIA"]])
            else:
                st.error("❌ Não achei as colunas STATUS e/ou QTD POR DIA no CONFIGURACAO")

            # ---------
            # ELEGIVEL
            # ---------
            st.write("✅ ELEGIVEL (contagem geral):")
            if "ELEGIVEL" in df_crm.columns:
                st.write(
                    df_crm["ELEGIVEL"]
                    .astype(str)
                    .str.upper()
                    .str.strip()
                    .value_counts(dropna=False)
                )
            else:
                st.warning("⚠️ Não existe a coluna ELEGIVEL no CRM_GERAL")

            # Quantos são ELEGIVEL=SIM por STATUS
            if "STATUS" in df_crm.columns and "ELEGIVEL" in df_crm.columns:
                df_tmp = df_crm.copy()
                df_tmp["STATUS_N"] = df_tmp["STATUS"].astype(str).str.upper().str.strip()
                df_tmp["ELEGIVEL_N"] = df_tmp["ELEGIVEL"].astype(str).str.upper().str.strip()

                st.write("✅ Por STATUS: quantos estão com ELEGIVEL = SIM")
                st.dataframe(
                    df_tmp[df_tmp["ELEGIVEL_N"].eq("SIM")]["STATUS_N"]
                    .value_counts()
                    .reset_index()
                    .rename(columns={"index": "STATUS", "STATUS_N": "QTD_ELEGIVEL_SIM"})
                )

            # ---------------------------
            # PROXIMO CONTATO PERMITIDO (COOLDOWN)
            # ---------------------------
            st.write("✅ PROXIMO CONTATO PERMITIDO (cooldown):")
            if "PROXIMO CONTATO PERMITIDO" in df_crm.columns and "STATUS" in df_crm.columns:
                df_tmp2 = df_crm.copy()
                df_tmp2["STATUS_N"] = df_tmp2["STATUS"].astype(str).str.upper().str.strip()
                df_tmp2["PCP"] = pd.to_datetime(df_tmp2["PROXIMO CONTATO PERMITIDO"], errors="coerce")

                hoje = pd.to_datetime(pd.Timestamp.today().date())

                bloqueados = df_tmp2[(df_tmp2["PCP"].notna()) & (df_tmp2["PCP"] > hoje)]

                st.write("⛔ Bloqueados por cooldown (PCP > hoje) por STATUS:")
                st.dataframe(
                    bloqueados["STATUS_N"]
                    .value_counts()
                    .reset_index()
                    .rename(columns={"index": "STATUS", "STATUS_N": "QTD_BLOQUEADOS"})
                )
            else:
                st.warning("⚠️ Não existe a coluna PROXIMO CONTATO PERMITIDO (ou STATUS) no CRM_GERAL")

            # ---------------------------
            # GERA A LISTA
            # ---------------------------
            st.session_state["lista_fixa"] = gerar_lista_fixa(df_crm, df_cfg)

            # registra que gerou hoje
            registrar_geracao_lista(st, SPREADSHEET_ID, "LISTA_FIXA_LAST_DATE")

            st.success("Lista fixa gerada (Google Sheets).")

    # ---------------------------
    # BOTÃO: ATUALIZAR CRM (SHEETS REAL)
    # ---------------------------
    with col2:
        if st.button("Atualizar CRM (Fixa)"):
            if "lista_fixa" not in st.session_state:
                st.warning("Gere a lista fixa antes.")
                st.stop()

            df = st.session_state["lista_fixa"].copy()

            if "ENVIADO?" not in df.columns:
                st.warning("Coluna ENVIADO? não encontrada na lista.")
                st.stop()

            if df["ENVIADO?"].fillna(False).sum() == 0:
                st.warning("Marque pelo menos 1 contato como ENVIADO antes de atualizar.")
                st.stop()

            df_real = pd.DataFrame({
                "whatsapp": df.get("WHATSAPP"),
                "nome": df.get("NOME"),
                "status": df.get("STATUS"),
                "campanha": df.get("CAMPANHA"),
                "enviado": df.get("ENVIADO?"),
            })

            SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
            res = atualizar_crm_por_lista_real(st, SPREADSHEET_ID, df_real)

            st.success(f"Atualizado (FIXA)! {res['updated']} contatos gravados no CRM e no LOG.")

    st.divider()

    # ---------------------------
    # TABELA: MOSTRAR LISTA
    # ---------------------------
    if "lista_fixa" not in st.session_state:
        st.warning("Nenhuma lista fixa gerada ainda.")
        return

    st.subheader("LISTA_FIXA (Google Sheets)")

    df_base = st.session_state["lista_fixa"].copy().reset_index(drop=True)

    # ✅ Forçar ENVIADO? como boolean
    if "ENVIADO?" in df_base.columns:
        df_base["ENVIADO?"] = df_base["ENVIADO?"].fillna(False).astype(bool)

    cols_show = []
    for c in ["LINK", "ENVIADO?", "NOME", "WHATSAPP", "STATUS", "CAMPANHA"]:
        if c in df_base.columns:
            cols_show.append(c)

    df_view = df_base[cols_show].copy() if cols_show else df_base.copy()

    with st.form("form_lista_fixa"):
        edited = st.data_editor(
            df_view,
            use_container_width=True,
            num_rows="fixed",
            hide_index=True,
            key="editor_lista_fixa_form",
            column_config={
                "ENVIADO?": st.column_config.CheckboxColumn(
                    "Enviado",
                    help="Marque após enviar no WhatsApp"
                ),
                "LINK": st.column_config.LinkColumn(
                    "ABRIR",
                    display_text="ABRIR",
                    help="Abrir conversa no WhatsApp"
                ),
            },
            disabled=[c for c in df_view.columns if c != "ENVIADO?"],
        )

        aplicar = st.form_submit_button("Atualizar CRM (Fixa)")

    if aplicar:
        if "ENVIADO?" in edited.columns and "ENVIADO?" in df_base.columns:
            df_base["ENVIADO?"] = edited["ENVIADO?"].fillna(False).astype(bool)

        st.session_state["lista_fixa"] = df_base
        st.success("Marcações aplicadas. Agora clique no botão 'Atualizar CRM (Fixa)' acima para gravar no Sheets.")
