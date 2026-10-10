# Guida operativa

## Scopo

Questa guida descrive come lavorare sulla versione italiana di `code-modernization`.

La repository italiana è:

```text
alangiacomin/claude-marketplace
```

Il branch stabile è:

```text
main
```

La repository ufficiale Anthropic è utilizzata come upstream:

```text
anthropics/claude-plugins-official
```

---

# 1. Regola principale

La repository italiana è il punto di riferimento per la versione italiana.

Le modifiche di traduzione e localizzazione devono essere effettuate nella repository italiana.

Le modifiche funzionali sviluppate da Anthropic vengono invece importate tramite la sincronizzazione upstream.

In pratica:

```text
Anthropic
   │
   │ nuove modifiche funzionali
   ▼
upstream sync
   │
   ▼
Pull Request
   │
   ▼
revisione italiana
   │
   ▼
main
```

---

# 2. Modificare una traduzione

Le modifiche italiane possono essere effettuate normalmente sui file del repository.

Per esempio:

```text
plugins/code-modernization/README.md
plugins/code-modernization/CHANGELOG.md
plugins/code-modernization/commands/
plugins/code-modernization/agents/
```

oppure nei file relativi alle istruzioni, ai testi mostrati all'utente o alla documentazione.

Prima di modificare:

```bash
cd ~/Git/code-modernization-it
```

È consigliabile verificare lo stato:

```bash
git status
```

Il working tree dovrebbe essere pulito prima di iniziare un nuovo lavoro.

---

# 3. Creare un branch per una modifica italiana

Per una modifica non banale è consigliato utilizzare un branch dedicato.

Esempio:

```bash
git switch -c fix/traduzione-readme
```

Modificare i file con l'editor preferito.

Nel nostro ambiente è possibile utilizzare Kate:

```bash
kate plugins/code-modernization/README.md
```

oppure:

```bash
kate .github/workflows/sync-upstream-code-modernization.yml
```

---

# 4. Controllare le modifiche

Dopo aver modificato i file:

```bash
git status
```

e:

```bash
git diff
```

Per controllare problemi di whitespace:

```bash
git diff --check
```

È buona pratica eseguire tutti e tre i controlli prima del commit.

---

# 5. Commit della modifica italiana

Quando la modifica è corretta:

```bash
git add <file>
```

poi:

```bash
git commit -m "docs: update Italian translation"
```

Il messaggio del commit deve descrivere brevemente cosa è stato modificato.

Esempi:

```text
docs: update Italian README
docs: translate modernization command
fix: correct Italian wording
docs: update Italian changelog
```

---

# 6. Pubblicare una modifica italiana

Per pubblicare il branch:

```bash
git push -u origin fix/traduzione-readme
```

Successivamente è possibile creare una normale Pull Request verso:

```text
main
```

---

# 7. Modifiche funzionali upstream

Quando Anthropic modifica `code-modernization`, non è necessario copiare manualmente i file.

La GitHub Action controlla la repository upstream.

Attualmente la Action viene avviata manualmente:

```text
GitHub
→ Actions
→ Sync upstream code-modernization
→ Run workflow
```

La Action confronta la versione upstream con `main`.

---

# 8. Quando non ci sono aggiornamenti

Se Anthropic non ha modificato il plugin dall'ultima sincronizzazione, la Action termina con:

```text
No upstream changes detected.
```

In questo caso non viene creato nulla.

Non vengono creati:

```text
sync/code-modernization-XXXXXXX
```

e non viene aperta alcuna Pull Request.

Non è necessario fare nessuna operazione.

---

# 9. Quando ci sono aggiornamenti upstream

Se vengono rilevate modifiche, la Action:

1. recupera la repository Anthropic;
2. estrae solo `plugins/code-modernization/`;
3. confronta la storia filtrata con `main`;
4. crea un branch:

```text
sync/code-modernization-XXXXXXXX
```

5. esegue il merge dell'upstream nel branch;
6. pubblica il branch su GitHub;
7. apre automaticamente una Pull Request verso `main`.

La PR avrà un titolo simile a:

```text
chore: sync code-modernization from upstream
```

---

# 10. Cosa fare quando arriva una PR upstream

La PR deve essere trattata come una normale modifica al progetto.

Controllare:

* quali file sono cambiati;
* quali modifiche funzionali sono state introdotte;
* eventuali modifiche al README;
* eventuali modifiche ai comandi;
* eventuali modifiche agli agent;
* eventuali modifiche agli hook;
* eventuali test;
* eventuali modifiche che richiedono una nuova traduzione italiana.

Non fare il merge automaticamente senza aver controllato il contenuto.

---

# 11. Effetti sulle traduzioni italiane

Questo è il punto più importante.

Una sincronizzazione upstream può modificare file che contengono testo già tradotto in italiano.

Per esempio:

```text
README.md
commands/qualcosa.md
agents/qualcosa.md
```

Se Anthropic modifica una stessa porzione di testo che è stata modificata anche nella versione italiana, Git può generare un conflitto.

Questo è normale.

La sincronizzazione **non deve sovrascrivere silenziosamente le modifiche italiane**.

---

# 12. Conflitto Git

In caso di conflitto, la Action si ferma durante il merge.

Non viene pubblicato il branch di sync e non viene creata la PR.

Questo significa che il conflitto deve essere risolto manualmente.

Il maintainer deve quindi:

1. individuare il conflitto;
2. confrontare la versione upstream;
3. confrontare la versione italiana;
4. decidere quale testo o struttura mantenere;
5. applicare eventualmente la nuova traduzione;
6. verificare il risultato;
7. completare il merge.

---

# 13. Principio per la risoluzione dei conflitti

Quando un conflitto riguarda testo inglese modificato upstream e testo italiano localizzato, non bisogna semplicemente scegliere:

```text
ours
```

oppure:

```text
theirs
```

senza analizzare il contenuto.

Bisogna invece verificare la modifica funzionale upstream e riportarla nella versione italiana mantenendo la localizzazione.

Esempio concettuale:

```text
UPSTREAM:
Run the modernization analysis on the selected files.

ITALIANO ATTUALE:
Esegue l'analisi di modernizzazione sui file selezionati.
```

Se upstream cambia la frase in:

```text
Run the modernization analysis on the selected files and report failures.
```

la soluzione corretta non è necessariamente scegliere una delle due versioni.

Bisogna aggiornare la traduzione:

```text
Esegue l'analisi di modernizzazione sui file selezionati
e segnala gli errori.
```

---

# 14. Modifiche italiane durante una sincronizzazione

È possibile che una modifica italiana sia già presente in `main` quando arriva un aggiornamento upstream.

Questo è previsto.

La PR di sincronizzazione serve proprio a permettere di verificare l'interazione tra:

```text
nuove modifiche upstream
```

e:

```text
personalizzazioni/localizzazione italiana
```

Prima del merge controllare sempre il diff completo della PR.

---

# 15. Dopo il merge della PR

Quando la PR upstream viene approvata e mergiata:

```text
main
```

contiene la nuova versione sincronizzata.

A quel punto eventuali modifiche italiane risolte durante la PR sono già parte di `main`.

Non bisogna eseguire nuovamente la stessa sincronizzazione.

---

# 16. Verificare lo stato locale

Dopo un merge su GitHub:

```bash
cd ~/Git/code-modernization-it
```

poi:

```bash
git switch main
git pull
```

e:

```bash
git status
```

Il repository dovrebbe risultare pulito.

---

# 17. Non modificare manualmente il branch di sync

I branch:

```text
sync/code-modernization-XXXXXXXX
```

sono branch temporanei generati automaticamente dalla Action.

Normalmente non devono essere utilizzati per il normale sviluppo italiano.

Se una PR richiede una correzione manuale, la correzione può essere fatta direttamente sulla PR/branch secondo le normali procedure GitHub.

---

# 18. Non modificare il contenuto upstream direttamente

Non bisogna modificare manualmente il contenuto italiano cercando di simulare un aggiornamento upstream.

La sincronizzazione deve partire dalla repository ufficiale:

```text
anthropics/claude-plugins-official
```

e deve importare esclusivamente:

```text
plugins/code-modernization/
```

---

# 19. Aggiornamento della Action

La Action si trova in:

```text
.github/workflows/sync-upstream-code-modernization.yml
```

Se bisogna modificarla, farlo con attenzione perché è parte dell'infrastruttura del progetto.

Prima della modifica:

```bash
git status
```

Dopo la modifica:

```bash
git diff --check
git diff -- .github/workflows/sync-upstream-code-modernization.yml
```

Controllare il diff prima del commit.

---

# 20. Verifica manuale della Action

Per avviare una sincronizzazione manuale:

```text
GitHub
→ Actions
→ Sync upstream code-modernization
→ Run workflow
```

Non è necessario eseguire comandi locali per effettuare il sync upstream.

La sincronizzazione viene eseguita dal runner GitHub Actions.

---

# 21. Collaboratori Windows

I collaboratori che lavorano su Windows **non devono installare Linux o WSL per la sincronizzazione upstream**.

La parte di sincronizzazione automatica viene eseguita da:

```text
GitHub Actions
```

su:

```text
ubuntu-latest
```

Il repository locale Windows serve solamente per il normale sviluppo, traduzione e revisione.

---

# 22. Sequenza operativa consigliata

Per una normale modifica italiana:

```text
1. git switch main
2. git pull
3. creare branch di lavoro
4. modificare i file
5. controllare git diff
6. eseguire git diff --check
7. commit
8. push
9. Pull Request verso main
10. revisione
11. merge
```

Per una sincronizzazione upstream:

```text
1. GitHub Actions
2. Run workflow
3. attendere il risultato
4. se nessun cambiamento → fine
5. se cambiamenti → verificare la PR
6. controllare il diff
7. risolvere eventuali conflitti
8. verificare la traduzione
9. approvare
10. merge
```

---

# 23. Regola pratica finale

In caso di dubbio, distinguere sempre tra:

### Modifica italiana

```text
Io modifico → branch italiano → PR → main
```

### Modifica upstream

```text
Anthropic modifica
        ↓
Action
        ↓
sync/code-modernization-XXXX
        ↓
Pull Request
        ↓
revisione italiana
        ↓
main
```

La repository italiana mantiene quindi la propria identità e localizzazione, mentre il codice originale di Anthropic viene seguito tramite una sincronizzazione controllata e revisionabile.

