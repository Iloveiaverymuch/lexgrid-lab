# Démo live — 15 minutes (partage d'écran)

Statut : ACTIF · Mis à jour : 2026-11-19 · Prochaine action : vérifier les étapes 5, 8 et 9 en conditions réelles avant la démo

Ce document suit l'interface pas à pas. Pour chaque étape : **ce qu'on fait**, **ce qu'on voit** (résultats
constatés lors du test du 19/11/2026 sur le vrai système), **la conclusion** à en tirer. Les libellés de
l'interface sont en anglais et sont cités tels qu'ils apparaissent à l'écran.
Tous les chiffres viennent de [FINDINGS](../evals/FINDINGS.md) ou de l'écran.

## Avant de partager l'écran (5 min)

```bash
cd ~/Documents/Work/AI/"AI Formation"/lexgrid-lab
docker compose -f infra/docker-compose.yml up -d --wait
export LEXGRID_DB=postgresql+psycopg://lexgrid:lexgrid@localhost:5432/lexgrid
LEXGRID_API_KEYS="dev-fr:FR;dev-all:EU,FR,DE" uv run lexgrid serve
```
1. Ouvrir http://127.0.0.1:8000/, saisir la clé `dev-all`, cliquer **Connect** → en haut à droite : **Can search EU FR DE**.
2. **Préchauffer les modèles** : lancer une recherche quelconque en **Hybrid + rerank** (la première prend 10 à 20 s).
3. Onglets prêts : la console, le README sur GitHub, [ADR-001](adr/ADR-001-open-source-embeddings-and-reranker.md).

## Le fil conducteur
Un moteur de recherche juridique multi-pays dont chaque résultat est traçable, chaque version d'index est
évaluée avant mise en production, et dont les faiblesses sont mesurées et connues.

---

## Étape 1 — Recherche par numéro d'article (2 min)

**Faire** : onglet **Search** → exemple **Article number** (remplit `article L. 221-18 code de la consommation`, FR seul, classement **Hybrid**).

**On voit** :
- Rang 1 : **C. conso art. L221-18**, « in force 2016-07-01 », étiquette **you named it**.
- Son score (0,0267) est **inférieur** à celui du rang 2 (L221-21, 0,0297).
- Le rang 2, L221-21, cite « l'article L. 221-18 » dans son propre texte.
- Le fil d'Ariane (Chapitre › Section 6 : Droit de rétractation…) au-dessus de chaque titre.

**Conclusion** : la référence tapée par l'utilisateur (« L. 221-18 ») est normalisée vers l'identifiant indexé
(« L221-18 ») et l'article nommé passe en tête. Sans cette règle, l'article qui *cite* L221-18 sortait premier
(références exactes : 4/6 → 6/6 au rang 1). Le découpage par article garde la hiérarchie du code.

## Étape 2 — Traçabilité d'un résultat (1 min)

**Faire** : sur le rang 1, cliquer **Trace source**.

**On voit** : la chaîne *Search result → Chunk → Document version → Raw capture → Published source* :
parseur `legifrance_html 1.0.0`, empreinte SHA-256 du fichier capturé, date de collecte, URL Légifrance d'origine.

**Conclusion** : tout résultat, donc toute citation, remonte jusqu'aux octets téléchargés et au code qui les a lus.

## Étape 3 — Comparer les quatre classements (2 min)

**Faire** : fermer le panneau (Échap) → **Compare all four**, FR seul → saisir
`combien de jours a le consommateur pour se rétracter après un achat en ligne ?` → **Search** →
survoler **C. conso:L221-18** dans une colonne.

**On voit** (L221-18 est la bonne réponse) :

| Colonne | Position de L221-18 |
|---|---|
| Keywords (BM25) | absent du top 10 |
| Meaning (dense) | **1** |
| Hybrid (RRF) | 5 |
| Hybrid + rerank | **1** |

**Conclusion** : la question n'emploie aucun terme juridique de l'article ; la recherche par mots-clés échoue,
la recherche sémantique trouve. La fusion à poids égaux (RRF) dilue la bonne réponse parce qu'une des deux
listes ne la contient pas ; le reranker la remet en tête. C'est exactement l'écart mesuré par l'évaluation.

> En mode Compare, les quatre classements sont calculés l'un après l'autre : chaque temps affiché est le sien.

## Étape 4 — Question en français, droit allemand ⚠ faiblesse identifiée (2 min)

**Faire** : exemple **French question, German law** (remplit `délai de remboursement après rétractation en droit allemand`, DE seul), en **Compare all four** → survoler **BGB:357** puis **BGB:357b**.

**On voit** (bonne réponse : BGB § 357, règle générale de remboursement) :

| Colonne | Rang 1 | Position de § 357 |
|---|---|---|
| Keywords (BM25) | § 192 (délais en général) : bruit | absent du top 10 |
| Meaning (dense) | § 357b (services financiers) | 2 |
| Hybrid (RRF) | **§ 591b (bail rural)** | 5 |
| Hybrid + rerank | § 357b | 7 |

**Conclusion** : la recherche sémantique trouve la bonne famille d'articles (§§ 355–357) d'une langue à
l'autre. Deux faiblesses se cumulent :
1. **Fusion insensible à la langue** : les mots-clés français ne produisent que du bruit sur un texte allemand,
   et la fusion à poids égaux le promeut (bail rural au rang 1). Mesuré : 0,59 en hybride contre 0,76 en dense
   sur les questions « autre langue » (n = 6).
2. **Articles quasi identiques** : § 357b (services financiers) passe devant § 357 (règle générale), et le
   reranker est moins bon d'une langue à l'autre (§ 357 recule de 2 à 7).

## Étape 5 — Trois juridictions : trouvé, corrigé, mesuré (2 min)

**Faire** : exemple **Three countries** (`exceptions to the right of withdrawal for personalised goods`, EU + FR + DE), classement **Hybrid + rerank** seul.

**Avant correction** (constaté le 19/11 au matin) : rangs 1 à 8 **uniquement EU** (CRD art. 16, 9, 14, 6…) ;
C. conso L221-28 (FR) et BGB § 312g (DE) absents.

**Après correction** (run D4-EVAL-DIVERSIFY-01, même ordre attendu à l'écran, à vérifier en direct) :

| Rang | Article | Juste ? |
|---|---|---|
| 1 | CRD art. 16 — Exceptions from the right of withdrawal | oui |
| 2 | BGB § 997 | **non** (la bonne réponse est § 312g) |
| 3 | C. conso L221-28 | oui |

**Conclusion** :
- **Trouvé** : une question comparative en anglais ne renvoyait que le droit de l'UE, seul texte disponible en
  anglais ; la France et l'Allemagne n'atteignaient même pas le reranker.
- **Corrigé** : quand plusieurs pays sont dans le périmètre, chaque pays est cherché et reclassé séparément,
  puis le meilleur article de chaque pays est placé en tête ; une recherche sur un seul pays est inchangée.
- **Mesuré** : questions « plusieurs pays » 0,696 → 0,783 nDCG@10 (+0,087, IC [−0,00 ; +0,18], n = 6) ;
  tous les autres types strictement identiques. Gain cohérent, pas encore concluant sur 6 questions.
- **Limite restante, visible au rang 2** : pour l'Allemagne, le meilleur article trouvé depuis une question
  en anglais est faux (§ 997). C'est la faiblesse inter-langues de l'étape 4 ; la diversification la rend
  visible au lieu de la cacher (backlog n° 9).

## Étape 6 — Évaluation (2 min)

**Faire** : onglet **Evaluation** → run **D2-EVAL-BGEM3-01 (bge-m3)**.

**On voit** :

| Classement | nDCG@10 [IC 95 %] | p50 / p95 |
|---|---|---|
| Keywords (BM25) | 0,557 [0,41 ; 0,71] | 106 / 370 ms |
| Meaning (dense) | 0,759 [0,66 ; 0,86] | 91 / 663 ms |
| Hybrid (RRF) | 0,733 [0,63 ; 0,84] | 65 / 170 ms |
| Hybrid + rerank | **0,843 [0,76 ; 0,92]** | 3 032 / 4 893 ms |

Après la correction de l'étape 5, choisir le run **D4-EVAL-DIVERSIFY-01** : Hybrid + rerank **0,860 [0,79 ; 0,93]**.

Tableau « par type de question » : numéro d'article 0,99 (mots-clés) contre 0,56 (sémantique) ; autre langue
0,16 contre 0,76 ; plusieurs pays : 0,70 au mieux.

**Conclusion** : chaque faiblesse vue en direct (étapes 3 à 5) se lit dans ce tableau ; c'est l'évaluation qui
a guidé le diagnostic. Les intervalles sont larges (30 questions, étiquettes en attente de relecture) : on
compare des ordres de grandeur, pas des décimales. Le reranker apporte le plus de qualité et coûte le plus de
latence.

## Étape 7 — Mise en production contrôlée (2 min)

**Faire** : onglet **Indexes** (pas besoin de relancer : les builds du 19/11 au matin sont affichés).

**On voit**, pour chaque juridiction :
- un index **promoted** (en production) ;
- l'index de la veille **retired** ;
- un index **rejected** avec moins de chunks (DE 2 571 → 1 772) et un identifiant de run `GATE-…`.

**Conclusion** : chaque nouvel index est évalué sur le jeu de questions contre l'index en production avant
bascule. Une reconstruction à l'identique est promue (écart +0,000) ; un index amputé de 30 % de ses chunks
est refusé (nDCG@10 −0,159, IC [−0,271 ; −0,063]) et l'alias de production ne bouge pas. Un retour arrière est
une seule bascule d'alias atomique.

## Étape 8 — Périmètre par clé d'API (1 min) — à vérifier avant la démo

**Faire** : saisir la clé `dev-fr` → **Connect** → onglet **Search** → exemple **Outside your scope**.

**On doit voir** : « Refused by the server — not entitled to: DE ». En haut à droite : **Can search FR** seulement.

**Conclusion** : le périmètre vient de la clé, jamais de la requête ; on peut le restreindre, pas l'élargir.
Mesuré : 0 fuite sur 4 516 résultats, 120/120 tentatives d'élargissement refusées (D3-LEAK-01).

## Étape 9 — Réponse citée et abstention (1 min) — à vérifier avant la démo

**Faire** : reconnecter avec `dev-all` → onglet **Ask** → exemple **Withdrawal period**, puis **Not in the corpus**.

**On doit voir** :
1. Des extraits d'articles, chacun avec sa citation en marge, puis l'avertissement « not legal advice ».
2. Pour la question sur la période d'essai : **Not answered**, avec le score obtenu et le seuil (0,15).

**Conclusion** : la réponse cite ses sources mot pour mot (extraction, sans modèle de langage). Quand les
sources ne suffisent pas, le système le dit au lieu de citer un mauvais article : 10/10 questions hors corpus
refusées, 27/30 questions répondables traitées (D3-ABSTAIN-01, seulement 10 questions hors corpus).

## Étape 10 — Choix et limites (1 min)

**Faire** : ouvrir [ADR-001](adr/ADR-001-open-source-embeddings-and-reranker.md).

**Conclusion** : Bedrock (Titan, Rerank) était bloqué sur le plan gratuit AWS ; modèles open source locaux
(bge-m3, bge-reranker-v2-m3), décision documentée et réversible sans changer le code.

---

## Faiblesses connues (à assumer, pas à cacher)

| Faiblesse | Où elle se voit | Mesure | Piste |
|---|---|---|---|
| Fusion insensible à la langue | Étape 4 : bail rural au rang 1 | Autre langue : 0,59 (hybride) vs 0,76 (dense), n = 6 | Pondérer les mots-clés selon la langue de la question et du droit visé |
| Articles quasi identiques | Étape 4 : § 357b devant § 357 | — | Jeu de questions « pièges » (hard set) dans l'évaluation |
| Mauvais article national promu par la diversification | Étape 5 : BGB § 997 au rang 2 | q28, q29 (D4-CMP-01) | Seuil de crédibilité sur le score du reranker avant d'accorder une place ; fusion sensible à la langue |
| Latence du reranker | Étapes 5 et 6 | p50 3 s, p95 4,9 s | Reranker moins de candidats ou un modèle plus léger, mesurer la perte |
| Dates de validité | Champ « In force on » | Version actuelle seulement pour la France | Import LEGI en masse (versions historiques) |
| Taille de l'évaluation | Onglet Evaluation | 30 questions, étiquettes à relire | Jeu relu et élargi |

## Requêtes de réserve

| Requête | Réglages | Résultat attendu |
|---|---|---|
| `within how many hours must a controller notify a personal data breach to the authority?` | EU, Hybrid + rerank | RGPD art. 33 (72 heures) |
| `Art. 17 DSGVO Recht auf Löschung` | EU, Hybrid | RGPD art. 17 en tête (référence en allemand) |
| `Muss ein Online-Shop eine Schaltfläche zum Widerrufen anbieten?` | DE, Hybrid + rerank | BGB § 356a (fonction de rétractation électronique) |
| `is a trader allowed to charge a surcharge for paying by credit card?` | EU, Hybrid + rerank | CRD art. 19 |
| `informations précontractuelles à fournir avant un contrat à distance` puis **In force on** = 01/01/2025 | FR | L221-5 disparaît : seule la version en vigueur depuis le 19/06/2026 est indexée |

## Si quelque chose casse

| Symptôme | Action |
|---|---|
| Première recherche très lente | Normal (chargement des modèles) ; d'où le préchauffage |
| « Cannot reach the API » | Vérifier que `lexgrid serve` tourne dans l'onglet 1 |
| Erreur de connexion à OpenSearch ou Postgres | `docker compose -f infra/docker-compose.yml up -d --wait` |
| Interface inutilisable | Même API en ligne de commande : `curl -s localhost:8000/search -H 'Content-Type: application/json' -H 'X-API-Key: dev-all' -d '{"query":"article L. 221-18","k":3}'` |
