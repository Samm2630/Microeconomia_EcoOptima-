"""

Ejecutar con:  streamlit run app.py
"""
import json
from dataclasses import replace

import pandas as pd
import streamlit as st

import motor as mt

st.set_page_config(page_title="EcoOptima Systems", page_icon="", layout="wide")


def semaforo_html(s: dict) -> str:
    return (f"<div style='background:{s['color']};color:white;padding:14px 18px;"
            f"border-radius:10px;font-size:1.1rem;font-weight:600'>{s['etiqueta']}</div>")


def q(x):
    return f"{x:,.0f}"


# parámetros
if "params" not in st.session_state:
    st.session_state.params = mt.cargar_parametros()
P = st.session_state.params
D = P["entrada_por_defecto"]

st.title("EcoOptima Systems")
st.caption("Motor microeconómico-ambiental para Tecniplast, S.A. (beta)")

# sidebar: entradas
sb = st.sidebar
sb.header("Variables de entrada")

sb.subheader("Tierra (N)")
kwh = sb.number_input("Energía eléctrica (kWh/mes)", 0, 5_000_000, int(D["kwh"]), step=5000)
agua = sb.number_input("Agua operativa (m³/mes)", 0, 100_000, int(D["agua_m3"]), step=100)
resinas = {t: sb.number_input(f"Resina virgen {t} (kg/mes)", 0, 1_000_000,
                              int(D["resinas_kg"].get(t, 0)), step=500)
           for t in mt.RESINAS_VIRGENES}
pcr = sb.number_input("Resina reciclada PCR (kg/mes)", 0, 1_000_000, int(D["pcr_kg"]), step=500)
bio = sb.number_input("Bioplástico (kg/mes)", 0, 1_000_000, int(D["bio_kg"]), step=500)

sb.subheader("Trabajo (L)")
trab = sb.slider("Operarios activos", 1, 300, int(D["trabajadores"]))
hl = sb.slider("Horas por operario al mes (HL)", 40, 260, int(D["horas_trabajador"]))
merma = sb.slider("Merma / scrap actual (%)", 0.0, 20.0, float(D["merma_pct"]), 0.5)

sb.subheader("Capital (K)")
hk = sb.slider("Horas de operación de maquinaria", 100, 6000, int(D["horas_maquina"]), 50)

sb.subheader("Tecnología (T)")
tipo = sb.radio("Nivel tecnológico", ["Hidráulica tradicional", "Híbrida", "Servo-eléctrica + colada caliente", "Personalizado"],
                index=3)
te_preset = {"Hidráulica tradicional": 0.4, "Híbrida": 0.7, "Servo-eléctrica + colada caliente": 1.0}
if tipo == "Personalizado":
    te = sb.slider("Índice de eficiencia TE", 0.1, 1.0, float(D["te"]), 0.05)
else:
    te = te_preset[tipo]

E = mt.Entradas(kwh=kwh, agua_m3=agua, resinas_kg=resinas, pcr_kg=pcr, bio_kg=bio,
                trabajadores=trab, horas_trabajador=hl, horas_maquina=hk, te=te, merma_pct=merma)
R = mt.calcular(E, P)
S = mt.evaluar_semaforo(E, R, P)

# ---------------------------------------------------------------- pestañas
t1, t2, t3, t4, t5 = st.tabs(["Diagnóstico", "Simulación What-If", "Sensibilidad TE",
                              "Historial", "Parámetros"])

# ===== Diagnóstico
with t1:
    st.markdown(semaforo_html(S), unsafe_allow_html=True)
    st.write("")
    c = st.columns(5)
    c[0].metric("Producción Q", f"{q(R['Q'])} unid/mes")
    c[1].metric("Huella de carbono", f"{R['t_co2e']:.1f} tCO₂e")
    c[2].metric("kg CO₂e / unidad", f"{R['kg_co2e_por_unidad']:.3f}")
    c[3].metric("Costo eco-ajustado", f"Q {q(R['ct_eco'])}")
    c[4].metric("Costo marginal (CP)", f"Q {R['costo_ecologico_marginal']:.2f}/unid")

    c2 = st.columns(2)
    with c2[0]:
        st.subheader("Emisiones por fuente (kg CO₂e)")
        st.bar_chart(pd.Series(R["emisiones_kg"], name="kg CO2e"))
    with c2[1]:
        st.subheader("Estructura de costos (GTQ)")
        st.bar_chart(pd.Series(R["costos"] | {"Impuesto ecológico": R["impuesto_ecologico"]}, name="GTQ"))

    d = st.columns(3)
    d[0].metric("Costo unitario operativo", f"Q {R['costo_unitario_op']:.2f}")
    d[1].metric("Costo unitario eco-ajustado", f"Q {R['costo_unitario_eco']:.2f}")
    d[2].metric("Eficiencia ecológica", f"{R['unidades_por_kg_co2e']:.1f} unid/kg CO₂e")

    st.subheader("Alertas y recomendaciones")
    if not S["alertas"]:
        st.success("Sin alertas: la operación se encuentra en zona sostenible.")
    for nivel, factor, msg, rec in sorted(S["alertas"], reverse=True):
        (st.error if nivel == 2 else st.warning)(f"**{factor}** — {msg}\n\n➜ {rec}")

    nombre = st.text_input("Nombre de la simulación", "Línea base")
    if st.button("Guardar en historial"):
        mt.guardar_historial(nombre, E, R, S)
        st.success("Simulación guardada en datos/historial.csv")

# ===== What-if
with t2:
    st.markdown("Ajuste las medidas y compare el **escenario** contra la **línea base** actual.")
    a, b = st.columns(2)
    with a:
        r_kwh = st.slider("Reducción de consumo eléctrico (%)", 0, 50, 15)
        r_agua = st.slider("Reducción de agua por recirculación (%)", 0, 80, 30)
        r_mer = st.slider("Reducción de merma por capacitación (%)", 0, 80, 30)
    with b:
        s_pcr = st.slider("Resina virgen sustituida por PCR (%)", 0, 100, 20)
        s_bio = st.slider("Resina virgen sustituida por bioplástico (%)", 0, 100 - s_pcr, 0)
        te_n = st.slider("Nuevo índice tecnológico TE", 0.1, 1.0, max(E.te, 0.8), 0.05)

    E2 = mt.aplicar_escenario(E, red_kwh_pct=r_kwh, red_agua_pct=r_agua, sust_pcr_pct=s_pcr,
                              sust_bio_pct=s_bio, te_nuevo=te_n, red_merma_pct=r_mer)
    R2 = mt.calcular(E2, P)
    S2 = mt.evaluar_semaforo(E2, R2, P)

    x, y = st.columns(2)
    x.markdown("**Base**"); x.markdown(semaforo_html(S), unsafe_allow_html=True)
    y.markdown("**Escenario**"); y.markdown(semaforo_html(S2), unsafe_allow_html=True)
    st.write("")

    df = pd.DataFrame(mt.comparar(R, R2))
    st.dataframe(df.style.format({"Base": "{:,.2f}", "Escenario": "{:,.2f}", "Variación %": "{:+.1f}%"}),
                 hide_index=True, use_container_width=True)

    evitadas = R["t_co2e"] - R2["t_co2e"]
    ahorro = R["ct_eco"] - R2["ct_eco"]
    st.info(f"Emisiones evitadas: **{evitadas:.1f} tCO₂e/mes** · "
            f"Cambio en costo eco-ajustado: **Q {ahorro:,.0f}/mes** "
            f"({'ahorro' if ahorro >= 0 else 'mayor costo'}).")
    comp = pd.DataFrame({"Base": R["emisiones_kg"], "Escenario": R2["emisiones_kg"]})
    st.bar_chart(comp)

# ===== Sensibilidad TE
with t3:
    st.markdown("Efecto del índice tecnológico **TE** sobre producción, emisiones y costo por unidad "
                "(el resto de variables se mantiene constante).")
    curva = pd.DataFrame(mt.curva_tecnologia(E, P)).set_index("TE")
    l, r = st.columns(2)
    l.subheader("kg CO₂e por unidad"); l.line_chart(curva["kg_co2e_por_unidad"])
    r.subheader("Costo unitario eco-ajustado (GTQ)"); r.line_chart(curva["costo_unitario_eco"])
    st.subheader("Producción Q"); st.line_chart(curva["Q"])

# ===== Historial
with t4:
    h = mt.cargar_historial()
    if h:
        dfh = pd.DataFrame(h)
        st.dataframe(dfh, hide_index=True, use_container_width=True)
        st.download_button("⬇️ Descargar CSV", dfh.to_csv(index=False).encode("utf-8"),
                           "historial_ecooptima.csv", "text/csv")
    else:
        st.info("Aún no hay simulaciones guardadas.")

# ===== Parámetros
with t5:
    st.markdown("Edite tarifas, factores de emisión, elasticidades y umbrales (archivo `datos/parametros.json`).")
    txt = st.text_area("parametros.json", json.dumps(P, indent=2, ensure_ascii=False), height=450)
    if st.button("Guardar parámetros"):
        try:
            nuevo = json.loads(txt)
            mt.guardar_parametros(nuevo)
            st.session_state.params = nuevo
            st.success("Parámetros guardados. Recargando…")
            st.rerun()
        except json.JSONDecodeError as err:
            st.error(f"JSON inválido: {err}")
