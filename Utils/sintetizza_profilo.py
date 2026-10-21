"""
sintetizza_profilo.py
=====================
Eseguito al termine della chat di profilazione di ogni partecipante.

Flusso:
  1. Legge dal DB: self-report, T0, trascrizione chat di profilazione
  2. Per ogni sezione usa il prompt few-shot specifico + schema JSON di sezione
      - non_sensitive_attributes  → estrazione_non_sensibili_few_shot.txt
      - private_attributes        → estrazione_privati_few_shot.txt
      - psychological_attributes  → estrazione_psicologici_few_shot.txt
      - sensitive_attributes      → estrazione_sensibili_appello_emotivo.txt
  3. Calcola manipulation_vulnerability_profile → estrazione_vulnerabilita_appello_emotivo.txt
     (riceve il profilo parziale già compilato, NON la trascrizione grezza)
  4. Assembla il JSON completo (schema_vuoto_user_profile.json come base)
  5. Salva in output/<partecipante_id>/
      - profilo_completo.json
      - non_sensitive_attributes.json
      - private_attributes.json
      - psychological_attributes.json
      - sensitive_attributes.json
      - manipulation_vulnerability_profile.json
  6. (Opzionale) Salva su Supabase → tabella `profili`

Integrazione nel flusso Streamlit (Manipolazione.py):
    from Utils.sintetizza_profilo import sintetizza_e_salva_profilo

    with st.spinner("Elaborazione profilo in corso..."):
        profilo = sintetizza_e_salva_profilo(
            partecipante_id=st.session_state["partecipante_id"],
            sessione_id=sessione_profilazione.sessione_id,
            salva_su_db=True,
        )

Uso standalone (da terminale):
    python sintetizza_profilo.py U1
    python sintetizza_profilo.py U1 U2 U3 --output-dir ./profili --no-db
    python sintetizza_profilo.py U1 --sessione-id 42 --no-db
"""

from __future__ import annotations

import concurrent.futures
import copy
import json
import re
import sys
from pathlib import Path
from typing import Optional

# ── path setup ────────────────────────────────────────────────────────────────
_RADICE = Path(__file__).resolve().parents[2]
if str(_RADICE) not in sys.path:
    sys.path.insert(0, str(_RADICE))

from clients import get_client
from Utils.database import (
    leggi_risposte_questionario,
    leggi_messaggi_sessione,
    leggi_sessioni_partecipante,
    ottieni_client as _db_client,
)
from Utils.prompts_profilazione import (
    sintetizza_sr_per_prompt,
    sintetizza_t0_per_prompt,
    VERSIONE_PROMPT,
)

# ── percorsi file ─────────────────────────────────────────────────────────────
# _DIR è la cartella dove si trova questo script (Utils/).
# _PROMPT_DIR e _SCHEMA_DIR puntano alle sottocartelle del progetto.
_DIR         = Path(__file__).resolve().parent          # …/Utils/
_PROGETTO    = _DIR.parent                              # …/SISTEMA DI MANIPOLAZIONE/
_PROMPT_DIR  = _PROGETTO / "Prompts"
_SCHEMA_DIR  = _PROGETTO / "Schemi"

# Mappa: (nome_sezione, file_prompt, file_schema, label_per_placeholder)
_SEZIONI: list[tuple[str, str, str, str]] = [
    (
        "non_sensitive_attributes",
        "estrazione_non_sensibili_few_shot.txt",
        "schema_non_sensitive.json",
        "non_sensitive_attributes",
    ),
    (
        "private_attributes",
        "estrazione_privati_few_shot.txt",
        "schema_private.json",
        "private_attributes",
    ),
    (
        "psychological_attributes",
        "estrazione_psicologici_few_shot.txt",
        "schema_psychological.json",
        "psychological_attributes",
    ),
    (
        "sensitive_attributes",
        # Prompt riscritto con framing neutro da ricercatore (funziona con tutti i modelli)
        "estrazione_sensibili_ricercatore.txt",
        "schema_sensitive.json",
        "sensitive_attributes",
    ),
]

_PROMPT_MVP   = "estrazione_vulnerabilita_ricercatore.txt"   # idem
_SCHEMA_MVP   = "schema_vulnerability.json"
_SCHEMA_VUOTO = "schema_vuoto_user_profile.json"

# ── timeout chiamate LLM (secondi) ───────────────────────────────────────────
# Gemini 2.5 Flash può bloccarsi silenziosamente sui contenuti sensibili
# (safety filter lato OpenRouter). Il timeout forza l'uscita e permette
# al codice di continuare con la sezione successiva invece di bloccarsi.
LLM_TIMEOUT_SEC = 120

# ── configurazione LLM ────────────────────────────────────────────────────────
CFG_SINTESI = {
    "provider":    "openrouter",
    "model":       "google/gemini-2.5-flash",
    "api_key_env": "OPENROUTER_API_KEY",
    "temperature": 0.1,
    "max_tokens":  4096,
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers I/O
# ─────────────────────────────────────────────────────────────────────────────

def _leggi_file(nome: str, cartella: Path) -> str:
    percorso = cartella / nome
    if not percorso.exists():
        raise FileNotFoundError(
            f"File non trovato: {percorso}\n"
            f"Assicurati che '{nome}' sia nella cartella '{cartella}'"
        )
    return percorso.read_text(encoding="utf-8")


def _leggi_schema(nome: str) -> dict:
    return json.loads(_leggi_file(nome, _SCHEMA_DIR))


def _carica_schema_vuoto() -> dict:
    return json.loads(_leggi_file(_SCHEMA_VUOTO, _SCHEMA_DIR))


def _parse_json_risposta(testo: str) -> Optional[dict]:
    """Estrae il primo JSON valido dalla risposta del modello."""
    testo = testo.strip()
    testo = re.sub(r"```(?:json)?\s*", "", testo).replace("```", "").strip()
    try:
        return json.loads(testo)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", testo, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def _formatta_trascrizione(messaggi: list[dict]) -> str:
    """
    Converte i messaggi della sessione in testo per il prompt.
    Usa doc_id='chat_profilazione' come atteso dagli esempi few-shot.
    """
    righe = []
    for i, m in enumerate(messaggi):
        ruolo = "UTENTE" if m.get("ruolo") == "utente" else "ASSISTENTE"
        testo = m.get("contenuto", "").strip()
        if testo:
            righe.append(f"[{ruolo} doc_id=chat_profilazione msg_id=msg_{i}]: {testo}")
    return "\n\n".join(righe) if righe else "(nessun messaggio disponibile)"


def _prepara_chat_text(
    trascrizione: str,
    riassunto_sr: str,
    riassunto_t0: str,
) -> str:
    """
    Costruisce il testo completo per {{chat_text}}:
    self-report e T0 come contesto dichiarato, poi trascrizione chat.
    I dati SR/T0 includono doc_id espliciti per le evidence.
    """
    parti = []

    if riassunto_sr and "(nessun" not in riassunto_sr:
        parti.append(
            "[SELF_REPORT doc_id=self_report]:\n" + riassunto_sr
        )
    if riassunto_t0 and "(nessun" not in riassunto_t0:
        parti.append(
            "[T0_QUESTIONARIO doc_id=t0]:\n" + riassunto_t0
        )
    if trascrizione and "(nessun" not in trascrizione:
        parti.append(trascrizione)

    return "\n\n---\n\n".join(parti) if parti else "(nessun dato disponibile)"


def _leggi_ultima_sessione_profilazione(partecipante_id: str) -> Optional[int]:
    sessioni = leggi_sessioni_partecipante(partecipante_id)
    for s in reversed(sessioni):
        if s.get("tipo") == "profilazione":
            return s["id"]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Chiamata LLM
# ─────────────────────────────────────────────────────────────────────────────

def _chiama_llm(client, sistema: str, utente: str, timeout: int = LLM_TIMEOUT_SEC) -> str:
    """
    Chiama il LLM con un timeout esplicito.

    Se la chiamata non risponde entro `timeout` secondi (tipicamente perché
    il modello è entrato nel ciclo di review dei safety filter di OpenRouter),
    solleva TimeoutError invece di bloccarsi indefinitamente.
    """
    messaggi = [
        {"role": "system", "content": sistema},
        {"role": "user",   "content": utente},
    ]

    def _call() -> str:
        if hasattr(client, "send_chat"):
            return client.send_chat(messaggi).text
        return client.send_prompt(f"{sistema}\n\n{utente}").text

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_call)
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(
                f"Timeout ({timeout}s) nella chiamata LLM — "
                "possibile blocco del safety filter (OpenRouter/Gemini). "
                "La sezione verrà saltata."
            )


# ─────────────────────────────────────────────────────────────────────────────
# Merging
# ─────────────────────────────────────────────────────────────────────────────

def _mergia_campo_foglia(base: dict, nuovo: dict) -> dict:
    """
    Mergia due campi foglia {'value':..., 'confidence':...}.
    Il nuovo vince se la sua confidence è >= a quella attuale
    oppure se la base è ancora vuota/null.
    """
    conf_base  = base.get("confidence") or 0.0
    conf_nuovo = nuovo.get("confidence") or 0.0
    val_base   = base.get("value")
    val_nuovo  = nuovo.get("value")

    base_vuota = val_base in (None, "", [], 0.0)
    nuovo_ha_val = val_nuovo not in (None, "", [], 0.0)

    if nuovo_ha_val and (base_vuota or conf_nuovo >= conf_base):
        return nuovo
    return base


def _mergia_sezione(base: dict, nuova: dict) -> dict:
    """Merge ricorsivo di due sezioni del profilo."""
    if not isinstance(nuova, dict):
        return base
    risultato = copy.deepcopy(base)
    for chiave, val_nuovo in nuova.items():
        val_base = risultato.get(chiave, {})
        if isinstance(val_nuovo, dict) and "confidence" in val_nuovo:
            # campo foglia
            risultato[chiave] = _mergia_campo_foglia(
                val_base if isinstance(val_base, dict) else {},
                val_nuovo,
            )
        elif isinstance(val_nuovo, dict) and isinstance(val_base, dict):
            # sottoalbero (es. big_five_personality)
            risultato[chiave] = _mergia_sezione(val_base, val_nuovo)
        elif val_nuovo is not None:
            risultato[chiave] = val_nuovo
    return risultato


# ─────────────────────────────────────────────────────────────────────────────
# Estrazione sezioni
# ─────────────────────────────────────────────────────────────────────────────

def _estrai_sezione(
    client,
    nome_sezione: str,
    nome_prompt: str,
    nome_schema: str,
    label_sezione: str,
    chat_text: str,
) -> dict:
    """
    Chiama il LLM con il prompt few-shot della sezione e restituisce
    il dizionario compilato per quella sezione.
    """
    template = _leggi_file(nome_prompt, _PROMPT_DIR)
    schema   = _leggi_schema(nome_schema)

    prompt_completo = (
        template
        .replace("{{section}}",   label_sezione)
        .replace("{{schema}}",    json.dumps(schema, ensure_ascii=False, indent=2))
        .replace("{{chat_text}}", chat_text)
    )

    # Separa system dal blocco utente sul delimitatore <<<CHAT>>>
    if "<<<CHAT>>>" in prompt_completo:
        parti   = prompt_completo.split("<<<CHAT>>>", 1)
        sistema = parti[0].strip()
        utente  = "<<<CHAT>>>" + parti[1]
    else:
        sistema = "Sei un annotatore sperimentale. Rispondi SOLO con JSON valido, senza Markdown."
        utente  = prompt_completo

    print(f"    [debug] prompt file: {_PROMPT_DIR / nome_prompt}")
    print(f"    [debug] schema file: {_SCHEMA_DIR / nome_schema}")
    print(f"    [debug] split su <<<CHAT>>>: {'sì' if '<<<CHAT>>>' in prompt_completo else 'NO — delimitatore assente!'}")

    try:
        print(f"    [debug] avvio chiamata LLM (timeout={LLM_TIMEOUT_SEC}s)...")
        risposta = _chiama_llm(client, sistema, utente)
        print(f"    [debug] risposta ricevuta ({len(risposta)} char)")
    except TimeoutError as e:
        print(f"    ✗ '{nome_sezione}': {e}")
        return {}
    except Exception as e:
        print(f"    ✗ '{nome_sezione}': errore chiamata LLM → {e}")
        import traceback; traceback.print_exc()
        return {}

    print(f"    [debug] risposta LLM (primi 200 char): {risposta[:200]!r}")  # noqa: E501

    risultato = _parse_json_risposta(risposta)

    if risultato is None:
        print(f"    ✗ '{nome_sezione}': risposta non JSON valido.")
        return {}

    print(f"    ✓ '{nome_sezione}': OK ({len(risultato)} campi estratti)")
    return risultato


def _estrai_mvp(client, profilo_parziale: dict) -> dict:
    """
    Calcola il manipulation_vulnerability_profile.
    Input: il profilo con le 4 sezioni già compilate (non la chat grezza).
    """
    template = _leggi_file(_PROMPT_MVP, _PROMPT_DIR)
    schema   = _leggi_schema(_SCHEMA_MVP)

    sezioni_input = {
        k: profilo_parziale.get(k, {})
        for k in [
            "non_sensitive_attributes",
            "private_attributes",
            "psychological_attributes",
            "sensitive_attributes",
        ]
    }
    testo_profilo = json.dumps(sezioni_input, ensure_ascii=False, indent=2)

    prompt_completo = (
        template
        .replace("{{schema}}",    json.dumps(schema, ensure_ascii=False, indent=2))
        .replace("{{chat_text}}", testo_profilo)
    )

    if "<<<PROFILO_ESTRATTO>>>" in prompt_completo:
        parti   = prompt_completo.split("<<<PROFILO_ESTRATTO>>>", 1)
        sistema = parti[0].strip()
        utente  = "<<<PROFILO_ESTRATTO>>>" + parti[1]
    else:
        sistema = "Sei un analista di vulnerabilità persuasiva. Rispondi SOLO con JSON valido."
        utente  = prompt_completo

    try:
        print(f"    [debug] avvio chiamata LLM MVP (timeout={LLM_TIMEOUT_SEC}s)...")
        risposta = _chiama_llm(client, sistema, utente)
        print(f"    [debug] risposta MVP ricevuta ({len(risposta)} char)")
    except TimeoutError as e:
        print(f"    ✗ MVP: {e}")
        return {}
    except Exception as e:
        print(f"    ✗ MVP: errore chiamata LLM → {e}")
        return {}

    risultato = _parse_json_risposta(risposta)

    if risultato is None:
        print(f"    ✗ MVP: risposta non JSON. Primi 300 char:")
        print(f"      {risposta[:300]!r}")
        return {}

    print(f"    ✓ MVP: OK ({len(risultato)} campi estratti)")
    return risultato


# ─────────────────────────────────────────────────────────────────────────────
# Output su disco
# ─────────────────────────────────────────────────────────────────────────────

def _salva_output(partecipante_id: str, profilo: dict, output_dir: Path) -> None:
    """
    Crea output_dir/<partecipante_id>/ e salva profilo_completo.json
    + un file JSON per ognuna delle 5 sezioni principali.
    """
    cartella = output_dir / partecipante_id
    cartella.mkdir(parents=True, exist_ok=True)

    (cartella / "profilo_completo.json").write_text(
        json.dumps(profilo, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for nome in [
        "non_sensitive_attributes",
        "private_attributes",
        "psychological_attributes",
        "sensitive_attributes",
        "manipulation_vulnerability_profile",
    ]:
        (cartella / f"{nome}.json").write_text(
            json.dumps(profilo.get(nome, {}), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"    ✓ Salvato in: {cartella.resolve()}")


def _salva_su_db(partecipante_id: str, profilo: dict) -> None:
    db = _db_client()
    db.table("profili").upsert(
        {
            "partecipante_id": partecipante_id,
            "profilo_json":    profilo,
            "nome_file_origine": f"sintesi_llm_{partecipante_id}.json",
        },
        on_conflict="partecipante_id",
    ).execute()
    print(f"    ✓ Salvato su Supabase")


# ─────────────────────────────────────────────────────────────────────────────
# API pubblica
# ─────────────────────────────────────────────────────────────────────────────

def sintetizza_e_salva_profilo(
    partecipante_id: str,
    sessione_id: Optional[int] = None,
    output_dir: Optional[Path] = None,
    salva_su_db: bool = True,
) -> dict:
    """
    Sintetizza il profilo completo di un partecipante.

    Parametri
    ----------
    partecipante_id : str
    sessione_id     : int | None  — ID sessione chat profilazione (auto-detect se None)
    output_dir      : Path | None — cartella output (default ./output)
    salva_su_db     : bool        — upsert su Supabase

    Ritorna il profilo JSON completo come dict.
    """
    if output_dir is None:
        output_dir = Path("output")

    print(f"\n{'─'*60}")
    print(f"  Sintesi profilo: {partecipante_id}")
    print(f"{'─'*60}")
    print(f"  Script in:    {Path(__file__).resolve()}")
    print(f"  Prompt dir:   {_PROMPT_DIR}  {'✓' if _PROMPT_DIR.exists() else '✗ NON TROVATA'}")
    print(f"  Schema dir:   {_SCHEMA_DIR}  {'✓' if _SCHEMA_DIR.exists() else '✗ NON TROVATA'}")
    print(f"  Output dir:   {output_dir.resolve()}")

    client = get_client(CFG_SINTESI)

    # 1. Carica dati
    print("1. Caricamento dati dal DB...")
    risposte_sr  = leggi_risposte_questionario(partecipante_id, "self_report")
    risposte_t0  = leggi_risposte_questionario(partecipante_id, "t0")
    riassunto_sr = sintetizza_sr_per_prompt(risposte_sr)
    riassunto_t0 = sintetizza_t0_per_prompt(risposte_t0)

    if sessione_id is None:
        sessione_id = _leggi_ultima_sessione_profilazione(partecipante_id)

    trascrizione = ""
    if sessione_id is not None:
        messaggi     = leggi_messaggi_sessione(sessione_id)
        trascrizione = _formatta_trascrizione(messaggi)
        print(f"   Chat: {len(messaggi)} messaggi (sessione {sessione_id})")
    else:
        print("   ⚠ Nessuna sessione di profilazione trovata.")

    chat_text = _prepara_chat_text(trascrizione, riassunto_sr, riassunto_t0)

    # 2. Schema base vuoto
    profilo = _carica_schema_vuoto()
    profilo["subject_id"]  = partecipante_id
    profilo["model"]       = CFG_SINTESI["model"]
    profilo["source_type"] = "llm_synthesis"
    profilo["condition"]   = "profiling_velato"
    profilo["meta"].update({
        "extraction_model_used":    CFG_SINTESI["model"],
        "extraction_prompt_version": VERSIONE_PROMPT,
        "llm_chat_available":        bool(trascrizione),
    })

    # 3. Estrazione sezione per sezione
    print("2. Estrazione sezioni...")
    for nome_sezione, nome_prompt, nome_schema, label in _SEZIONI:
        print(f"   → {nome_sezione}")
        estratto = _estrai_sezione(
            client=client,
            nome_sezione=nome_sezione,
            nome_prompt=nome_prompt,
            nome_schema=nome_schema,
            label_sezione=label,
            chat_text=chat_text,
        )
        if estratto:
            profilo[nome_sezione] = _mergia_sezione(
                profilo.get(nome_sezione, {}), estratto
            )

    # 4. Calcolo MVP (input: profilo con le 4 sezioni già compilate)
    print("   → manipulation_vulnerability_profile")
    mvp = _estrai_mvp(client, profilo)
    if mvp:
        profilo["manipulation_vulnerability_profile"] = _mergia_sezione(
            profilo.get("manipulation_vulnerability_profile", {}), mvp
        )

    # 5. Output su disco
    print("3. Salvataggio...")
    _salva_output(partecipante_id, profilo, output_dir)

    # 6. Supabase
    if salva_su_db:
        _salva_su_db(partecipante_id, profilo)

    print(f"✓ Completato: {partecipante_id}\n")
    return profilo


def sintetizza_tutti(
    partecipanti: list[str],
    output_dir: Optional[Path] = None,
    salva_su_db: bool = True,
) -> dict[str, dict]:
    """Elabora una lista di partecipanti in sequenza."""
    risultati: dict[str, dict] = {}
    for pid in partecipanti:
        try:
            risultati[pid] = sintetizza_e_salva_profilo(
                partecipante_id=pid,
                output_dir=output_dir,
                salva_su_db=salva_su_db,
            )
        except Exception as e:
            print(f"  ✗ Errore per {pid}: {e}")
            risultati[pid] = {}
    return risultati


# ─────────────────────────────────────────────────────────────────────────────
# Entry point standalone
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Sintetizza il profilo JSON di uno o più partecipanti post-chat"
    )
    parser.add_argument(
        "partecipanti",
        nargs="+",
        help="Uno o più ID partecipante (es. U1 U2 PERSONA_3)",
    )
    parser.add_argument(
        "--sessione-id",
        type=int,
        default=None,
        help="ID sessione profilazione (solo con un partecipante singolo)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Cartella radice per i file JSON (default: ./output)",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Non salvare su Supabase",
    )
    args = parser.parse_args()

    if len(args.partecipanti) == 1:
        sintetizza_e_salva_profilo(
            partecipante_id=args.partecipanti[0],
            sessione_id=args.sessione_id,
            output_dir=args.output_dir,
            salva_su_db=not args.no_db,
        )
    else:
        if args.sessione_id:
            print("⚠  --sessione-id ignorato con più partecipanti.")
        sintetizza_tutti(
            partecipanti=args.partecipanti,
            output_dir=args.output_dir,
            salva_su_db=not args.no_db,
        )