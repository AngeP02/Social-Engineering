from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Optional

from clients import get_client

from Utils.prompts_profilazione import (
    VERSIONE_PROMPT,
    TURNI_MINIMI_UTENTE,
    costruisci_prompt_profilazione,
    sintetizza_t0_per_prompt,
    sintetizza_sr_per_prompt,
    _serializza_stato_profilo,
)
from Utils.database import (
    crea_sessione_chat,
    chiudi_sessione_chat,
    salva_messaggio,
    salva_aggiornamento_profilazione,
    leggi_risposte_questionario,
)
from Utils.database import storage_leggi_json, storage_file_esiste


#_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "Dati" / "schema_vuoto_user_profile.json"

_SCHEMA_PATH = "Dati/schema_vuoto_user_profile.json"

def _carica_schema_vuoto() -> dict:
    try:
        return storage_leggi_json(_SCHEMA_PATH)
    except Exception:
        return {
            "subject_id": "", "model": "", "source_type": "llm_chat", "condition": "profiling",
            "non_sensitive_attributes": {}, "private_attributes": {},
            "psychological_attributes": {}, "sensitive_attributes": {},
            "manipulation_vulnerability_profile": {},
            "meta": {"extraction_prompt_version": VERSIONE_PROMPT},
        }

CFG_MODELLO_PROFILAZIONE = {
    "provider": "openrouter",
    "model": "google/gemini-2.5-flash",
    "api_key_env": "OPENROUTER_API_KEY",
    "temperature": 0.7,
    "max_tokens":  1500,
}

LABEL_MODELLO_PROFILAZIONE = "profilazione_gemini"

_RE_PROFILO_UPDATE = re.compile(
    r"<profilo_update>(.*?)</profilo_update>",
    re.DOTALL | re.IGNORECASE,
)
_RE_MVP_UPDATE = re.compile(
    r"<mvp_update>(.*?)</mvp_update>",
    re.DOTALL | re.IGNORECASE,
)


def estrai_testo_pulito(risposta: str) -> str:

    testo = _RE_PROFILO_UPDATE.sub("", risposta)
    testo = _RE_MVP_UPDATE.sub("", testo)
    testo = re.sub(r"<profilo_update>.*?</mvp_update>", "", testo, flags=re.DOTALL | re.IGNORECASE)
    testo = re.sub(r"<mvp_update>.*?</profilo_update>", "", testo, flags=re.DOTALL | re.IGNORECASE)

    return testo.strip()

def _parse_json_da_blocco(contenuto: str) -> Optional[dict]:
    contenuto = contenuto.strip()
    if contenuto.lower() == "null" or not contenuto:
        return None
    try:
        return json.loads(contenuto)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", contenuto, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def _trova_campo_schema(schema: dict, categoria: str) -> tuple[Optional[dict], Optional[str]]:
    sezioni = [
        "non_sensitive_attributes",
        "private_attributes",
        "psychological_attributes",
        "sensitive_attributes",
        "manipulation_vulnerability_profile",
    ]
    for nome_sezione in sezioni:
        sezione = schema.get(nome_sezione, {})
        if categoria in sezione:
            return sezione, categoria
        for chiave_padre, valore_padre in sezione.items():
            if isinstance(valore_padre, dict) and categoria in valore_padre:
                return valore_padre, categoria
    return None, None


def applica_aggiornamento_profilo(
    schema_corrente: dict,
    aggiornamento: dict,
) -> dict:

    schema = copy.deepcopy(schema_corrente)

    categoria = aggiornamento.get("categoria", "")
    valore = aggiornamento.get("valore")
    confidenza  = float(aggiornamento.get("confidenza", 0.5))
    inf_type = aggiornamento.get("inference_type", "inferred")
    quote = aggiornamento.get("quote", "")

    if not categoria or valore is None:
        return schema

    sezione, chiave = _trova_campo_schema(schema, categoria)
    if sezione is None:
        return schema

    campo = sezione.get(chiave, {})
    if not isinstance(campo, dict):
        return schema

    confidenza_attuale = float(campo.get("confidence", 0.0))
    if confidenza >= confidenza_attuale:
        campo["confidence"] = confidenza
        campo["inference_type"] = inf_type

        if isinstance(campo.get("value"), list):
            if valore not in campo["value"]:
                campo["value"].append(valore)
        else:
            campo["value"] = valore

        if quote:
            evidence_list = campo.get("evidence", [])
            if isinstance(evidence_list, list):
                evidence_list.append({"quote": quote, "doc_id": "chat_profilazione"})
                campo["evidence"] = evidence_list

        sezione[chiave] = campo

    return schema


def applica_mvp_update(schema_corrente: dict, mvp: dict) -> dict:
    schema = copy.deepcopy(schema_corrente)
    mvp_schema = schema.get("manipulation_vulnerability_profile", {})

    for campo, dati in mvp.items():
        if campo in mvp_schema and isinstance(dati, dict):
            conf_nuova = float(dati.get("confidence", 0.0))
            conf_att   = float(mvp_schema[campo].get("confidence", 0.0))
            if conf_nuova >= conf_att:
                mvp_schema[campo].update(dati)

    schema["manipulation_vulnerability_profile"] = mvp_schema
    return schema


def percentuale_completamento(schema: dict) -> int:

    totale = 0
    compilati = 0

    def _conta(obj):
        nonlocal totale, compilati
        if isinstance(obj, dict):
            if "confidence" in obj and "value" in obj:
                totale += 1
                valore = obj["value"]
                conf   = float(obj.get("confidence", 0.0))
                ha_valore = bool(valore) if not isinstance(valore, (int, float)) else valore > 0
                if ha_valore and conf >= 0.5:
                    compilati += 1
            else:
                for v in obj.values():
                    _conta(v)

    for sezione in ["non_sensitive_attributes", "private_attributes",
                    "psychological_attributes", "sensitive_attributes"]:
        _conta(schema.get(sezione, {}))

    return int(compilati / max(totale, 1) * 100)


class SessioneProfilazione:

    def __init__(
        self,
        partecipante_id: str,
        nfc_score: float,
        frequenza_ai: str,
    ):
        self.partecipante_id  = partecipante_id
        self.nfc_score = nfc_score
        self.frequenza_ai = frequenza_ai

        self.schema_corrente: dict = _carica_schema_vuoto()
        self.schema_corrente["subject_id"] = partecipante_id
        self.schema_corrente["model"] = CFG_MODELLO_PROFILAZIONE["model"]
        self.schema_corrente["source_type"] = "llm_chat"
        self.schema_corrente["condition"] = "profiling_velato"
        self.schema_corrente["meta"]["extraction_prompt_version"] = VERSIONE_PROMPT

        self.messaggi_storia: list[dict] = []
        self.messaggi_visibili: list[dict] = []

        self.turni_utente: int = 0
        self.sessione_id: Optional[int] = None
        self._client = None
        self._prompt_sistema: str = ""
        self._riassunto_t0: str = ""
        self._riassunto_sr: str = ""

    def inizia(self) -> str:

        # --- T0 ---
        risposte_t0 = leggi_risposte_questionario(self.partecipante_id, "t0")
        self._riassunto_t0 = sintetizza_t0_per_prompt(risposte_t0)

        # --- Self-report: leggi dal DB e precarica lo schema ---
        risposte_sr = leggi_risposte_questionario(self.partecipante_id, "self_report")
        self._riassunto_sr = sintetizza_sr_per_prompt(risposte_sr)
        print(f"   SR: {self._riassunto_sr[:150]!r}")
        print(f"   T0: {self._riassunto_t0[:150]!r}")

        # Precarica lo schema con i dati SR se il profilo JSON esiste su disco;
        # altrimenti usa lo schema vuoto (la chat li raccoglierà via conversazione).
        #_profilo_sr_path = _SCHEMA_PATH.parent / "profili_json_completi" / f"PERSONA_{self.partecipante_id}.json"
        _profilo_sr_path = f"Dati/profili_json_completi/PERSONA_{self.partecipante_id}.json"
        if storage_file_esiste(_profilo_sr_path):
            self.schema_corrente = storage_leggi_json(_profilo_sr_path)
            # Sovrascrivi i metadati di sessione mantenendo i dati SR
            self.schema_corrente["model"] = CFG_MODELLO_PROFILAZIONE["model"]
            self.schema_corrente["source_type"] = "llm_chat"
            self.schema_corrente["condition"] = "profiling_velato"
            self.schema_corrente["meta"]["extraction_prompt_version"] = VERSIONE_PROMPT

        self._prompt_sistema = costruisci_prompt_profilazione(
            partecipante_id=self.partecipante_id,
            nfc_score=self.nfc_score,
            frequenza_ai=self.frequenza_ai,
            risposte_t0_summary=self._riassunto_t0,
            profilo_corrente=self.schema_corrente if risposte_sr else None,
            risposte_sr_summary=self._riassunto_sr,
        )
        self._client = get_client(CFG_MODELLO_PROFILAZIONE)
        self.sessione_id = crea_sessione_chat(
            partecipante_id=self.partecipante_id,
            tipo="profilazione",
            llm=LABEL_MODELLO_PROFILAZIONE,
        )
        self.messaggi_storia = [
            {"role": "system", "content": self._prompt_sistema},
            {"role": "user",   "content": "Ciao!"},
        ]

        risposta_raw = self._chiama_modello()
        testo_visibile = estrai_testo_pulito(risposta_raw)
        self._aggiorna_da_risposta(risposta_raw, turno=0)

        self.messaggi_storia.append({"role": "assistant", "content": risposta_raw})
        salva_messaggio(self.sessione_id, self.partecipante_id, "utente", "Ciao!")
        salva_messaggio(self.sessione_id, self.partecipante_id, "assistente", testo_visibile)

        self.messaggi_visibili.append({"ruolo": "assistente", "contenuto": testo_visibile})
        return testo_visibile

    def invia_messaggio(self, testo_utente: str) -> str:
        self.turni_utente += 1
        self.messaggi_storia.append({"role": "user", "content": testo_utente})
        self._aggiorna_prompt_con_profilo()
        risposta_raw   = self._chiama_modello()
        testo_visibile = estrai_testo_pulito(risposta_raw)
        self.messaggi_storia.append({"role": "assistant", "content": risposta_raw})
        self._aggiorna_da_risposta(risposta_raw, turno=self.turni_utente)
        salva_messaggio(self.sessione_id, self.partecipante_id, "utente",      testo_utente)
        salva_messaggio(self.sessione_id, self.partecipante_id, "assistente",  testo_visibile)
        self.messaggi_visibili.append({"ruolo": "utente",     "contenuto": testo_utente})
        self.messaggi_visibili.append({"ruolo": "assistente", "contenuto": testo_visibile})

        return testo_visibile

    @property
    def completabile(self) -> bool:
        return self.turni_utente >= TURNI_MINIMI_UTENTE

    def chiudi(self) -> None:
        if self.sessione_id is None:
            return

        perc = percentuale_completamento(self.schema_corrente)
        chiudi_sessione_chat(
            sessione_id=self.sessione_id,
            n_turni_utente=self.turni_utente,
            durata_minuti=0.0,  # calcolato lato DB dai timestamp
            rifiuto_modello="nessuno",
            metriche={
                "percentuale_completamento_schema": perc,
                "versione_prompt": VERSIONE_PROMPT,
                "nfc_score_usato": self.nfc_score,
            },
        )


    def _aggiorna_prompt_con_profilo(self) -> None:
        nuovo_prompt = costruisci_prompt_profilazione(
            partecipante_id=self.partecipante_id,
            nfc_score=self.nfc_score,
            frequenza_ai=self.frequenza_ai,
            risposte_t0_summary=self._riassunto_t0,
            profilo_corrente=self.schema_corrente,
            risposte_sr_summary=self._riassunto_sr,
        )
        self._prompt_sistema = nuovo_prompt

        if self.messaggi_storia and self.messaggi_storia[0]["role"] == "system":
            self.messaggi_storia[0]["content"] = nuovo_prompt

    def _chiama_modello(self) -> str:
        if hasattr(self._client, "send_chat"):
            risposta = self._client.send_chat(self.messaggi_storia)
        else:
            prompt_fallback = "\n\n".join(
                f"[{m['role'].upper()}]\n{m['content']}"
                for m in self.messaggi_storia
            )
            risposta = self._client.send_prompt(prompt_fallback)
        return risposta.text

    def _aggiorna_da_risposta(self, risposta_raw: str, turno: int) -> None:

        match_profilo = _RE_PROFILO_UPDATE.search(risposta_raw)
        if match_profilo:
            aggiornamento = _parse_json_da_blocco(match_profilo.group(1))
            if aggiornamento and isinstance(aggiornamento, dict):

                categoria = aggiornamento.get("categoria")

                if categoria:
                    self.schema_corrente = applica_aggiornamento_profilo(
                        self.schema_corrente, aggiornamento
                    )
                    if self.sessione_id is not None:
                        salva_aggiornamento_profilazione(
                            partecipante_id=self.partecipante_id,
                            sessione_id=self.sessione_id,
                            turno_numero=turno,
                            categoria=categoria,
                            valore_estratto=str(aggiornamento.get("valore", "")),
                            confidenza=str(aggiornamento.get("confidenza", 0.0)),
                            json_snapshot=self.schema_corrente,
                        )

        match_mvp = _RE_MVP_UPDATE.search(risposta_raw)
        if match_mvp:
            mvp = _parse_json_da_blocco(match_mvp.group(1))
            if mvp and isinstance(mvp, dict):
                self.schema_corrente = applica_mvp_update(self.schema_corrente, mvp)