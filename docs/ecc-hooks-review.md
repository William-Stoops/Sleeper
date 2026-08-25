# Revue des hooks ECC — avant activation

- **Dépôt audité** : `affaan-m/ecc`
- **Commit** : `d8409a4b0813771235555e32e3d8046a73988bfa` (2026-08-19)
- **Version plugin** : 2.2.0
- **État actuel** : hooks **désactivés** (`hooks_enabled=false` dans `~/.claude/settings.json`).
  Agents, skills et commands sont installés et actifs.
- **Méthode** : lecture de `hooks/hooks.json`, de `scripts/hooks/*.js` (52 fichiers) et de
  `scripts/lib/`, plus recherche exhaustive des appels réseau et des exécutions de binaires.

## 1. Ce qui s'exécute automatiquement

Tous les hooks sont de type `command` et lancent `node` sur un script du plugin. Aucune
intervention n'est demandée : **si `hooks_enabled=true`, ils tournent à chaque événement**.

### PreToolUse — peuvent **bloquer** un appel d'outil (exit 2)

| ID | Déclencheur | Effet |
|---|---|---|
| `pre:bash:dispatcher` | tout `Bash` | Préflight qualité, tmux, `git push`, GateGuard. Bloque `npm run dev` hors tmux, bloque un `git commit` jugé non conforme |
| `pre:edit-write:gateguard-fact-force` | 1er `Edit`/`Write`/`MultiEdit` par fichier | **Bloque** et exige une phase d'investigation avant d'autoriser l'écriture |
| `pre:config-protection` | `Write`/`Edit`/`MultiEdit` | **Bloque** toute modification des fichiers de config de linter/formateur |
| `pre:mcp-health-check` | tout outil | **Bloque** les appels MCP vers un serveur jugé en mauvaise santé |
| `pre:write:doc-file-warning` | `Write` | Avertit sur les `.md`/`.txt` non standard (exit 0) |
| `pre:edit-write:suggest-compact` | `Edit`/`Write` | Suggère `/compact` (exit 0) |
| `pre:observe:continuous-learning` | tout outil | Enregistre des observations d'usage |
| `pre:governance-capture` | `Bash`/`Write`/`Edit` | Inactif sauf `ECC_GOVERNANCE_CAPTURE=1` |

### PostToolUse — analysent, ne bloquent pas

`post:quality-gate`, `post:edit:accumulator`, `post:edit:console-warn`,
`post:edit:design-quality-check`, `post:bash:dispatcher`, `post:session-activity-tracker`,
`post:ecc-metrics-bridge`, `post:ecc-context-monitor`, `post:observe`, `post:skill:track`.

Le quality gate lance de vrais binaires sur les fichiers modifiés : `ruff`, `gofmt`,
`prettier`/`biome`, `tsc --noEmit`. C'est de l'exécution locale d'outillage, pas du code amont.

### Stop / SessionStart / SessionEnd / PreCompact

`stop:format-typecheck` (formate et typecheck en lot, timeout 300 s),
`stop:check-console-log`, `stop:session-end`, `stop:evaluate-session`, `stop:cost-tracker`,
`stop:desktop-notify`, `stop:plan-canvas-pending`, `session:start`,
`session-start:plan-canvas-sessions`, `pre:compact`, `session:end:marker`.

## 2. Sorties réseau — verdict

**Aucun hook n'envoie de donnée vers un tiers.** Recherche exhaustive de `fetch(`, `axios`,
`http.request`, `https.request`, `curl`, `net.`, `dgram`, `WebSocket` dans `scripts/hooks/`
et `scripts/lib/` :

| Trouvaille | Nature | Risque |
|---|---|---|
| `plan-canvas-pending.js` → `http://127.0.0.1:<port>/api/await` | **loopback** uniquement, serveur local de la commande `/plan-canvas` | nul |
| `mcp-health-check.js` → `client.request(url)` | ping GET vers **les serveurs MCP déjà configurés par toi** — aucune URL en dur | à surveiller si un MCP distant est ajouté |
| `scripts/lib/compute-sponsor.js` → `https://compute.itomarkets.com` | chaîne d'affichage d'un bandeau sponsor. Requis uniquement par `scripts/setup.js`, `welcome.js`, `install-*.js` — **jamais par un hook** | nul en usage plugin |
| `scripts/lib/plan-canvas/ui.js` → CDN jsdelivr (mermaid) | chargé par le **navigateur** si tu ouvres `/plan-canvas` | nul tant que la commande n'est pas utilisée |
| `insaits-security-monitor.py` | moniteur de sécurité tiers, 100 % local, **non câblé dans `hooks.json`**, opt-in via `ECC_ENABLE_INSAITS=1` | inactif |

Binaires externes lancés : `osascript` (notification macOS), `git`, `which`, `taskkill`,
`gofmt`, `ruff`. Rien d'anormal.

## 3. Écritures disque — point de vigilance réel

C'est ici que se situe le vrai enjeu, pas dans le réseau. Plusieurs hooks lisent
`transcript_path`, c'est-à-dire **le contenu intégral de la conversation** :

`evaluate-session.js`, `session-end.js`, `cost-tracker.js`, `pre-compact.js`,
`suggest-compact.js`, `gateguard-fact-force.js`.

Ils en dérivent des artefacts persistés sous `~/.claude/` (par ex. `~/.claude/metrics/costs.jsonl`,
et un chemin `learned_skills_path` configurable). Tout reste **sur la machine**, mais des
extraits de session sont écrits hors du projet et survivent à la session.

## 4. Recommandation

Le harnais est propre : pas d'exfiltration, pas de code obscurci hostile, pas de dépendance
réseau cachée. Deux réserves pour **ce** projet :

1. `pre:edit-write:gateguard-fact-force` et `pre:config-protection` **bloquent** des écritures.
   Sur un projet neuf où l'on crée `pyproject.toml`, `ruff.toml` et `.pre-commit-config.yaml`,
   `pre:config-protection` va se déclencher en permanence pour de mauvaises raisons.
2. `stop:format-typecheck` cible JS/TS (Biome/Prettier/tsc). Le projet est en Python : ce hook
   ne rendra aucun service et consommera du temps à chaque réponse.

**Proposition** : profil `minimal`, qui ne laisse actifs que `session:end`, `cost-tracker`,
`evaluate-session`, `session:end:marker`, `plan-canvas-pending` et le pont de métriques.
On garde le cycle de vie et la traçabilité, on écarte les gardes qui se battent contre la
mise en place d'un projet Python neuf.

C'est ta décision.

## 5. Rejouer cette revue

```bash
git clone --depth 1 https://github.com/affaan-m/ecc.git /tmp/ecc-audit
grep -rnE "fetch\(|https?://[a-zA-Z]|axios|http\.request|curl |net\.|dgram|WebSocket" /tmp/ecc-audit/scripts/hooks/ /tmp/ecc-audit/scripts/lib/
python3 -c "import json;d=json.load(open('/tmp/ecc-audit/hooks/hooks.json'));[print(e,'|',x.get('id'),'|',x.get('matcher'),'|',x.get('description','')) for e,l in d['hooks'].items() for x in l]"
```

## 6. Décision appliquée — 2026-08-25

Profil **`minimal`** retenu par William. Configuration effective dans `~/.claude/settings.json` :

```json
"pluginConfigs": { "ecc@ecc": { "options": { "hooks_enabled": true, "hook_profile": "minimal" } } }
```

Le gating est vérifié : `parseProfiles()` (`scripts/lib/hook-flags.js:100`) applique un défaut
`['standard','strict']` quand un hook ne déclare aucun profil. **Un hook sans profil explicite
est donc inactif en `minimal`** — ce qui écarte au passage `pre:bash:auto-tmux-dev` et les
journaux de commandes Bash.

### Liste exacte des hooks actifs sous `minimal`

| Hook | Événement | Effet |
|---|---|---|
| `pre:bash:block-no-verify` | PreToolUse Bash | **Bloque** `git commit --no-verify`. Seul hook bloquant restant, et il va dans notre sens : la CI et `pre-commit` ne doivent pas être contournables |
| `session:start` | SessionStart | Recharge le contexte de la session précédente, détecte le gestionnaire de paquets |
| `post:ecc-metrics-bridge` | PostToolUse | Pont de métriques local |
| `stop:session-end` | Stop | Persiste l'état de session |
| `stop:evaluate-session` | Stop | Extraction de motifs réutilisables |
| `stop:cost-tracker` | Stop | Coût/jetons → `~/.claude/metrics/costs.jsonl` |
| `stop:plan-canvas-pending` | Stop | Draine le retour Plan Canvas (loopback, inactif si la commande n'est pas utilisée) |
| `session:end:marker` | SessionEnd | Marqueur de fin de cycle |

**Neutralisés par ce choix** : `pre:config-protection`, `pre:edit-write:gateguard-fact-force`,
`pre:mcp-health-check`, `pre:write:doc-file-warning`, `pre:observe`, `stop:format-typecheck`,
`stop:check-console-log`, `stop:desktop-notify`, `post:quality-gate`, `post:edit:*`,
`post:bash:*`, `session-start:plan-canvas-sessions`.

Réserve maintenue : trois des hooks actifs (`session-end`, `evaluate-session`, `cost-tracker`)
lisent le transcript intégral et persistent des dérivés sous `~/.claude/`. C'est local, mais
c'est hors du projet et ça survit à la session.

Pour tout couper en urgence :

```bash
ECC_HOOKS_ENABLED=0 claude
```
