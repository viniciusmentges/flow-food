import streamlit as st

def render_sidebar(page_names: list[str]) -> str:
    with st.sidebar:
        st.title("Flow Food")
        st.caption("Painel Operacional")
        st.divider()

        selected = st.radio("Menu", page_names, index=0)

        st.divider()
        st.caption("Rodando local (localhost)")
    return selected
