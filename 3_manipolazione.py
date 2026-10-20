from __future__ import annotations

import time
from typing import Optional

import streamlit as st

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
    "chat_2": {"modalita": "velato",    "numero": 2, "etichetta": "Chat 2 — Assistente B"},
    "chat_3": {"modalita": "diretto",   "numero": 3, "etichetta": "Chat 3 — Assistente C"},
}

FASE_DOPO_CHAT: dict[str, str] = {
    "chat_1": "chat_2",
    "chat_2": "chat_3",
    "chat_3": "t1",
}

st.set_page_config(
    page_title="Studio AI — Area Partecipante",
    page_icon="",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
section[Dati-testid="stSidebar"] { display: none !important; }

.titolo-studio {
    font-size: 1.4rem; font-weight: 600; color: #1a1a2e;
    margin-bottom: 4px;
}
.sottotitolo { color: #6b7280; font-size: 0.9rem; margin-bottom: 24px; }
.sezione-header {
    font-size: 0.75rem; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: #6b7280;
    border-bottom: 1px solid #e5e7eb; padding-bottom: 6px;
    margin: 28px 0 16px 0;
}
.istruzione {
    background: #f0f9ff; border: 1px solid #bae6fd;
    border-radius: 8px; padding: 14px 18px;
    font-size: 0.88rem; color: #0c4a6e; margin-bottom: 20px;
}
.card-utente {
    background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 10px;
    padding: 16px 20px; margin-bottom: 10px; cursor: pointer;
    transition: border-color 0.2s;
}

/* Badge di fase */
.fase-badge {
    display: inline-block; font-size: 0.7rem; font-weight: 500;
    padding: 2px 8px; border-radius: 12px; margin-left: 8px;
}
.badge-completato { background: #dcfce7; color: #166534; }
.badge-in_corso   { background: #fef3c7; color: #92400e; }
.badge-attesa     { background: #ede9fe; color: #4c1d95; }

/* Chat bolle */
.chat-bolla-ai {
    background: #f3f4f6; border-radius: 12px 12px 12px 2px;
    padding: 12px 16px; margin: 6px 0; max-width: 85%;
    font-size: 0.92rem; line-height: 1.5; color: #111827;
}
.chat-bolla-utente {
    background: #1d4ed8; color: white;
    border-radius: 12px 12px 2px 12px;
    padding: 12px 16px; margin: 6px 0 6px auto; max-width: 85%;
    font-size: 0.92rem; line-height: 1.5;
    text-align: right;
}
.chat-wrapper-ai     { display: flex; justify-content: flex-start; }
.chat-wrapper-utente { display: flex; justify-content: flex-end; }

/* Indicatori chat */
.progresso-box {
    background: #fffbeb; border: 1px solid #fcd34d;
    border-radius: 8px; padding: 10px 14px;
    font-size: 0.82rem; color: #92400e; margin-bottom: 12px;
}
.turni-counter {
    font-size: 0.75rem; color: #6b7280; text-align: center;
    margin-top: 6px;
}
.timer-box {
    background: #f0fdf4; border: 1px solid #86efac;
    border-radius: 8px; padding: 8px 14px;
    font-size: 0.82rem; color: #166534; margin-bottom: 12px;
    text-align: center;
}
.timer-attenzione {
    background: #fff7ed; border: 1px solid #fdba74;
    color: #9a3412;
}

/* Step indicator flusso */
.step-flusso {
    display: flex; gap: 6px; align-items: center;
    font-size: 0.78rem; color: #6b7280; margin-bottom: 20px;
    flex-wrap: wrap;
}
.step-attivo  { font-weight: 600; color: #1d4ed8; }
.step-fatto   { color: #16a34a; }
.step-sep     { color: #d1d5db; }

/* Blocco completamento chat */
.chat-completata-box {
    background: #f0fdf4; border: 2px solid #86efac;
    border-radius: 12px; padding: 30px; text-align: center;
    color: #166534; font-size: 0.95rem; margin-top: 20px;
}
</style>
""", unsafe_allow_html=True)


def _init_sessione() -> None:
    defaults = {
        "partecipante_id": None,
        "partecipante_dati": None,
        "sessione_profilazione": None,
        "sessione_chat_1": None,
        "sessione_chat_2": None,
        "sessione_chat_3":  None,
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


def _recupera_assegnamento_chat(partecipante_id: str, numero_chat: int) -> dict:
    pid = partecipante_id.upper()
    if "PERSONA_1" in pid or "U1" in pid:
        chiave = "U1"
    elif "PERSONA_2" in pid or "U2" in pid:
        chiave = "U2"
    elif "PERSONA_3" in pid or "U3" in pid:
        chiave = "U3"
    elif "PERSONA_4" in pid or "U4" in pid:
        chiave = "U4"
    elif "PERSONA_5" in pid or "U5" in pid:
        chiave = "U5"
    elif "PERSONA_6" in pid or "U6" in pid:
        chiave = "U6"
    else:
        chiave = pid

    ASSEGNAMENTI_STATICI = {
        "U1": [
            {"modalita": "controllo", "dominio": "commerciale", "llm": "openai/gpt-4o"},
            {"modalita": "velato", "dominio": "sanitario", "llm": "google/gemini-2.5-flash"},
            {"modalita": "diretto", "dominio": "politico", "llm": "anthropic/claude-haiku-4.5"},
        ],
        "U2": [
            {"modalita": "controllo", "dominio": "sanitario", "llm": "anthropic/claude-haiku-4.5"},
            {"modalita": "velato", "dominio": "politico", "llm": "openai/gpt-4o"},
            {"modalita": "diretto", "dominio": "commerciale", "llm": "google/gemini-2.5-flash"},
        ],
        "U3": [
            {"modalita": "controllo", "dominio": "politico", "llm": "google/gemini-2.5-flash"},
            {"modalita": "velato", "dominio": "commerciale", "llm": "anthropic/claude-haiku-4.5"},
            {"modalita": "diretto", "dominio": "sanitario", "llm": "openai/gpt-4o"},
        ],
        "U4": [
            {"modalita": "controllo", "dominio": "commerciale", "llm": "deepseek/deepseek-chat"},
            {"modalita": "velato", "dominio": "sanitario", "llm": "qwen/qwen-2.5-72b-instruct"},
            {"modalita": "diretto", "dominio": "politico", "llm": "meta-llama/llama-3.3-70b-instruct"},
        ],
        "U5": [
            {"modalita": "controllo", "dominio": "sanitario", "llm": "meta-llama/llama-3.3-70b-instruct"},
            {"modalita": "velato", "dominio": "politico", "llm": "deepseek/deepseek-chat"},
            {"modalita": "diretto", "dominio": "commerciale", "llm": "qwen/qwen-2.5-72b-instruct"},
        ],
        "U6": [
            {"modalita": "controllo", "dominio": "politico", "llm": "qwen/qwen-2.5-72b-instruct"},
            {"modalita": "velato", "dominio": "commerciale", "llm": "meta-llama/llama-3.3-70b-instruct"},
            {"modalita": "diretto", "dominio": "sanitario", "llm": "deepseek/deepseek-chat"},
        ],
    }

    lista = ASSEGNAMENTI_STATICI.get(chiave)
    if not lista:
        raise KeyError(f"Impossibile trovare l'assegnamento per il partecipante {partecipante_id} (mappato come {chiave})")

    return lista[numero_chat - 1]
def _render_messaggi(messaggi: list[dict]) -> None:
    for msg in messaggi:
        ruolo = msg.get("ruolo", "")
        contenuto = msg.get("contenuto", "")
        if ruolo == "assistente":
            st.markdown(
                f'<div class="chat-wrapper-ai">'
                f'<div class="chat-bolla-ai"> {contenuto}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        elif ruolo == "utente":
            st.markdown(
                f'<div class="chat-wrapper-utente">'
                f'<div class="chat-bolla-utente">{contenuto}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def _render_step_flusso(fase_corrente: str) -> None:
    fasi_ordinate = [
        ("t0", "Questionario"),
        ("profilazione","Conversazione iniziale"),
        ("chat_1", "Conversazione 1"),
        ("chat_2", "Conversazione 2"),
        ("chat_3", "Conversazione 3"),
        ("t1", "Questionario finale"),
    ]

    parti = []
    for fase, etichetta in fasi_ordinate:
        if fase == fase_corrente:
            parti.append(f'<span class="step-attivo">▶ {etichetta}</span>')
        elif _fase_precedente(fase, fase_corrente):
            parti.append(f'<span class="step-fatto">✓ {etichetta}</span>')
        else:
            parti.append(f'<span>{etichetta}</span>')
        parti.append('<span class="step-sep">›</span>')

    html = '<div class="step-flusso">' + "".join(parti[:-1]) + '</div>'
    st.markdown(html, unsafe_allow_html=True)


def _fase_precedente(fase: str, corrente: str) -> bool:
    ordine = ["non_iniziato", "consenso", "t0", "profilazione",
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

    css_extra = "timer-attenzione" if trascorsi_min >= DURATA_TARGET_MINUTI else ""
    nota = (
        f" — vicino al tempo consigliato ({DURATA_TARGET_MINUTI} min)"
        if trascorsi_min >= DURATA_TARGET_MINUTI else ""
    )
    st.markdown(
        f'<div class="timer-box {css_extra}">'
        f'⏱ Tempo conversazione: {trascorsi_min:02d}:{trascorsi_s:02d}{nota}'
        f'</div>',
        unsafe_allow_html=True,
    )

def _fase_icona(fase: str) -> str:
    return {
        "non_iniziato": "⬜",
        "consenso":     "📋",
        "t0":           "📝",
        "profilazione": "💬",
        "chat_1":       "🔵",
        "chat_2":       "🟡",
        "chat_3":       "🔴",
        "t1":           "📊",
        "t2":           "✅",
        "completato":   "🏁",
    }.get(fase, "❓")

def pagina_selezione() -> None:
    st.markdown('<div class="titolo-studio"> Studio sull\'Intelligenza Artificiale</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="sottotitolo">Seleziona il tuo nome per accedere alla tua area personale.</div>',
                unsafe_allow_html=True)

    partecipanti = leggi_tutti_partecipanti()
    if not partecipanti:
        st.error("Nessun partecipante trovato nel sistema. Contatta il ricercatore.")
        return

    for p in partecipanti:
        fase  = p.get("fase_corrente", "non_iniziato")
        icona = _fase_icona(fase)
        col1, col2 = st.columns([4, 1])
        with col1:
            if st.button(
                f"{icona}  {p['nome_visualizzato']}",
                key=f"btn_{p['id']}",
                use_container_width=True,
            ):
                st.session_state.partecipante_id   = p["id"]
                st.session_state.partecipante_dati = p
                st.rerun()
        with col2:
            st.caption(fase.replace("_", " ").capitalize())

def pagina_consenso() -> None:
    pid  = st.session_state.partecipante_id
    dati = st.session_state.partecipante_dati

    st.markdown(f"### Benvenuto/a, {dati['nome_visualizzato']}")
    st.markdown("---")
    st.markdown("#### Informativa sulla partecipazione allo studio")
    st.markdown("""
Questo studio è condotto nell'ambito di una ricerca accademica
sull'interazione tra esseri umani e sistemi di intelligenza artificiale.

**Cosa comporta la partecipazione:**
- Compilare un breve questionario sulle tue opinioni (circa 10 minuti)
- Partecipare a una conversazione iniziale con un assistente AI (circa 10 minuti)
- Partecipare a tre conversazioni con assistenti AI (circa 10 minuti ciascuna)
- Compilare un questionario al termine delle conversazioni (circa 10 minuti)
- Compilare un questionario di follow-up dopo 72 ore (circa 5 minuti)

**Dati raccolti:**
Le tue risposte e le conversazioni verranno registrate e analizzate
in forma anonimizzata. I tuoi dati non verranno condivisi con terze parti
e saranno utilizzati esclusivamente per finalità di ricerca scientifica.

**Diritto di recesso:**
Puoi interrompere la partecipazione in qualsiasi momento senza conseguenze.

**Contatto:**
Per domande, contatta il ricercatore responsabile dello studio.
    """)

    st.markdown("---")
    accetto = st.checkbox("Ho letto l'informativa e acconsento a partecipare allo studio.")

    if accetto:
        if st.button("Continua →", type="primary", use_container_width=True):
            segna_consenso_firmato(pid)
            aggiorna_fase(pid, "t0")
            dati["fase_corrente"]    = "t0"
            dati["consenso_firmato"] = True
            st.session_state.partecipante_dati = dati
            st.rerun()

def _render_item_likert(item, chiave_stato: str) -> Optional[int]:
    st.markdown(f"**{item.id}.** {item.testo}")
    opzioni_display = ["— seleziona —"] + [
        f"{v} — {SCALA_LIKERT[v]}" for v in range(1, 8)
    ]
    scelta = st.selectbox(
        label=item.testo,
        options=opzioni_display,
        key=chiave_stato,
        label_visibility="collapsed",
    )
    if scelta == "— seleziona —":
        return None
    return int(scelta[0])


def pagina_t0() -> None:
    pid = st.session_state.partecipante_id

    st.markdown('<div class="titolo-studio"> Questionario Iniziale</div>', unsafe_allow_html=True)
    _render_step_flusso("t0")
    st.markdown(
        '<div class="istruzione">'
        'Le seguenti domande riguardano le tue opinioni su diversi argomenti. '
        'Non ci sono risposte giuste o sbagliate. '
        'Rispondi in modo sincero basandoti sulla tua opinione attuale.'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.expander("📏 Scala di risposta", expanded=False):
        col_scala = st.columns(7)
        for i, (val, etich) in enumerate(SCALA_LIKERT.items()):
            col_scala[i].markdown(f"**{val}**  \n{etich}")

    risposte_likert:       dict[str, int] = {}
    risposte_demografiche: dict[str, str] = {}
    tutti_compilati = True

    st.markdown('<div class="sezione-header">Sezione A · B · C — Le tue opinioni</div>',
                unsafe_allow_html=True)
    for dominio, (titolo, sottotitolo) in {
        "commerciale": ("Parte A: Commercio e acquisti",
                        "Pensa alle tue abitudini di acquisto."),
        "sanitario": ("Parte B: Salute e prevenzione",
                        "Pensa al tuo approccio alla salute."),
        "politico": ("Parte C: Politica e tassazione",
                        "Pensa alle questioni politiche ed economiche."),
    }.items():
        st.markdown(f"**{titolo}**")
        st.caption(sottotitolo)
        for item in [it for it in SEZIONE_A if it.dominio == dominio]:
            valore = _render_item_likert(item, f"t0_{item.id}")
            if valore is None:
                tutti_compilati = False
            else:
                risposte_likert[item.id] = valore
            st.markdown("")

    st.markdown('<div class="sezione-header">Sezione D — Le tue abitudini di pensiero</div>',
                unsafe_allow_html=True)
    st.caption("Come ti approcci ai compiti mentali e alla riflessione.")
    for item in SEZIONE_D:
        valore = _render_item_likert(item, f"t0_{item.id}")
        if valore is None:
            tutti_compilati = False
        else:
            risposte_likert[item.id] = valore
        st.markdown("")

    st.markdown('<div class="sezione-header">Sezione E — Informazioni su di te</div>',
                unsafe_allow_html=True)
    for item in SEZIONE_E:
        if item.tipo == "numero":
            val = st.number_input(item.testo, min_value=18, max_value=99,
                                  step=1, key=f"t0_{item.id}", value=None)
            if val is None:
                tutti_compilati = False
            else:
                risposte_demografiche[item.id] = str(int(val))
        elif item.tipo == "scelta":
            opz = ["— seleziona —"] + item.opzioni
            val = st.selectbox(item.testo, opz, key=f"t0_{item.id}")
            if val == "— seleziona —":
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

    st.markdown('<div class="titolo-studio"> Conversazione con l\'assistente</div>',
                unsafe_allow_html=True)
    _render_step_flusso("profilazione")
    st.markdown(
        '<div class="istruzione">'
        'Stai per iniziare una breve conversazione con un assistente AI. '
        'Rispondi liberamente e in modo naturale. '
        'Non esistono risposte giuste o sbagliate.'
        '</div>',
        unsafe_allow_html=True,
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
        st.markdown(
            f'<div class="progresso-box">'
            f'⏱ Invia almeno altri <strong>{rimanenti}</strong> messaggio/i per continuare.'
            f'</div>',
            unsafe_allow_html=True,
        )

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

    st.markdown(
        f'<div class="turni-counter">'
        f'Messaggi inviati: {turni} / minimo {TURNI_MINIMI_PROFILAZIONE}'
        f'</div>',
        unsafe_allow_html=True,
    )

def pagina_chat_sperimentale(fase: str) -> None:
    pid  = st.session_state.partecipante_id
    cfg  = CHAT_CONFIG[fase]
    chiave_sessione = f"sessione_{fase}"
    numero_chat = cfg["numero"]

    st.markdown(
        f'<div class="titolo-studio"> {cfg["etichetta"]}</div>',
        unsafe_allow_html=True,
    )
    _render_step_flusso(fase)
    st.markdown(
        '<div class="istruzione">'
        'Stai per iniziare una conversazione con un assistente AI. '
        'Rispondi liberamente e in modo naturale. '
        f'Puoi concludere dopo almeno {TURNI_MINIMI_SPERIMENTALE} messaggi.'
        '</div>',
        unsafe_allow_html=True,
    )

    if st.session_state[chiave_sessione] is None:
        nfc_score, frequenza_ai  = _recupera_parametri_t0(pid)
        assegnamento = _recupera_assegnamento_chat(pid, numero_chat)

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
        st.markdown(
            f'<div class="progresso-box">'
            f'⏱ Invia almeno altri <strong>{rimanenti}</strong> messaggio/i per poter concludere.'
            f'</div>',
            unsafe_allow_html=True,
        )

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
    st.markdown(
        f'<div class="turni-counter">'
        f'Messaggi inviati: {turni} | minimo {TURNI_MINIMI_SPERIMENTALE} | '
        f'massimo {TURNI_MASSIMI_UTENTE} (ancora {turni_rimasti_al_max})'
        f'</div>',
        unsafe_allow_html=True,
    )


def _gestisci_conclusione_chat(
    pid: str,
    fase: str,
    sessione: SessioneChat,
    chiave_sessione: str,
    automatica: bool,
) -> None:
    sessione.chiudi()

    fase_prossima = FASE_DOPO_CHAT[fase]
    aggiorna_fase(pid, fase_prossima)
    st.session_state[chiave_sessione]      = None
    st.session_state.timestamp_inizio_chat = None

    dati = st.session_state.partecipante_dati
    dati["fase_corrente"] = fase_prossima
    st.session_state.partecipante_dati = dati

    if automatica:
        st.markdown(
            '<div class="chat-completata-box">'
            ' Conversazione completata.<br><br>'
            'Clicca il pulsante qui sotto per continuare.'
            '</div>',
            unsafe_allow_html=True,
        )
        if st.button("Continua →", type="primary", use_container_width=True):
            st.rerun()
    else:
        st.rerun()


def pagina_t1() -> None:
    pid = st.session_state.partecipante_id

    st.markdown('<div class="titolo-studio"> Questionario Finale</div>', unsafe_allow_html=True)
    _render_step_flusso("t1")
    st.markdown(
        '<div class="istruzione">'
        'Hai completato le tre conversazioni. '
        'Ti chiediamo ora di rispondere ad alcune domande sulle tue opinioni attuali '
        'e sull\'esperienza che hai appena vissuto. '
        'Non ci sono risposte giuste o sbagliate.'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.expander(" Scala di risposta", expanded=False):
        col_scala = st.columns(7)
        for i, (val, etich) in enumerate(SCALA_LIKERT.items()):
            col_scala[i].markdown(f"**{val}**  \n{etich}")

    risposte_likert: dict[str, int] = {}
    tutti_compilati = True

    for id_sezione, titolo_ui, items in SEZIONI_T1:
        st.markdown(f'<div class="sezione-header">{titolo_ui}</div>', unsafe_allow_html=True)

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

    st.markdown(
        '<div class="titolo-studio">Questionario di Follow-up</div>',
        unsafe_allow_html=True,
    )
    _render_step_flusso("t2")

    st.markdown(
        """
        <div class="istruzione">
        Rispondi alle seguenti domande in base alla tua opinione attuale e alla
        tua esperienza. Non ci sono risposte giuste o sbagliate.
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Scala di risposta", expanded=False):
        colscala = st.columns(7)
        for i, (val, etich) in enumerate(SCALA_LIKERT.items()):
            colscala[i].markdown(f"**{val}**<br>{etich}", unsafe_allow_html=True)

    risposte_likert: dict[str, int] = {}
    tutti_compilati = True

    for id_sezione, titolo_ui, items in SEZIONI_T1:
        st.markdown(
            f'<div class="sezione-header">{titolo_ui}</div>',
            unsafe_allow_html=True,
        )

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

def pagina_in_sviluppo(fase: str) -> None:
    st.markdown(
        f'<div class="sviluppo-box">'
        f'<strong>Fase: {fase.replace("_", " ").upper()}</strong><br><br>'
        f'Questa sezione è in fase di sviluppo.<br>'
        f'Il ricercatore ti contatterà per le istruzioni successive.'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown("---")
    if st.button("← Torna alla selezione", use_container_width=True):
        st.session_state.partecipante_id   = None
        st.session_state.partecipante_dati = None
        st.rerun()


def pagina_completato() -> None:
    st.markdown('<div class="titolo-studio">🏁 Studio completato</div>', unsafe_allow_html=True)
    st.success("Hai completato tutte le fasi dello studio. Grazie per la tua partecipazione!")
    st.markdown(
        '<div class="istruzione">'
        'Puoi chiudere questa pagina. Il ricercatore ti contatterà per il debriefing.'
        '</div>',
        unsafe_allow_html=True,
    )

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