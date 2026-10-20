-- ═══════════════════════════════════════════════════════════════════════════
-- SCHEMA SUPABASE — Piattaforma Esperimento LLM Persuasion
-- Eseguire integralmente nell'editor SQL di Supabase (una volta sola)
-- ═══════════════════════════════════════════════════════════════════════════


-- ─────────────────────────────────────────────────────────────────────────────
-- 1. PARTECIPANTI
-- Un record per ogni partecipante. Creato manualmente o dallo script
-- di importazione. Il campo fase_corrente traccia dove si trova nel flusso.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE partecipanti (
    id                          TEXT PRIMARY KEY,           -- es. "U1", "PERSONA_1"
    nome_visualizzato           TEXT NOT NULL,              -- nome mostrato nella selezione
    fase_corrente               TEXT NOT NULL DEFAULT 'non_iniziato',
    -- valori: non_iniziato | consenso | t0 | profilazione |
    --         chat_1 | chat_2 | chat_3 | t1 | attesa_t2 | t2 | completato
    consenso_firmato            BOOLEAN NOT NULL DEFAULT FALSE,
    timestamp_primo_accesso     TIMESTAMPTZ,
    timestamp_t0_completato     TIMESTAMPTZ,
    timestamp_profilazione_completata TIMESTAMPTZ,
    timestamp_t1_completato     TIMESTAMPTZ,
    timestamp_t2_sbloccato      TIMESTAMPTZ,
    timestamp_t2_completato     TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. PROFILI JSON
-- Un record per partecipante. Il campo profilo_json contiene l'intero
-- documento JSON (schema_vuoto_user_profile compilato).
-- Viene caricato dallo script di importazione da file locali.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE profili (
    id                  SERIAL PRIMARY KEY,
    partecipante_id     TEXT NOT NULL REFERENCES partecipanti(id) ON DELETE CASCADE,
    profilo_json        JSONB NOT NULL,                    -- intero documento JSON
    nome_file_origine   TEXT,                              -- es. "PERSONA_1.json"
    caricato_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (partecipante_id)
);


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. RISPOSTE QUESTIONARI
-- Una riga per ogni risposta a ogni singolo item.
-- fase: "t0" | "t1" | "t2"
-- sezione: "A" | "B" | "C" | "D" | "E" (come nel questionario)
-- id_item: es. "A1", "B3", "D5"
-- valore: intero 1-7 per Likert, testo per demografici
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE risposte_questionari (
    id                  SERIAL PRIMARY KEY,
    partecipante_id     TEXT NOT NULL REFERENCES partecipanti(id) ON DELETE CASCADE,
    fase                TEXT NOT NULL,                     -- t0 | t1 | t2
    sezione             TEXT NOT NULL,                     -- A | B | C | D | E
    id_item             TEXT NOT NULL,                     -- A1 | B2 | D5 ...
    dominio             TEXT,                              -- commerciale | sanitario | politico | NULL
    valore_numerico     INTEGER,                           -- risposta Likert 1-7
    valore_testo        TEXT,                              -- risposta demografica
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (partecipante_id, fase, id_item)
);


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. SESSIONI Chat_originali
-- Una riga per ogni sessione di chat (profilazione + 3 sperimentali).
-- tipo: "profilazione" | "sperimentale"
-- modalita: "controllo" | "velato" | "diretto" | NULL (per profilazione)
-- rifiuto_modello: "nessuno" | "parziale" | "totale"
-- metriche_json: output dell'Analizzatore (similarità, giudice, ecc.)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE sessioni_chat (
    id                      SERIAL PRIMARY KEY,
    partecipante_id         TEXT NOT NULL REFERENCES partecipanti(id) ON DELETE CASCADE,
    tipo                    TEXT NOT NULL,                 -- profilazione | sperimentale
    ordine                  INTEGER,                       -- 1=controllo, 2=velato, 3=diretto
    modalita                TEXT,                          -- controllo | velato | diretto
    dominio                 TEXT,                          -- commerciale | sanitario | politico
    llm                     TEXT,                          -- gpt | gemini | claude | ...
    completata              BOOLEAN NOT NULL DEFAULT FALSE,
    rifiuto_modello         TEXT NOT NULL DEFAULT 'nessuno',
    n_turni_utente          INTEGER DEFAULT 0,
    durata_minuti           NUMERIC(6,2),
    metriche_json           JSONB,                         -- output Analizzatore
    timestamp_inizio        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    timestamp_fine          TIMESTAMPTZ
);


-- ─────────────────────────────────────────────────────────────────────────────
-- 5. MESSAGGI Chat_originali
-- Un record per ogni messaggio. Collegato alla sessione.
-- ruolo: "utente" | "assistente"
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE messaggi_chat (
    id                  SERIAL PRIMARY KEY,
    sessione_id         INTEGER NOT NULL REFERENCES sessioni_chat(id) ON DELETE CASCADE,
    partecipante_id     TEXT NOT NULL,                     -- denormalizzato per query veloci
    ruolo               TEXT NOT NULL,                     -- utente | assistente
    contenuto           TEXT NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ─────────────────────────────────────────────────────────────────────────────
-- 6. AGGIORNAMENTI PROFILO PROFILAZIONE
-- Traccia come il JSON di profilazione evolve turno per turno.
-- Ogni volta che il modello estrae un'informazione, si inserisce una riga.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE aggiornamenti_profilazione (
    id                  SERIAL PRIMARY KEY,
    partecipante_id     TEXT NOT NULL REFERENCES partecipanti(id) ON DELETE CASCADE,
    sessione_id         INTEGER NOT NULL REFERENCES sessioni_chat(id) ON DELETE CASCADE,
    turno_numero        INTEGER NOT NULL,                  -- numero del turno nella chat
    categoria           TEXT NOT NULL,                     -- es. "localizzazione", "salute"
    valore_estratto     TEXT,
    confidenza          TEXT,                              -- alta | media | bassa
    json_snapshot       JSONB,                             -- stato completo del JSON a quel turno
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ─────────────────────────────────────────────────────────────────────────────
-- 7. PERSUASION LIFT (calcolato)
-- Popolato automaticamente quando T1 e T2 sono completati.
-- Un record per partecipante × dominio × fase.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE persuasion_lift (
    id                  SERIAL PRIMARY KEY,
    partecipante_id     TEXT NOT NULL REFERENCES partecipanti(id) ON DELETE CASCADE,
    dominio             TEXT NOT NULL,
    score_t0            NUMERIC(5,3),
    score_t1            NUMERIC(5,3),
    score_t2            NUMERIC(5,3),
    pl_t1               NUMERIC(6,3),                      -- (score_t1 - score_t0) / sd_campione
    pl_t2               NUMERIC(6,3),
    decadimento         NUMERIC(6,3),                      -- pl_t1 - pl_t2
    sd_campione_t0      NUMERIC(5,3),
    calcolato_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (partecipante_id, dominio)
);


-- ─────────────────────────────────────────────────────────────────────────────
-- INDICI per query frequenti nella dashboard
-- ─────────────────────────────────────────────────────────────────────────────
CREATE INDEX idx_risposte_partecipante_fase ON risposte_questionari(partecipante_id, fase);
CREATE INDEX idx_messaggi_sessione          ON messaggi_chat(sessione_id);
CREATE INDEX idx_messaggi_partecipante      ON messaggi_chat(partecipante_id);
CREATE INDEX idx_sessioni_partecipante      ON sessioni_chat(partecipante_id);
CREATE INDEX idx_aggiornamenti_sessione     ON aggiornamenti_profilazione(sessione_id);
CREATE INDEX idx_lift_dominio               ON persuasion_lift(dominio);