# Upstream Sync Action — code-modernization

## Scopo

La GitHub Action `Sync upstream code-modernization` mantiene sincronizzata la repository italiana con il plugin ufficiale `code-modernization` di Anthropic.

La repository (marketplace `alan.giacomin`) contiene più plugin, ciascuno in una sottocartella di `plugins/`. Il plugin sincronizzato vive in:

```text
plugins/code-modernization/
├── .claude-plugin/
├── CHANGELOG.md
├── LICENSE
├── README.md
├── agents/
├── assets/
├── commands/
├── hooks/
├── scripts/
├── tests/
├── tsconfig.json
└── workflows/
```

Nella radice restano i file del marketplace (`.claude-plugin/marketplace.json`, `README.md`) e quelli operativi (`.github/`, `tools/`, `OPERATIONS.md`, `UPSTREAM_SYNC_ACTION_CODE_MODERNIZATION.md`), che la sincronizzazione non tocca.

La repository ufficiale Anthropic, invece, contiene molti plugin. La Action importa esclusivamente:

```text
plugins/code-modernization/
```

e lo porta in `plugins/code-modernization/` della repository.

---

## Repository coinvolte

### Repository italiana

```text
https://github.com/alangiacomin/claude-marketplace
```

È la repository ufficiale della versione italiana.

Il branch stabile è:

```text
main
```

### Repository upstream

```text
https://github.com/anthropics/claude-plugins-official.git
```

Il branch utilizzato è:

```text
main
```

La repository Anthropic rimane la sorgente ufficiale per il contenuto originale del plugin.

---

## Principio fondamentale

Il repository italiano e quello upstream hanno una storia Git diversa.

Per questo motivo **non viene fatto un merge diretto dell'intero repository Anthropic**.

La Action esegue invece questo processo:

```text
Anthropic repository
        │
        │ plugins/code-modernization/
        ▼
   git-filter-repo
        │
        ▼
storia Git filtrata
        │
        ▼
confronto con main italiano
        │
        ├── nessuna modifica
        │       └── termina
        │
        └── modifiche presenti
                │
                ▼
        branch sync/code-modernization-XXXX
                │
                ▼
             push
                │
                ▼
          Pull Request
                │
                ▼
       revisione manuale
                │
                ▼
         merge manuale
```

---

# Trigger

Attualmente la Action utilizza:

```yaml
on:
  workflow_dispatch:
```

Quindi viene avviata **manualmente** da GitHub Actions.

Questa scelta è intenzionale: permette di verificare e controllare il comportamento del sistema prima di introdurre un'esecuzione automatica periodica.

In futuro sarà possibile aggiungere un `schedule`, per esempio:

```yaml
on:
  workflow_dispatch:

  schedule:
    - cron: "0 8 * * 1"
```

In questo modo la sincronizzazione potrebbe essere controllata automaticamente ogni settimana.

---

# Permessi

La Action utilizza:

```yaml
permissions:
  contents: write
  pull-requests: write
```

## `contents: write`

Serve per poter:

* creare il branch di sincronizzazione;
* fare push del branch su `origin`.

## `pull-requests: write`

Serve per permettere alla Action di creare automaticamente la Pull Request tramite `gh pr create`.

Non viene assegnato alcun permesso di merge automatico.

---

# Fase 1 — Checkout

La Action esegue il checkout completo della repository italiana:

```yaml
- name: Checkout repository
  uses: actions/checkout@v4
  with:
    fetch-depth: 0
```

`fetch-depth: 0` è importante perché il confronto richiede la storia Git completa.

---

# Fase 2 — Installazione di git-filter-repo

La Action installa:

```text
git-filter-repo
```

tramite:

```bash
python3 -m pip install --user git-filter-repo
```

Questo strumento permette di estrarre dalla repository Anthropic esclusivamente la storia relativa a:

```text
plugins/code-modernization/
```

---

# Fase 3 — Recupero upstream

Viene aggiunto il remote:

```bash
git remote add upstream \
  https://github.com/anthropics/claude-plugins-official.git
```

e viene recuperato:

```bash
git fetch upstream main
```

Questo aggiorna il riferimento:

```text
upstream/main
```

---

# Fase 4 — Creazione del repository filtrato

La Action crea una directory temporanea e clona la repository Anthropic.

Successivamente esegue:

```bash
git filter-repo \
  --path plugins/code-modernization/ \
  --path-rename plugins/code-modernization/:
```

Il risultato è una nuova storia Git contenente soltanto il plugin.

La trasformazione:

```text
plugins/code-modernization/README.md
```

diventa:

```text
README.md
```

e analogamente per tutti gli altri file.

La storia filtrata ha quindi il plugin alla radice. Il riallineamento a `plugins/code-modernization/` avviene al momento del merge (Fase 9) con `-Xsubtree`: in questo modo la storia filtrata resta identica a quella già presente in `main` e il merge base continua a funzionare.

---

# Fase 5 — Importazione della storia filtrata

La storia filtrata viene resa disponibile nel repository principale tramite:

```bash
git fetch "$TEMP_DIR/upstream" main
```

Il commit filtrato viene quindi rappresentato da:

```text
FETCH_HEAD
```

Questo è importante perché permette di confrontare correttamente la storia filtrata con `main`.

---

# Fase 6 — Individuazione del commit upstream

La Action determina:

```bash
UPSTREAM_COMMIT="$(git rev-parse FETCH_HEAD)"
```

e il commit attuale della repository italiana:

```bash
MAIN_COMMIT="$(git rev-parse main)"
```

Viene inoltre calcolato l'antenato comune:

```bash
MERGE_BASE="$(git merge-base main FETCH_HEAD)"
```

L'antenato comune è fondamentale per capire quali modifiche sono state introdotte upstream dopo l'ultimo punto condiviso.

---

# Fase 7 — Confronto

Il confronto principale è:

```bash
git diff --stat main...FETCH_HEAD
```

e successivamente:

```bash
git diff --quiet main...FETCH_HEAD
```

Se non ci sono modifiche:

```text
No upstream changes detected.
```

la Action termina senza creare nulla.

Non vengono creati:

* branch;
* commit;
* push;
* Pull Request.

---

# Fase 8 — Creazione del branch di sync

Se vengono rilevate modifiche, viene creato un branch con il formato:

```text
sync/code-modernization-XXXXXXXX
```

dove `XXXXXXXX` sono i primi 8 caratteri del commit upstream filtrato.

Esempio:

```text
sync/code-modernization-03386984
```

Il branch viene creato a partire da `main`.

---

# Fase 9 — Merge dell'upstream filtrato

La Action esegue:

```bash
git merge --no-ff -Xsubtree=plugins/code-modernization FETCH_HEAD \
  -m "Sync upstream code-modernization"
```

L'opzione `-Xsubtree=plugins/code-modernization` sposta i file della storia filtrata (radice) nella sottocartella del plugin. I file nuovi upstream finiscono quindi in `plugins/code-modernization/` e non nella radice del marketplace.

Il merge è intenzionalmente separato dal branch `main`.

Questo significa che:

* `main` non viene modificato direttamente;
* le modifiche upstream finiscono in un branch temporaneo;
* eventuali conflitti si manifestano prima della Pull Request.

---

# Gestione dei conflitti

Se una modifica upstream entra in conflitto con una modifica italiana, il comando:

```bash
git merge --no-ff FETCH_HEAD
```

fallisce.

La Action termina quindi senza eseguire il push del branch.

Questo è un comportamento intenzionale e sicuro.

La repository italiana non viene sovrascritta automaticamente.

Un conflitto deve essere risolto manualmente.

---

# Fase 10 — Push

Se il merge ha avuto successo:

```bash
git push origin "$SYNC_BRANCH"
```

viene pubblicato il branch su GitHub.

Esempio:

```text
sync/code-modernization-a1b2c3d4
```

---

# Fase 11 — Creazione della Pull Request

Dopo il push viene eseguito:

```bash
gh pr create
```

con:

```text
base = main
head = sync/code-modernization-XXXXXXXX
```

Il titolo della PR è:

```text
chore: sync code-modernization from upstream
```

La descrizione contiene:

* repository upstream;
* path sincronizzato;
* commit upstream;
* indicazione che la PR è stata generata automaticamente;
* indicazione che non viene eseguito alcun merge automatico.

---

# Nessun merge automatico

La Action **non esegue mai**:

```bash
git merge
```

sul branch `main`.

Il merge Git avviene esclusivamente sul branch temporaneo:

```text
sync/code-modernization-XXXXXXXX
```

La Pull Request viene poi lasciata alla revisione umana.

Il maintainer decide se:

* approvare;
* modificare;
* risolvere eventuali conflitti;
* chiudere;
* effettuare il merge.

---

# Modifica della Action

Il file principale è:

```text
.github/workflows/sync-upstream-code-modernization.yml
```

Per modificarlo localmente:

```bash
cd ~/Git/code-modernization-it
kate .github/workflows/sync-upstream-code-modernization.yml
```

Dopo ogni modifica è consigliato eseguire:

```bash
git diff --check
```

e:

```bash
git diff -- .github/workflows/sync-upstream-code-modernization.yml
```

Prima del commit verificare che il diff contenga esclusivamente le modifiche previste.

---

# Principi da mantenere

Quando si modifica la Action, è importante mantenere questi vincoli:

1. Sincronizzare esclusivamente `plugins/code-modernization/`.
2. Non importare la repository Anthropic completa.
3. Non modificare automaticamente `main`.
4. Non fare merge automatici della Pull Request.
5. In caso di conflitto, fermare la sincronizzazione.
6. Creare la PR solo dopo che il branch è stato creato e pubblicato.
7. Mantenere `contents: write`.
8. Mantenere `pull-requests: write` se viene utilizzato `gh pr create`.
9. Mantenere `fetch-depth: 0`.
10. Verificare sempre il diff della Action prima di fare push.

---

# Stato attuale

La sincronizzazione è attualmente:

```text
manuale
    ↓
confronto upstream
    ↓
branch automatico in caso di modifiche
    ↓
Pull Request automatica
    ↓
merge manuale
```

Non è attualmente presente una schedulazione automatica.

Questo permette di controllare il sistema manualmente fino a quando il comportamento non sarà considerato sufficientemente stabile.
