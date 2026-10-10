# Claude Marketplace

Marketplace centralizzato di plugin per [Claude Code](https://code.claude.com). Ogni plugin vive in una sottocartella di `plugins/`.

## Uso

```
/plugin marketplace add alangiacomin/claude-marketplace
/plugin install <plugin>@alan.giacomin
```

## Plugin disponibili

| Plugin | Descrizione |
|--------|-------------|
| [`code-modernization`](plugins/code-modernization/README.md) | Modernizzazione guidata di codebase legacy. Versione italiana del plugin Anthropic, sincronizzata con l'upstream. |

## Struttura del repository

```text
.claude-plugin/marketplace.json   catalogo dei plugin (nome marketplace: alan.giacomin)
plugins/<nome-plugin>/            un plugin per cartella, con il proprio .claude-plugin/plugin.json
.github/workflows/                sincronizzazione con l'upstream
tools/                            script di supporto
```

Documentazione operativa: [OPERATIONS.md](OPERATIONS.md) per il lavoro quotidiano, [UPSTREAM_SYNC_ACTION_CODE_MODERNIZATION.md](UPSTREAM_SYNC_ACTION_CODE_MODERNIZATION.md) per il funzionamento della Action di sincronizzazione.

## Aggiungere un plugin

1. Crea `plugins/<nome>/` con `.claude-plugin/plugin.json`.
2. Aggiungi una voce in `plugins[]` di `.claude-plugin/marketplace.json` con `"source": "./plugins/<nome>"`.
3. Verifica con `claude plugin validate .`.
