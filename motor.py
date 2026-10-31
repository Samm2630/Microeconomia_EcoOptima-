"""

Modelo:
    Q = A * L^alpha * K^beta ,   A = A_base * (1 + g * f(TE))   (Cobb-Douglas adaptada)
    CO2e = sum(consumo_i * FE_i)                       (huella de carbono)
    CT_eco = CT_operativo + impuesto ecológico         (costo eco-ajustado)
"""
from __future__ import annotations

import csv
import json
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
RUTA_PARAMS = BASE / "datos" / "parametros.json"
RUTA_HIST = BASE / "datos" / "historial.csv"

RESINAS_VIRGENES = ["PE", "PP", "PET", "PVC", "PS"]


# Capa 3)
# --------------------------------------------------------------------------
PARAMETROS_POR_DEFECTO = {'_nota': 'Valores REFERENCIALES. Reemplazar con datos reales de Tecniplast, S.A. (tarifa '
          'CNEE/EEGSA, factor de emision del AMM, facturas de resina, planilla).',
 'modelo': {'A_base': 96.0,
            'alpha': 0.4,
            'beta': 0.6,
            'te_referencia': 0.4,
            'ahorro_energia_max': 0.35,
            'reduccion_merma_max': 0.5,
            'capacidad_horas_maquina': 3300,
            'ganancia_A_max': 0.15},
 'factores_emision_kgCO2e': {'electricidad_kwh': 0.25,
                             'agua_m3': 0.34,
                             'PE': 2.0,
                             'PP': 1.95,
                             'PET': 2.2,
                             'PVC': 2.1,
                             'PS': 3.0,
                             'PCR': 0.6,
                             'BIO': 1.2},
 'costos_GTQ': {'kwh': 1.35,
                'agua_m3': 12.0,
                'PE': 13.0,
                'PP': 13.5,
                'PET': 15.0,
                'PVC': 12.0,
                'PS': 14.5,
                'PCR': 11.0,
                'BIO': 28.0,
                'hora_trabajo': 30.0,
                'hora_maquina': 85.0,
                'precio_carbono_por_tonelada': 250.0,
                'impuesto_plastico_virgen_por_kg': 0.5},
 'umbrales_semaforo': {'intensidad_verde_kg_por_unidad': 0.15,
                       'intensidad_rojo_kg_por_unidad': 0.25,
                       'merma_amarillo_pct': 5.0,
                       'merma_rojo_pct': 10.0,
                       'uso_capacidad_amarillo': 0.85,
                       'uso_capacidad_rojo': 0.95},
 'entrada_por_defecto': {'kwh': 120000,
                         'agua_m3': 1500,
                         'resinas_kg': {'PE': 9000,
                                        'PP': 8000,
                                        'PET': 4000,
                                        'PVC': 2000,
                                        'PS': 2000},
                         'pcr_kg': 0,
                         'bio_kg': 0,
                         'trabajadores': 60,
                         'horas_trabajador': 200,
                         'horas_maquina': 3000,
                         'te': 0.4,
                         'merma_pct': 7.0}}


def cargar_parametros(ruta: Path = RUTA_PARAMS) -> dict:
    if not ruta.exists():
        guardar_parametros(PARAMETROS_POR_DEFECTO, ruta)
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def guardar_parametros(p: dict, ruta: Path = RUTA_PARAMS) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------
# Entrada
# --------------------------------------------------------------------------
@dataclass
class Entradas:
    kwh: float                  # Tierra: energía eléctrica (kWh/mes)
    agua_m3: float              # Tierra: agua (m3/mes)
    resinas_kg: dict            # Tierra: resinas vírgenes por tipo (kg/mes)
    pcr_kg: float               # Tierra: resina reciclada posconsumo (kg/mes)
    bio_kg: float               # Tierra: bioplástico (kg/mes)
    trabajadores: int           # Trabajo: operarios activos
    horas_trabajador: float     # Trabajo: horas por operario al mes (HL)
    horas_maquina: float        # Capital: horas de operación (K)
    te: float                   # Tecnología: índice de eficiencia TE en [0.1, 1.0]
    merma_pct: float            # Scrap sobre producción bruta (%)

    @property
    def L(self) -> float:
        return self.trabajadores * self.horas_trabajador

    @property
    def K(self) -> float:
        return self.horas_maquina

    @property
    def resina_virgen_kg(self) -> float:
        return sum(self.resinas_kg.values())


def entradas_desde_dict(d: dict) -> Entradas:
    return Entradas(**deepcopy(d))


# --------------------------------------------------------------------------
# Cálculo principal
# --------------------------------------------------------------------------
def _fraccion_tecnologica(te: float, p: dict) -> float:
    """0 si TE <= referencia; 1 si TE = 1.0 """
    ref = p["modelo"]["te_referencia"]
    return max(0.0, (te - ref) / (1.0 - ref))


def calcular(e: Entradas, p: dict, con_marginal: bool = True) -> dict:
    m, fe, c = p["modelo"], p["factores_emision_kgCO2e"], p["costos_GTQ"]
    te = min(max(e.te, 0.1), 1.0)
    frac = _fraccion_tecnologica(te, p)

    # --- Producción ---
    A = m["A_base"] * (1 + m["ganancia_A_max"] * frac)   # TE <= referencia: A = A_base
    q_bruta = A * (e.L ** m["alpha"]) * (e.K ** m["beta"]) if e.L > 0 and e.K > 0 else 0.0
    merma_ef = e.merma_pct / 100 * (1 - m["reduccion_merma_max"] * frac)
    Q = q_bruta * (1 - merma_ef)

    kwh_ef = e.kwh * (1 - m["ahorro_energia_max"] * frac)

    # --- Emisiones (kg CO2e) por fuente ---
    em = {
        "Electricidad": kwh_ef * fe["electricidad_kwh"],
        "Agua": e.agua_m3 * fe["agua_m3"],
        "Resinas vírgenes": sum(kg * fe[t] for t, kg in e.resinas_kg.items()),
        "Resina reciclada (PCR)": e.pcr_kg * fe["PCR"],
        "Bioplástico": e.bio_kg * fe["BIO"],
    }
    kg_total = sum(em.values())
    t_co2e = kg_total / 1000

    # --- Costos (GTQ) ---
    costos = {
        "Energía": kwh_ef * c["kwh"],
        "Agua": e.agua_m3 * c["agua_m3"],
        "Resinas": sum(kg * c[t] for t, kg in e.resinas_kg.items())
        + e.pcr_kg * c["PCR"] + e.bio_kg * c["BIO"],
        "Mano de obra": e.L * c["hora_trabajo"],
        "Capital (máquinas)": e.K * c["hora_maquina"],
    }
    ct_op = sum(costos.values())
    impuesto = t_co2e * c["precio_carbono_por_tonelada"] \
        + e.resina_virgen_kg * c["impuesto_plastico_virgen_por_kg"]
    ct_eco = ct_op + impuesto

    res = {
        "A": A, "Q": Q, "merma_efectiva_pct": merma_ef * 100, "kwh_efectivo": kwh_ef,
        "emisiones_kg": em, "t_co2e": t_co2e,
        "costos": costos, "ct_operativo": ct_op, "impuesto_ecologico": impuesto,
        "ct_eco": ct_eco,
        "costo_unitario_op": ct_op / Q if Q else 0.0,
        "costo_unitario_eco": ct_eco / Q if Q else 0.0,
        "kg_co2e_por_unidad": kg_total / Q if Q else 0.0,
        "unidades_por_kg_co2e": Q / kg_total if kg_total else 0.0,   # ratio de eficiencia ecológica
        "productividad_por_hora_hombre": Q / e.L if e.L else 0.0,
        "uso_capacidad": e.K / m["capacidad_horas_maquina"],
    }
    res["costo_ecologico_marginal"] = _costo_marginal(e, p, res) if con_marginal else 0.0
    return res


def _costo_marginal(e: Entradas, p: dict, base: dict, delta: float = 0.01) -> float:
    f = 1 + delta
    e2 = replace(
        e, kwh=e.kwh * f, agua_m3=e.agua_m3 * f, pcr_kg=e.pcr_kg * f, bio_kg=e.bio_kg * f,
        resinas_kg={k: v * f for k, v in e.resinas_kg.items()},
        trabajadores=e.trabajadores * f,   # K (capital) fijo: costo marginal de corto plazo
    )
    r2 = calcular(e2, p, con_marginal=False)
    dq = r2["Q"] - base["Q"]
    return (r2["ct_eco"] - base["ct_eco"]) / dq if dq else 0.0


# --------------------------------------------------------------------------
# Semáforo ecoeficiente
# --------------------------------------------------------------------------
def evaluar_semaforo(e: Entradas, r: dict, p: dict) -> dict:
    u = p["umbrales_semaforo"]
    alertas = []   # (nivel 0/1/2, factor, mensaje, recomendación)

    i = r["kg_co2e_por_unidad"]
    if i > u["intensidad_rojo_kg_por_unidad"]:
        alertas.append((2, "Tierra", f"Intensidad de carbono crítica: {i:.3f} kg CO2e/unidad",
                        "Sustituir resina virgen por PCR/bioplástico y reducir kWh."))
    elif i > u["intensidad_verde_kg_por_unidad"]:
        alertas.append((1, "Tierra", f"Intensidad de carbono elevada: {i:.3f} kg CO2e/unidad",
                        "Evaluar recirculación de agua y mezcla con resina reciclada."))

    mer = r["merma_efectiva_pct"]
    if mer > u["merma_rojo_pct"]:
        alertas.append((2, "Trabajo", f"Merma crítica: {mer:.1f} %",
                        "Capacitar en parametrización y purga; revisar matricería."))
    elif mer > u["merma_amarillo_pct"]:
        alertas.append((1, "Trabajo", f"Merma por encima de la meta: {mer:.1f} %",
                        "Programa de capacitación y mantenimiento preventivo de moldes."))

    uso = r["uso_capacidad"]
    if uso > u["uso_capacidad_rojo"]:
        alertas.append((2, "Capital", f"Sobreexplotación de maquinaria: {uso:.0%} de capacidad",
                        "Riesgo de desgaste y fugas térmicas; planificar mantenimiento o nueva inversión."))
    elif uso > u["uso_capacidad_amarillo"]:
        alertas.append((1, "Capital", f"Uso alto de maquinaria: {uso:.0%} de capacidad",
                        "Monitorear desgaste de inyectoras y moldes."))

    if e.te < 0.5:
        alertas.append((1, "Tecnología", f"Índice tecnológico bajo (TE = {e.te:.2f})",
                        "Migrar a servo-inyectoras y moldes de colada caliente."))

    nivel = max((a[0] for a in alertas), default=0)
    return {"nivel": nivel, "etiqueta": ["VERDE: Óptimo / Sostenible",
                                         "AMARILLO: Advertencia por ineficiencia",
                                         "ROJO: Crítico / Sobreexplotación"][nivel],
            "color": ["#2e7d32", "#f9a825", "#c62828"][nivel], "alertas": alertas}


# --------------------------------------------------------------------------
# Simulación "what-if"
# --------------------------------------------------------------------------
def aplicar_escenario(e: Entradas, *, red_kwh_pct=0.0, red_agua_pct=0.0,
                      sust_pcr_pct=0.0, sust_bio_pct=0.0,
                      te_nuevo: float | None = None, red_merma_pct=0.0) -> Entradas:
    """Devuelve unas Entradas nuevas con las medidas aplicadas (no modifica la original)."""
    sust_total = min(sust_pcr_pct + sust_bio_pct, 100.0) / 100
    virgen = e.resina_virgen_kg
    return replace(
        e,
        kwh=e.kwh * (1 - red_kwh_pct / 100),
        agua_m3=e.agua_m3 * (1 - red_agua_pct / 100),
        resinas_kg={t: kg * (1 - sust_total) for t, kg in e.resinas_kg.items()},
        pcr_kg=e.pcr_kg + virgen * sust_pcr_pct / 100,
        bio_kg=e.bio_kg + virgen * sust_bio_pct / 100,
        te=e.te if te_nuevo is None else te_nuevo,
        merma_pct=e.merma_pct * (1 - red_merma_pct / 100),
    )


def comparar(base: dict, esc: dict) -> list[dict]:
    """Tabla comparativa base vs escenario."""
    filas = [
        ("Producción Q (unid/mes)", "Q"),
        ("tCO2e emitidas", "t_co2e"),
        ("kg CO2e por unidad", "kg_co2e_por_unidad"),
        ("Costo operativo (GTQ)", "ct_operativo"),
        ("Impuesto ecológico (GTQ)", "impuesto_ecologico"),
        ("Costo eco-ajustado CT (GTQ)", "ct_eco"),
        ("Costo unitario eco (GTQ/unid)", "costo_unitario_eco"),
        ("Costo ecológico marginal (GTQ/unid)", "costo_ecologico_marginal"),
    ]
    out = []
    for nombre, k in filas:
        b, s = base[k], esc[k]
        out.append({"Indicador": nombre, "Base": b, "Escenario": s,
                    "Variación %": ((s - b) / b * 100) if b else 0.0})
    return out


def curva_tecnologia(e: Entradas, p: dict, pasos: int = 10) -> list[dict]:
    """Análisis de sensibilidad del índice TE (0.1 → 1.0)."""
    datos = []
    for i in range(1, pasos + 1):
        te = round(i / pasos, 2)
        r = calcular(replace(e, te=te), p)
        datos.append({"TE": te, "Q": r["Q"], "kg_co2e_por_unidad": r["kg_co2e_por_unidad"],
                      "costo_unitario_eco": r["costo_unitario_eco"]})
    return datos


# --------------------------------------------------------------------------
# Historial de simulaciones (CSV)
# --------------------------------------------------------------------------
CAMPOS_HIST = ["fecha", "nombre", "te", "Q", "t_co2e", "kg_co2e_por_unidad",
               "ct_operativo", "ct_eco", "costo_unitario_eco", "semaforo"]


def guardar_historial(nombre: str, e: Entradas, r: dict, semaforo: dict,
                      ruta: Path = RUTA_HIST) -> None:
    nuevo = not ruta.exists()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_HIST)
        if nuevo:
            w.writeheader()
        w.writerow({
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "nombre": nombre, "te": e.te,
            "Q": round(r["Q"]), "t_co2e": round(r["t_co2e"], 3),
            "kg_co2e_por_unidad": round(r["kg_co2e_por_unidad"], 4),
            "ct_operativo": round(r["ct_operativo"], 2), "ct_eco": round(r["ct_eco"], 2),
            "costo_unitario_eco": round(r["costo_unitario_eco"], 4),
            "semaforo": semaforo["etiqueta"].split(":")[0],
        })


def cargar_historial(ruta: Path = RUTA_HIST) -> list[dict]:
    if not ruta.exists():
        return []
    with open(ruta, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


if __name__ == "__main__":
    p = cargar_parametros()
    e = entradas_desde_dict(p["entrada_por_defecto"])
    r = calcular(e, p)
    print(f"Q = {r['Q']:,.0f} | tCO2e = {r['t_co2e']:.1f} | kg/unid = {r['kg_co2e_por_unidad']:.3f}")
    print(evaluar_semaforo(e, r, p)["etiqueta"])
