from __future__ import annotations

import time
import json
from pathlib import Path
from typing import Optional

import streamlit as st

from Utils.questionario_self_report import (          # [PATCH]
    SEZIONI_SR,                                        # [PATCH]
    SCALA_LIKERT_7,                                    # [PATCH]
    serializza_per_db_sr,                              # [PATCH]
    compila_campi_profilo,                             # [PATCH]
)

import json
from Utils.database import (
    leggi_tutti_partecipanti,
    leggi_partecipante,
    leggi_risposte_questionario,
    segna_consenso_firmato,
    segna_t0_completato,
    aggiorna_fase,
    salva_risposte_questionario,
)
from Utils.questionario_t0 import (
    SEZIONE_A,
    SEZIONE_D,
    SEZIONE_E,
    serializza_per_db,
    correggi_item,
)
from Utils.questionario_t1 import (
    SEZIONI_T1,
    SCALA_LIKERT,
    serializza_per_db_t1,
)
from Utils.chat_profilazione import (
    SessioneProfilazione,
    TURNI_MINIMI_UTENTE as TURNI_MINIMI_PROFILAZIONE,
)
from Utils.chat_sperimentale import (
    SessioneChat,
    TURNI_MINIMI_UTENTE as TURNI_MINIMI_SPERIMENTALE,
    TURNI_MASSIMI_UTENTE,
)

DURATA_TARGET_MINUTI = 10

CHAT_CONFIG: dict[str, dict] = {
    "chat_1": {"modalita": "controllo", "numero": 1, "etichetta": "Chat 1 — Assistente A"},
    "chat_2": {"modalita": "velato", "numero": 2, "etichetta": "Chat 2 — Assistente B"},
    "chat_3": {"modalita": "diretto", "numero": 3, "etichetta": "Chat 3 — Assistente C"},
}

FASE_DOPO_CHAT: dict[str, str] = {
    "chat_1": "chat_2",
    "chat_2": "chat_3",
    "chat_3": "t1",
}


st.set_page_config(
    page_title="Studio AI — Area Partecipante",
    page_icon="",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# Definizione della scala Likert formale (già convertita in forma impersonale/formale)
SCALA_LIKERT_FORMALE = {
    1: "Completamente in disaccordo",
    2: "In forte disaccordo",
    3: "Piuttosto in disaccordo",
    4: "Né d'accordo né in disaccordo",
    5: "Piuttosto d'accordo",
    6: "In forte accordo",
    7: "Completamente d'accordo",
}

def _renderizza_scala_likert() -> None:
    with st.container(border=True):
        st.caption("Legenda scala di risposta")
        col_scala = st.columns(7)
        for i, (val, etich) in enumerate(SCALA_LIKERT_FORMALE.items()):
            col_scala[i].markdown(f"**{val}**  \n{etich}")

def _init_sessione() -> None:
    defaults = {
        "partecipante_id": None,
        "partecipante_dati": None,
        "sessione_profilazione": None,
        "sessione_chat_1": None,
        "sessione_chat_2": None,
        "sessione_chat_3": None,
        "timestamp_inizio_chat": None,
    }
    for chiave, valore in defaults.items():
        if chiave not in st.session_state:
            st.session_state[chiave] = valore

def _recupera_parametri_t0(partecipante_id: str) -> tuple[float, str]:
    risposte = leggi_risposte_questionario(partecipante_id, "t0")
    mappa = {r["id_item"]: r for r in risposte}

    valori_nfc = []
    for item in SEZIONE_D:
        r = mappa.get(item.id)
        if r and r.get("valore_numerico"):
            valori_nfc.append(correggi_item(item, r["valore_numerico"]))
    nfc_score = round(sum(valori_nfc) / len(valori_nfc), 2) if valori_nfc else 4.0

    freq_r = mappa.get("E4")
    frequenza_ai = (
        freq_r["valore_testo"]
        if freq_r and freq_r.get("valore_testo")
        else "Occasionalmente"
    )
    return nfc_score, frequenza_ai


# File esterno agli script: contiene gli assegnamenti sperimentali per ogni partecipante.
PERCORSO_CONFIG_ASSEGNAMENTI = Path(__file__).resolve().with_name("config_assegnamenti.json")


def _carica_config_assegnamenti() -> dict:
    """Carica gli assegnamenti dal JSON esterno, senza imporre un numero fisso di partecipanti."""
    if not PERCORSO_CONFIG_ASSEGNAMENTI.exists():
        raise FileNotFoundError(
            f"File degli assegnamenti non trovato: {PERCORSO_CONFIG_ASSEGNAMENTI}. "
            "Crea il file partendo da config_assegnamenti_template.json."
        )
    try:
        with PERCORSO_CONFIG_ASSEGNAMENTI.open("r", encoding="utf-8") as file:
            config = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Il file {PERCORSO_CONFIG_ASSEGNAMENTI.name} non è un JSON valido "
            f"(riga {exc.lineno}, colonna {exc.colno}): {exc.msg}"
        ) from exc

    partecipanti = config.get("partecipanti") if isinstance(config, dict) else None
    if not isinstance(partecipanti, dict):
        raise ValueError("Nel file di configurazione deve esserci un oggetto 'partecipanti'.")
    return partecipanti


def _recupera_assegnamento_chat(partecipante_id: str, numero_chat: int) -> dict:
    """Restituisce l'assegnamento della chat per l'ID esatto presente nel database."""
    partecipanti = _carica_config_assegnamenti()
    chiave = str(partecipante_id)
    if chiave not in partecipanti:
        raise KeyError(
            f"Nessun assegnamento configurato per l'ID partecipante '{chiave}'. "
            f"Aggiungi questo ID in '{PERCORSO_CONFIG_ASSEGNAMENTI.name}'."
        )

    dati_partecipante = partecipanti[chiave]
    chats = dati_partecipante.get("chat") if isinstance(dati_partecipante, dict) else None
    chiave_chat = f"chat_{numero_chat}"
    if not isinstance(chats, dict) or chiave_chat not in chats:
        raise KeyError(
            f"Assegnamento '{chiave_chat}' mancante per il partecipante '{chiave}'. "
            f"Completa il file '{PERCORSO_CONFIG_ASSEGNAMENTI.name}'."
        )

    assegnamento = chats[chiave_chat]
    campi_obbligatori = ("modalita", "dominio", "llm")
    mancanti = [campo for campo in campi_obbligatori if not assegnamento.get(campo)]
    if mancanti:
        raise ValueError(
            f"Assegnamento '{chiave_chat}' del partecipante '{chiave}': "
            f"campi obbligatori mancanti o vuoti: {', '.join(mancanti)}."
        )

    return {
        "modalita": str(assegnamento["modalita"]).strip().lower(),
        "dominio": str(assegnamento["dominio"]).strip().lower(),
        "llm": str(assegnamento["llm"]).strip(),
        "etichetta": str(assegnamento.get("etichetta", f"Chat {numero_chat} — Assistente {chr(64 + numero_chat)}")),
    }


def _render_messaggi(messaggi: list[dict]) -> None:
    """Mostra la conversazione usando i componenti nativi di Streamlit."""
    for msg in messaggi:
        ruolo = msg.get("ruolo", "")
        contenuto = msg.get("contenuto", "")
        if ruolo == "assistente":
            with st.chat_message("assistant"):
                st.markdown(contenuto)
        elif ruolo == "utente":
            with st.chat_message("user"):
                st.markdown(contenuto)


def _render_step_flusso(fase_corrente: str) -> None:
    fasi_ordinate = [
        ("self_report", "1. Questionario personale"),
        ("t0", "2. Questionario iniziale"),
        ("profilazione", "3. Conversazione iniziale"),
        ("chat_1", "4. Conversazione 1"),
        ("chat_2", "5. Conversazione 2"),
        ("chat_3", "6. Conversazione 3"),
        ("t1", "7. Questionario finale"),
        ("t2", "8. Questionario di aggiornamento (72h)"),
    ]

    st.markdown(
        """
        <style>
        .step-container {
            display: flex;
            gap: 8px;
            justify-content: space-between;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        .step-box {
            flex: 1;
            padding: 8px 10px;
            border-radius: 6px;
            font-size: 0.8rem;
            text-align: center;
            border: 1px solid #e5e7eb;
            background-color: #f9fafb;
            color: #6b7280;
        }
        .step-box.attiva {
            background-color: #6495ED;
            color: #ffffff;
            border-color: #6495ED;
            font-weight: 600;
        }
        .step-box.fatta {
            background-color: #8FBC8F;
            color: #ffffff;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    html_steps = '<div class="step-container">'
    for fase, etichetta in fasi_ordinate:
        classe = ""
        if fase == fase_corrente:
            classe = "attiva"
        elif _fase_precedente(fase, fase_corrente):
            classe = "fatta"
        html_steps += f'<div class="step-box {classe}">{etichetta}</div>'
    html_steps += '</div>'
    st.markdown(html_steps, unsafe_allow_html=True)
    if fase_corrente in ("self_report", "t0", "t1", "t2"):
        _renderizza_scala_likert()


def _fase_precedente(fase: str, corrente: str) -> bool:
    ordine = ["non_iniziato", "consenso", "self_report", "t0", "profilazione",
              "chat_1", "chat_2", "chat_3", "t1", "t2", "completato"]
    try:
        return ordine.index(fase) < ordine.index(corrente)
    except ValueError:
        return False


def _render_timer(timestamp_inizio: float) -> None:
    if timestamp_inizio is None:
        return
    trascorsi_sec = int(time.time() - timestamp_inizio)
    trascorsi_min = trascorsi_sec // 60
    trascorsi_s = trascorsi_sec % 60
    nota = (
        f" — vicino al tempo consigliato ({DURATA_TARGET_MINUTI} min)"
        if trascorsi_min >= DURATA_TARGET_MINUTI else ""
    )
    messaggio = f"Tempo conversazione: {trascorsi_min:02d}:{trascorsi_s:02d}{nota}"
    if trascorsi_min >= DURATA_TARGET_MINUTI:
        st.warning(messaggio)
    else:
        st.info(messaggio)


def _fase_icona(fase: str) -> str:
    return {
        "non_iniziato": "—",
        "consenso": "1",
        "self_report": "2",
        "t0": "3",
        "profilazione": "4",
        "chat_1": "5",
        "chat_2": "6",
        "chat_3": "7",
        "t1": "8",
        "t2": "9",
        "completato": "✓",
    }.get(fase, "❓")

def _titolo(testo: str, sottotitolo: str | None = None) -> None:
    st.title(testo)
    if sottotitolo:
        st.caption(sottotitolo)


def _istruzione(testo: str) -> None:
    st.info(testo)


def _render_item_likert(item, chiave_stato: str) -> Optional[int]:
    st.markdown(f"**{item.id}.** {item.testo}")
    valore = st.radio(
        label=item.testo,
        options=list(range(1, 8)),
        index=None,
        key=chiave_stato,
        horizontal=True,
        label_visibility="collapsed",
        format_func=lambda x: str(x),
    )
    return valore

def _render_item_sr(item) -> object:  # [PATCH]
    """
    Renderizza un item del self-report in Streamlit.
    Restituisce il valore selezionato (int, str, list) o None.
    """
    chiave = f"sr_{item.id}"

    if item.tipo == "numero":
        st.markdown(f"**{item.testo}**")
        valore = st.number_input(
            label=item.testo, min_value=18, max_value=99,
            step=1, key=chiave, label_visibility="collapsed",
            value=None,
        )
        return int(valore) if valore is not None else None

    elif item.tipo == "scelta":
        st.markdown(f"**{item.testo}**")
        valore = st.radio(
            label=item.testo, options=item.opzioni,
            index=None, key=chiave,
            label_visibility="collapsed",
            horizontal=len(item.opzioni) <= 4,
        )

        # Se l'utente seleziona "Altro", facciamo comparire il campo di testo per specificare
        if valore == "Altro":
            altro_valore = st.text_input(
                " ",
                key=f"{chiave}_altro",
                placeholder="Si prega di specificare qui...",
            )
            # Ritorna il testo inserito solo se compilato, altrimenti None per la validazione
            return altro_valore.strip() if altro_valore else None

        return valore

    elif item.tipo == "multi_scelta":
        st.markdown(f"**{item.testo}**")
        selezionati = []
        cols = st.columns(2)
        for idx, opzione in enumerate(item.opzioni):
            with cols[idx % 2]:
                if st.checkbox(opzione, key=f"{chiave}_{idx}"):
                    selezionati.append(opzione)
        return selezionati if selezionati else None

    else:
        # likert7 — scala accordo/disaccordo
        st.markdown(f"**{item.testo}**")
        col_min, col_slider, col_max = st.columns([2, 6, 2])
        with col_min:
            st.caption(SCALA_LIKERT_7[1])
        with col_slider:
            valore = st.radio(
                label=item.testo,
                options=list(range(1, 8)),
                index=None,
                key=chiave,
                horizontal=True,
                label_visibility="collapsed",
                format_func=lambda x: str(x),
            )
        with col_max:
            st.caption(SCALA_LIKERT_7[7])
        return valore


def pagina_selezione() -> None:
    st.title("Studio sperimentale sull'interazione uomo-macchina")
    st.info("La durata complessiva del test è di circa 15 minuti")
    st.markdown("Selezionare il proprio profilo per iniziare la sessione")

    with st.container(border=True):
        partecipanti = leggi_tutti_partecipanti()
        if not partecipanti:
            st.error("Nessun partecipante trovato nel sistema. Contatta il ricercatore.")
            return
        st.markdown("Cerca partecipante")
        ricerca = st.text_input(label=" ",placeholder="Digitare nome o cognome")

        if ricerca:
            partecipanti_filtrati = [
                p for p in partecipanti
                if ricerca.lower() in p.get("nome_visualizzato", "").lower()
            ]
        else:
            partecipanti_filtrati = partecipanti

        if ricerca:
            partecipanti_filtrati = [
                p for p in partecipanti
                if ricerca.lower() in p.get("nome_visualizzato", "").lower()
            ]
        else:
            partecipanti_filtrati = partecipanti

        if ricerca:
            st.caption(f"Trovati {len(partecipanti_filtrati)} partecipanti corrispondenti a '{ricerca}'")

        if not partecipanti_filtrati:
            st.info("Nessun partecipante corrisponde alla ricerca.")
            return
        st.markdown("\n")
        st.markdown("Lista partecipanti")
        st.markdown("\n")
        NUMERO_COLONNE = 5
        righe = [partecipanti_filtrati[i:i + NUMERO_COLONNE] for i in range(0, len(partecipanti_filtrati), NUMERO_COLONNE)]

        for riga in righe:
            colonne = st.columns(NUMERO_COLONNE)
            for col, p in zip(colonne, riga):
                with col:
                    fase = p.get("fase_corrente", "non_iniziato")
                    icona = _fase_icona(fase)
                    fase_testo = fase.replace("_", " ").capitalize()

                    with st.container(border=True):
                        st.markdown(f"**{icona} {p['nome_visualizzato']}**")
                        st.caption(f"Stato: {fase_testo}")

                        if st.button("Accesso", key=f"btn_{p['id']}", use_container_width=True):
                            st.session_state.partecipante_id = p["id"]
                            st.session_state.partecipante_dati = p
                            st.rerun()

def pagina_consenso() -> None:
    pid  = st.session_state.partecipante_id
    dati = st.session_state.partecipante_dati

    st.markdown(f"### Benvenut@ {dati['nome_visualizzato']}")
    st.markdown("---")
    st.markdown("#### Informativa sulla partecipazione")
    st.markdown("""
Il presente studio ha l'obiettivo di analizzare le dinamiche dell'interazione uomo-AI.

**In cosa consiste la partecipazione:**
- Compilazione di un breve questionario preliminare sulle opinioni relative ai domini di studio.
- Svolgimento di una conversazione iniziale di orientamento con un assistente virtuale.
- Completamento di tre sessioni di interazione guidata con assistenti AI.
- Compilazione di un questionario finale di valutazione dell'esperienza.
- Compilazione di un questionario di follow-up a distanza di 72 ore.


**I dati raccolti (risposte ai questionari e log testuali delle conversazioni) verranno registrati e analizzati in forma aggregata e anonima.**
    """)

    st.markdown("---")
    accetto = st.checkbox("Ho letto l'informativa e acconsento a partecipare.")

    if accetto:
        if st.button("Continua →", type="primary", use_container_width=True):
            segna_consenso_firmato(pid)
            aggiorna_fase(pid, "self_report")
            dati["fase_corrente"] = "self_report"
            dati["consenso_firmato"] = True
            st.session_state.partecipante_dati = dati
            st.rerun()

def pagina_self_report() -> None:
    pid = st.session_state.partecipante_id
    st.header("Fase -> Questionario personale")
    st.info("Prima di iniziare l'esperimento è necessario rispondere a qualche domanda personale.")
    _render_step_flusso("self_report")

    risposte_likert: dict[str, int] = {}
    risposte_demografiche: dict[str, object] = {}
    tutti_compilati = True

    _ISTRUZIONI_SEZIONE = {
        "P": None,  # nessuna istruzione aggiuntiva
        "Q": "Si indichi quanto si è d'accordo con ciascuna affermazione.",
        "R": "Si indichi quanto si è d'accordo con ciascuna affermazione.",
        "S": "Si indichi quanto si è d'accordo con ciascuna affermazione.",
    }

    for id_sezione, titolo_ui, items in SEZIONI_SR:
        with st.expander(titolo_ui, expanded=True):
            if _ISTRUZIONI_SEZIONE.get(id_sezione):
                st.info(_ISTRUZIONI_SEZIONE[id_sezione])

            # Dividiamo gli item della sezione in gruppi da 2 (per fare una griglia a 2 colonne)
            NUM_COLONNE = 3

            righe_item = [items[i:i + NUM_COLONNE] for i in range(0, len(items), NUM_COLONNE)]

            for gruppo in righe_item:
                colonne = st.columns(NUM_COLONNE)
                for col, item in zip(colonne, gruppo):
                    with col:
                        # Inseriamo ogni item all'interno di una card con bordo per una grafica pulita
                        with st.container(border=True):
                            valore = _render_item_sr(item)

                            # Validazione
                            if item.tipo == "multi_scelta":
                                if valore:
                                    risposte_demografiche[item.id] = valore
                            elif valore is None:
                                tutti_compilati = False
                            elif item.tipo in ("numero", "scelta"):
                                risposte_demografiche[item.id] = valore
                            else:
                                risposte_likert[item.id] = int(valore)

    st.markdown("---")

    if not tutti_compilati:
        st.warning("Compila tutte le domande obbligatorie per continuare.")

    if st.button(
            "Avanti →",
            type="primary",
            use_container_width=True,
            disabled=not tutti_compilati,
    ):
        # 1. Salva le risposte nel DB
        record = serializza_per_db_sr(
            partecipante_id=pid,
            risposte_likert=risposte_likert,
            risposte_demografiche=risposte_demografiche,
            fase="self_report",
        )
        salva_risposte_questionario(pid, "self_report", record)

        # 2. Compila il profilo JSON parziale e salvalo su disco
        _SCHEMA_PATH = Path(__file__).resolve().parent / "Dati" / "schema_vuoto_user_profile.json"
        if _SCHEMA_PATH.exists():
            with open(_SCHEMA_PATH, encoding="utf-8") as f:
                schema_vuoto = json.load(f)

            profilo_sr = compila_campi_profilo(
                risposte_likert=risposte_likert,
                risposte_demografiche=risposte_demografiche,
                schema_vuoto=schema_vuoto,
            )
            profilo_sr["subject_id"] = pid
            profilo_sr["source_type"] = "self_report"
            profilo_sr["condition"] = "self_report"

            _DIR_PROFILI = Path(__file__).resolve().parent / "Dati" / "profili_json_completi"
            _DIR_PROFILI.mkdir(parents=True, exist_ok=True)
            with open(_DIR_PROFILI / f"PERSONA_{pid}.json", "w", encoding="utf-8") as f:
                json.dump(profilo_sr, f, ensure_ascii=False, indent=2)

        # 3. Avanza alla fase T0
        aggiorna_fase(pid, "t0")
        dati = st.session_state.partecipante_dati
        dati["fase_corrente"] = "t0"
        st.session_state.partecipante_dati = dati
        st.rerun()

def pagina_t0() -> None:
    pid = st.session_state.partecipante_id

    _titolo("Questionario iniziale")
    _render_step_flusso("t0")
    _istruzione(
        "Le seguenti domande riguardano le proprie opinioni su diversi argomenti."
    )

    risposte_likert:       dict[str, int] = {}
    risposte_demografiche: dict[str, str] = {}
    tutti_compilati = True
    with st.container(border=True):
        st.subheader("Opinioni e orientamenti")

        dominio_config = {
            "commerciale": (
                "Parte A: Commercio e acquisti",
                "Si considerino le sue consuete abitudini di acquisto.",
            ),
            "sanitario": (
                "Parte B: Salute e prevenzione",
                "Si consideri il suo approccio personale alla salute e al benessere.",
            ),
            "politico": (
                "Parte C: Politica e società",
                "Si considerino i suoi pensieri su questioni politiche, economiche e sociali.",
            ),
        }

        NUM_COLONNE = 2

        for dominio, (titolo, sottotitolo) in dominio_config.items():
            st.markdown(f"{titolo}")
            st.caption(sottotitolo)

            items_dominio = [it for it in SEZIONE_A if it.dominio == dominio]
            righe_item = [items_dominio[i:i + NUM_COLONNE] for i in range(0, len(items_dominio), NUM_COLONNE)]

            for gruppo in righe_item:
                colonne = st.columns(NUM_COLONNE)
                for col, item in zip(colonne, gruppo):
                    with col:
                        with st.container(border=True):
                            valore = _render_item_likert(item, f"t0_{item.id}")
                            if valore is None:
                                tutti_compilati = False
                            else:
                                risposte_likert[item.id] = valore

    st.markdown("---")
    with st.container(border=True):
        st.subheader("Abitudini di pensiero e riflessione")
        st.caption("Si indichi il grado di accordo in merito al proprio approccio ai compiti mentali.")

        items_d = list(SEZIONE_D)
        righe_d = [items_d[i:i + NUM_COLONNE] for i in range(0, len(items_d), NUM_COLONNE)]

        for gruppo in righe_d:
            colonne = st.columns(NUM_COLONNE)
            for col, item in zip(colonne, gruppo):
                with col:
                    with st.container(border=True):
                        valore = _render_item_likert(item, f"t0_{item.id}")
                        if valore is None:
                            tutti_compilati = False
                        else:
                            risposte_likert[item.id] = valore

    st.markdown("---")
    with st.container(border=True):
        st.subheader("Esperienza con i sistemi di IA")

        items_e = list(SEZIONE_E)
        righe_e = [items_e[i:i + NUM_COLONNE] for i in range(0, len(items_e), NUM_COLONNE)]

        for gruppo in righe_e:
            colonne = st.columns(NUM_COLONNE)
            for col, item in zip(colonne, gruppo):
                with col:
                    with st.container(border=True):
                        st.markdown(f"**{item.testo}**")

                        if item.tipo == "scelta":
                            val = st.radio(
                                item.testo,
                                options=item.opzioni,
                                index=None,
                                key=f"t0_{item.id}",
                                label_visibility="collapsed",
                                horizontal=False
                            )

                            if val is None:
                                tutti_compilati = False
                            elif val == "Altro":
                                altro_val = st.text_input(
                                    "Specificare:",
                                    key=f"t0_{item.id}_altro",
                                    placeholder="Indicare qui...",
                                )
                                if altro_val:
                                    risposte_demografiche[item.id] = altro_val.strip()
                                else:
                                    tutti_compilati = False
                            else:
                                risposte_demografiche[item.id] = val

    st.markdown("---")
    if not tutti_compilati:
        st.warning("Compila tutte le domande per continuare.")

    if st.button(
        "Invia le risposte e continua →",
        type="primary",
        use_container_width=True,
        disabled=not tutti_compilati,
    ):
        record = serializza_per_db(
            partecipante_id=pid,
            risposte_likert=risposte_likert,
            risposte_demografiche=risposte_demografiche,
            fase="t0",
        )
        salva_risposte_questionario(pid, "t0", record)
        segna_t0_completato(pid)
        aggiorna_fase(pid, "profilazione")
        dati = st.session_state.partecipante_dati
        dati["fase_corrente"] = "profilazione"
        st.session_state.partecipante_dati = dati
        st.success("Risposte salvate.")
        st.rerun()

def pagina_profilazione() -> None:
    pid = st.session_state.partecipante_id

    _titolo("Conversazione con l’assistente")
    _render_step_flusso("profilazione")
    _istruzione(
        "Stai per iniziare una breve conversazione con un assistente AI. "
        "Rispondi liberamente e in modo naturale. "
        "Non esistono risposte giuste o sbagliate."
    )

    if st.session_state.sessione_profilazione is None:
        nfc_score, frequenza_ai = _recupera_parametri_t0(pid)
        sessione = SessioneProfilazione(
            partecipante_id=pid,
            nfc_score=nfc_score,
            frequenza_ai=frequenza_ai,
        )
        with st.spinner("Connessione all'assistente..."):
            sessione.inizia()
        st.session_state.sessione_profilazione = sessione
        st.rerun()

    sessione: SessioneProfilazione = st.session_state.sessione_profilazione

    with st.container():
        _render_messaggi(sessione.messaggi_visibili)

    turni = sessione.turni_utente
    rimanenti = max(0, TURNI_MINIMI_PROFILAZIONE - turni)

    if not sessione.completabile:
        st.info(f"Invia almeno altri **{rimanenti}** messaggio/i per continuare.")

    with st.form("form_chat_profilazione", clear_on_submit=True):
        testo = st.text_input(
            "Il tuo messaggio",
            placeholder="Scrivi qui la tua risposta...",
            label_visibility="collapsed",
        )
        col_inv, col_fin = st.columns([3, 1])
        with col_inv:
            invia = st.form_submit_button("Invia →", use_container_width=True, type="primary")
        with col_fin:
            concludi = st.form_submit_button(
                "Concludi ✓",
                use_container_width=True,
                disabled=not sessione.completabile,
            )

    if invia and testo.strip():
        with st.spinner(""):
            sessione.invia_messaggio(testo.strip())
        st.rerun()

    if concludi and sessione.completabile:
        sessione.chiudi()
        aggiorna_fase(pid, "chat_1")
        st.session_state.sessione_profilazione = None
        st.session_state.timestamp_inizio_chat = None
        dati = st.session_state.partecipante_dati
        dati["fase_corrente"] = "chat_1"
        st.session_state.partecipante_dati = dati
        st.rerun()

    st.caption(f"Messaggi inviati: {turni} / minimo {TURNI_MINIMI_PROFILAZIONE}")

def pagina_chat_sperimentale(fase: str) -> None:
    pid  = st.session_state.partecipante_id
    cfg  = CHAT_CONFIG[fase]
    chiave_sessione = f"sessione_{fase}"
    numero_chat = cfg["numero"]

    _titolo(cfg["etichetta"])
    _render_step_flusso(fase)
    _istruzione(
        "Stai per iniziare una conversazione con un assistente AI. "
        "Rispondi liberamente e in modo naturale. "
        f"Puoi concludere dopo almeno {TURNI_MINIMI_SPERIMENTALE} messaggi."
    )

    if st.session_state[chiave_sessione] is None:
        nfc_score, frequenza_ai  = _recupera_parametri_t0(pid)
        try:
            assegnamento = _recupera_assegnamento_chat(pid, numero_chat)
        except (FileNotFoundError, ValueError, KeyError) as exc:
            st.error(f"Configurazione degli assegnamenti incompleta: {exc}")
            st.info(
                "Controlla che config_assegnamenti.json si trovi nella stessa cartella "
                "di Manipolazione.py e che contenga l'ID esatto del partecipante."
            )
            st.stop()

        with st.spinner(f"Avvio conversazione {numero_chat}/3..."):
            sessione = SessioneChat(
                partecipante_id=pid,
                modalita=assegnamento["modalita"],
                dominio=assegnamento["dominio"],
                nfc_score=nfc_score,
                frequenza_ai=frequenza_ai,
                numero_chat=numero_chat,
                modello_override=assegnamento.get("llm"),
            )
            sessione.inizia()

        st.session_state[chiave_sessione]    = sessione
        st.session_state.timestamp_inizio_chat = time.time()
        st.rerun()

    sessione: SessioneChat = st.session_state[chiave_sessione]

    _render_timer(st.session_state.timestamp_inizio_chat)

    if sessione.chiusura_automatica:
        _gestisci_conclusione_chat(pid, fase, sessione, chiave_sessione, automatica=True)
        return

    with st.container():
        _render_messaggi(sessione.messaggi_visibili)

    turni = sessione.turni_utente
    rimanenti = max(0, TURNI_MINIMI_SPERIMENTALE - turni)

    if not sessione.completabile:
        st.info(f"Invia almeno altri **{rimanenti}** messaggio/i per poter concludere.")

    with st.form(f"form_chat_{fase}", clear_on_submit=True):
        testo = st.text_input(
            "Il tuo messaggio",
            placeholder="Scrivi qui la tua risposta...",
            label_visibility="collapsed",
        )
        col_inv, col_fin = st.columns([3, 1])
        with col_inv:
            invia = st.form_submit_button("Invia →", use_container_width=True, type="primary")
        with col_fin:
            concludi = st.form_submit_button(
                "Concludi ✓",
                use_container_width=True,
                disabled=not sessione.completabile,
            )

    if invia and testo.strip():
        with st.spinner(""):
            sessione.invia_messaggio(testo.strip())
        st.rerun()

    if concludi and sessione.completabile:
        _gestisci_conclusione_chat(pid, fase, sessione, chiave_sessione, automatica=False)
        return

    turni_rimasti_al_max = TURNI_MASSIMI_UTENTE - turni
    st.caption(
        f"Messaggi inviati: {turni} | minimo {TURNI_MINIMI_SPERIMENTALE} | "
        f"massimo {TURNI_MASSIMI_UTENTE} (ancora {turni_rimasti_al_max})"
    )

def pagina_t1() -> None:
    pid = st.session_state.partecipante_id

    _titolo("Questionario finale")
    _render_step_flusso("t1")
    _istruzione(
        "Hai completato le tre conversazioni. "
        "Ti chiediamo ora di rispondere ad alcune domande sulle tue opinioni attuali "
        "e sull'esperienza che hai appena vissuto. "
        "Non ci sono risposte giuste o sbagliate."
    )

    with st.expander(" Scala di risposta", expanded=False):
        col_scala = st.columns(7)
        for i, (val, etich) in enumerate(SCALA_LIKERT.items()):
            col_scala[i].markdown(f"**{val}**  \n{etich}")

    risposte_likert: dict[str, int] = {}
    tutti_compilati = True

    for id_sezione, titolo_ui, items in SEZIONI_T1:
        st.subheader(titolo_ui)

        # Contestualizzazione per sezione A ripetuta
        if id_sezione == "A":
            st.caption(
                "Le stesse domande che hai risposto all'inizio. "
                "Rispondi di nuovo in base alla tua opinione attuale."
            )

        for item in items:
            valore = _render_item_likert(item, f"t1_{item.id}")
            if valore is None:
                tutti_compilati = False
            else:
                risposte_likert[item.id] = valore
            st.markdown("")

    st.markdown("---")
    if not tutti_compilati:
        st.warning("Compila tutte le domande per continuare.")

    if st.button(
        "Invia le risposte e concludi →",
        type="primary",
        use_container_width=True,
        disabled=not tutti_compilati,
    ):
        record = serializza_per_db_t1(
            partecipante_id=pid,
            risposte_likert=risposte_likert,
            fase="t1",
        )
        salva_risposte_questionario(pid, "t1", record)
        aggiorna_fase(pid, "t2")
        dati = st.session_state.partecipante_dati
        dati["fase_corrente"] = "t2"
        st.session_state.partecipante_dati = dati
        st.success("Risposte T1 salvate.")
        st.rerun()

def pagina_t2() -> None:
    pid = st.session_state.partecipante_id

    _titolo("Questionario di follow-up")
    _render_step_flusso("t2")

    _istruzione(
        "Rispondi alle seguenti domande in base alla tua opinione attuale e alla "
        "tua esperienza. Non ci sono risposte giuste o sbagliate."
    )

    with st.expander("Scala di risposta", expanded=False):
        colscala = st.columns(7)
        for i, (val, etich) in enumerate(SCALA_LIKERT.items()):
            colscala[i].markdown(f"**{val}**  \n{etich}")

    risposte_likert: dict[str, int] = {}
    tutti_compilati = True

    for id_sezione, titolo_ui, items in SEZIONI_T1:
        st.subheader(titolo_ui)

        if id_sezione == "A":
            st.caption(
                "Le stesse domande che hai già risposto. "
                "Rispondi in base alla tua opinione attuale."
            )

        for item in items:
            valore = _render_item_likert(item, f"t2_{item.id}")

            if valore is None:
                tutti_compilati = False
            else:
                risposte_likert[item.id] = valore

        st.markdown("")

    st.markdown("---")

    if not tutti_compilati:
        st.warning("Compila tutte le domande per continuare.")

    if st.button(
        "Invia le risposte e concludi",
        type="primary",
        use_container_width=True,
        disabled=not tutti_compilati,
    ):
        record = serializza_per_db_t1(
            partecipante_id=pid,
            risposte_likert=risposte_likert,
            fase="t2",
        )

        salva_risposte_questionario(pid, "t2", record)

        dati = st.session_state.partecipante_dati
        dati["fase_corrente"] = "completato"
        st.session_state.partecipante_dati = dati

        aggiorna_fase(pid, "completato")

        st.success("Risposte T2 salvate.")
        st.rerun()

def pagina_completato() -> None:
    _titolo("Studio completato")
    st.success("Hai completato tutte le fasi dello studio. Grazie per la tua partecipazione!")
    st.info("Puoi chiudere questa pagina. Il ricercatore ti contatterà per il debriefing.")

def _gestisci_conclusione_chat(pid: str, fase: str, sessione: SessioneChat, chiave_sessione: str, automatica: bool) -> None:
    sessione.chiudi()

    fase_prossima = FASE_DOPO_CHAT[fase]
    aggiorna_fase(pid, fase_prossima)
    st.session_state[chiave_sessione]      = None
    st.session_state.timestamp_inizio_chat = None

    dati = st.session_state.partecipante_dati
    dati["fase_corrente"] = fase_prossima
    st.session_state.partecipante_dati = dati

    if automatica:
        st.success("Conversazione completata.")
        st.write("Clicca il pulsante qui sotto per continuare.")
        if st.button("Continua →", type="primary", use_container_width=True):
            st.rerun()
    else:
        st.rerun()

def pagina_in_sviluppo(fase: str) -> None:
    st.subheader(f"Fase: {fase.replace('_', ' ').upper()}")
    st.info("Questa sezione è in fase di sviluppo. Il ricercatore ti contatterà per le istruzioni successive.")
    st.markdown("---")
    if st.button("← Torna alla selezione", use_container_width=True):
        st.session_state.partecipante_id   = None
        st.session_state.partecipante_dati = None
        st.rerun()

def main() -> None:
    _init_sessione()

    if st.session_state.partecipante_id is None:
        pagina_selezione()
        return

    dati = leggi_partecipante(st.session_state.partecipante_id)
    if dati is None:
        st.error("Partecipante non trovato. Torna alla selezione.")
        if st.button("← Torna"):
            st.session_state.partecipante_id   = None
            st.session_state.partecipante_dati = None
            st.rerun()
        return
    st.session_state.partecipante_dati = dati

    fase = dati.get("fase_corrente", "non_iniziato")

    col_sp, col_btn = st.columns([5, 1])
    with col_btn:
        if st.button("← Esci", help="Torna alla selezione partecipante"):
            st.session_state.partecipante_id   = None
            st.session_state.partecipante_dati = None
            st.rerun()

    if fase in ("non_iniziato",) or not dati.get("consenso_firmato"):
        pagina_consenso()

    elif fase == "self_report":
        pagina_self_report()

    elif fase == "t0":
        pagina_t0()

    elif fase == "profilazione":
        pagina_profilazione()

    elif fase == "chat_1":
        pagina_chat_sperimentale("chat_1")

    elif fase == "chat_2":
        pagina_chat_sperimentale("chat_2")

    elif fase == "chat_3":
        pagina_chat_sperimentale("chat_3")

    elif fase == "t1":
        pagina_t1()
    elif fase == "t2":
        pagina_t2()
    elif fase == "completato":
        pagina_completato()

    else:
        pagina_in_sviluppo(fase)


if __name__ == "__main__":
    main()