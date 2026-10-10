# Lingua del plugin

Direttiva per ogni comando, agente e workflow:

> Parla con l'utente in italiano, poni ogni domanda in italiano e scrivi in italiano ogni documento e report generato
> (testo, titoli, tabelle, note). Non tradurre i token tecnici elencati qui sotto: sono letti da script e hook.

## Da lasciare in inglese

- Nomi di file generati (`ASSESSMENT.md`, `BUSINESS_RULES.md`, `INTENT.md`, `MODERNIZATION_BRIEF.md`, ...), chiavi JSON e nomi degli agenti.
- Intestazioni di fase `Phase N` nel brief.
- Parole chiave delle regole: `Given`, `When`, `Then`, `And`, le priorità `P0`–`P3`, gli id `RULE-NNN` e `D-nn`.
- Esiti dei test `pass`, `fail`, `error`, `skipped`.
- Verdetti `PROVEN`, `PARTLY PROVEN`, `NOT PROVEN` e le chiavi di revisione `confirmed`, `wrong`, `discuss`.
- L'etichetta `Goal:` in `INTENT.md`, seguita da una tra `uplift`, `transform`, `reimagine`, `understand`.
- Identificatori di codice, percorsi e comandi.

Tutto il resto, compresi spiegazioni, descrizioni, nomi leggibili delle regole e note, va in italiano.
