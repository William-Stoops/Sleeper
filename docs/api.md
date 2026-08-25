# API du site cible — reconnaissance et exploitation

> Relevé le 2026-08-25 sur `encheres-domaine.gouv.fr`.
> À rejouer avec `tools/discover_api.py` dès qu'un run échoue en `SchemaAmontError`.

## 1. Verdict

**L'API est exploitable en HTTP direct, sans navigateur pour le run lui-même.**

Le site est une application monopage. Contrairement à ce que laissait supposer
le segment `hermes` des anciennes URL, le backend n'est pas un service maison :
c'est un **Magento 2 exposé en GraphQL**. Toutes les données métier transitent
par une passerelle unique.

Une seule réserve, et elle est structurante : **le site est protégé par un
pare-feu applicatif UBIKA doublé d'un CAPTCHA ALTCHA**. Voir §5.

## 2. Passerelle

```
GET https://encheres-domaine.gouv.fr/gateway/magento/graphql/
    ?query=<texte de l'opération>
    &variables=<JSON>
    &operationName=<nom>
```

Réponses en `application/json`, enveloppe GraphQL standard (`data` / `errors`).
Aucune authentification n'est nécessaire pour les données publiques : la mise à
prix, l'enchère en cours et la mention « réservé aux professionnels » sont
toutes accessibles sans compte.

## 3. Opérations utilisées

Les textes exacts sont figés dans [`src/sleeper/api/operations.py`](../src/sleeper/api/operations.py)
et verrouillés par [`tests/api/test_operations.py`](../tests/api/test_operations.py).

### `getAuctions` — liste des ventes

| Variable | Type | Valeur employée |
|---|---|---|
| `currentPage` | `Int` | 1..n |
| `pageSize` | `Int` | 8 |
| `sort` | `AuctionSortsInput` | `{"end_date": "ASC"}` |
| `filter` | `AuctionFiltersInput` | `{"auction_auto_status": {"in": ["2","3"]}}` |

Réponse : `data.auctionsList.{items[], page_info.total_pages, total_count}`.

Champs d'un item exploités :

| Champ | Type | Remarque |
|---|---|---|
| `dnid_auction_id` | `Int` | identifiant de vente, celui de l'URL `/vente/{id}` |
| `auction_auto_status` | `Int` | **2 = à venir, 3 = en cours** |
| `name`, `description` | `String` | intitulé et libellé libre |
| `start_date`, `end_date` | ISO 8601 | horodatages aware, UTC |
| `sales_inspector_label` | `String` | direction régionale (« LILLE », « LA REUNION ») |
| `auction_number_of_lots` | `Int` | volumétrie annoncée |
| `categories[].name` | `String` | filtre « Véhicules » |
| `professional_only` | **`String`** `"0"`/`"1"` | ⚠️ voir §6 |
| `location` | `String` | **toujours `null` en pratique** — inutilisable |

### `getAuctionLots` — lots d'une vente

| Variable | Type | Valeur employée |
|---|---|---|
| `currentPage` | `Int` | 1..n |
| `pageSize` | `Int` | 8 |
| `sort` | `ProductAttributeSortInput` | `{"lot_number": "ASC"}` |
| `filter` | `ProductAttributeFilterInput` | `{"auction": {"eq": "467"}}` |

Réponse : `data.products.{items[], page_info.total_pages, total_count}`.

**C'est la requête la plus rentable du projet** : elle porte à elle seule les
trois informations décisives.

| Champ | Type | Correspondance dans la sortie |
|---|---|---|
| `id` | `Int` | `lots[].id` |
| `url_key` | `String` | construit `lots[].url` → `/lot/{url_key}.html` |
| `lot_number` | `Int` | `lots[].numero` |
| `professional_only` | **`Int`** `0`/`1` | **`reserve_aux_professionnels`** |
| `price_auction` | `Float` | `mise_a_prix` |
| `last_bid` | `Float\|null` | `enchere_en_cours` |
| `reserve_price` | `Float\|null` | prix de réserve, non publié dans la sortie |
| `dropoff_location.{city,postcode}` | `String` | **`lieu_retrait`, `code_postal`** |
| `short_description.html` | HTML | `description_integrale` (balises retirées) |
| `lot_status_label` | `String` | « Vente en cours », « Adjugé »… |
| `end_date` | ISO 8601 | clôture du lot |
| `sales_inspector_data.cav_name` | `String` | direction régionale |

### `getProductPageMain` — fiche détaillée d'un lot

Variable unique : `{"urlKey": "daciadustersecteurest-1"}`.

Apporte `custom_attributes[]`, seule source des caractéristiques du véhicule.
Chaque attribut a la forme :

```json
{
  "attribute_metadata": { "code": "vehicle_mileage", "label": "Kilométrage", "data_type": "FLOAT" },
  "entered_attribute_value": { "value": "110430.000000" },
  "selected_attribute_options": { "attribute_option": [ { "label": "Gazole" } ] }
}
```

La valeur est **soit** dans `entered_attribute_value.value` (saisie libre),
**soit** dans `selected_attribute_options.attribute_option[].label` (liste). Les
deux cas sont traités par `mapping._valeur_attribut`.

Attributs exploités :

| Code | Libellé source | Usage |
|---|---|---|
| `vehicle_brand` / `vehicle_model` | Marque / Modèle | `marque`, `modele` |
| `vehicle_mileage` | Kilométrage | `kilometrage` + règle `kilometrage_inconnu` |
| `vehicle_has_a_key` | Présence d'au moins une clé | `cles` + règle `sans_cle` |
| `registration_certificate` | Certificat d'immatriculation | `carte_grise` + règle associée |
| `technical_control` | Contrôle technique | `controle_technique` |
| `vehicle_energy_type` | Énergie / carburant | `energie` |
| `gearbox_type` | Type de boîte | `boite` |
| `body_type` | Type de carrosserie | (non publié) |
| `kind` | Genre (rubrique J.1) | `VP`, `CTTE`… → règle `genre_hors_cible` |
| `date_first_registration` | 1ʳᵉ mise en circulation | `premiere_mise_en_circulation` |
| `vhu_declared` | VHU déclaré | règle `epave_ou_pieces` |
| `not_conforme` | Non conforme | signal |
| `registrable_again` | Immatriculable à nouveau | règle `non_roulant` |
| `counter_change` | Compteur modifié | signal |
| `administrative_pound` | Fourrière administrative | signal |
| `tax_class_id` | TVA | `tva_recuperable` |

**Attributs délibérément écartés** (`domain/codes.ATTRIBUTS_SENSIBLES`) :
`biciban` (IBAN du compte de l'État), `contact_dropoff_location_id`,
`bid_winner_user`, `id_remitting_entity`. Ils portent des données bancaires ou
personnelles et ne servent à aucune décision d'achat.

### Opérations relevées mais inutilisées

`getAuctionHeaderInfos`, `getProductPageSide`, `getCavList`, `getCategories`,
`storeConfig`, `getLocale`, `ResolveURL`. Les deux premières sont figées dans
`operations.py` parce qu'elles seront utiles si le contrat de `getAuctionLots`
se dégrade ; les autres n'ont aucune valeur métier.

## 4. Champs absents de la source

Trois champs du contrat de sortie n'existent nulle part dans l'API publique.
Ils valent `null` — au sens « absent de la source », jamais « on n'a pas su
lire » :

- `nb_encherisseurs` — le nombre d'enchérisseurs n'est pas publié ;
- `frais_acheteur_pct` — les frais figurent au cahier des charges (PDF), pas
  par lot ;
- `version` — déduit du titre par soustraction de la marque et du modèle.

## 5. Protection anti-robot — la contrainte structurante

Le site est derrière un **WAF UBIKA** :

1. Toute première requête reçoit une page de redirection JavaScript
   (`/redirect_<jeton>/…`) et pose un cookie `bot_mitigation_cookie`. Un client
   HTTP nu ne voit que `This website requires JS enabled and cookies`.
2. Le pare-feu **valide la forme des paramètres**. Une requête GraphQL forgée,
   même sémantiquement équivalente, est refusée : `400 — "Bad query params
   length"`.
3. Après quelques requêtes hors gabarit, le site sert un **CAPTCHA ALTCHA**
   (`/.well-known/ubika/captcha/altcha.js`), y compris à un navigateur.

Conséquences architecturales, toutes assumées :

- **Un navigateur réel, et visible, obtient la session**, parce qu'un navigateur
  exécute le JavaScript du site comme le ferait n'importe quel visiteur.
  `api/session.py` isole cette acquisition, la met en cache et la renouvelle.
  Le mode headless est désactivé par défaut : Chromium y annonce
  `HeadlessChrome/151…`, que le pare-feu refuse. Masquer ce jeton aurait été un
  déguisement ; on ouvre donc une vraie fenêtre. Sur serveur sans affichage,
  passer par `xvfb-run`.
- **Les requêtes sont rejouées à l'identique.** `operations.py` reproduit
  au caractère près les textes émis par l'application ; seules les variables
  changent. Un test bloque toute divergence.
- **Le User-Agent annonce les deux** : le navigateur d'origine, dont la session
  est rejouée, et le robot qui s'en sert, avec une adresse de contact. Masquer
  l'un invaliderait la session ; masquer l'autre nous rendrait injoignables.
- **Aucun CAPTCHA n'est résolu.** Une page ALTCHA fait lever
  `ProtectionAntiRobotError`, **sans aucune reprise**, et le run s'arrête avec
  le code de sortie `3`. Réessayer reviendrait à chercher à contourner.
- **Une session expirée n'est pas un CAPTCHA.** Quand le site resert son
  challenge JavaScript d'entrée (`/redirect_<jeton>/…`), `client.py` renouvelle
  la session **une fois** et rejoue la requête. Si le challenge persiste malgré
  une session neuve, c'est que la protection a changé : le run échoue avec un
  message qui le dit.

### Politesse

`robots.txt` n'est pas servi : l'URL renvoie la coquille de l'application. Il
n'existe donc aucune directive d'exclusion à respecter — ni aucune autorisation
explicite. En l'absence de règle publiée, la configuration livrée applique une
cadence délibérément basse : **une exécution par jour**, `1,5 s` entre les
requêtes, concurrence `2`, cache local pour ne jamais retélécharger une fiche
inchangée. Les CGU et CGV sont publiées en PDF sous
`/admin/media/documents/{cgu,cgv}.pdf` et ne sont accessibles qu'avec une
session de navigateur ; **elles sont à relire avant tout passage en production
soutenu**.

## 6. Optimisation identifiée, non encore implémentée

**Une vente « Véhicules » ne contient pas que des véhicules.** La vente 478
annonce 609 lots répartis sur sept catégories : véhicules, matériels
professionnels, bijoux, high-tech, mobilier, matières, sports et loisirs.

Or `getAuctionLots` **ne renvoie aucune catégorie par lot**. Le seul
discriminant disponible est la présence d'attributs véhicule dans la fiche
détaillée, ce qui coûte une requête par lot. C'est ce que fait la règle
`hors_categorie_vehicule` : elle donne au moins un motif exact, au lieu de
laisser ces lots tomber sur « kilométrage inconnu ».

Le gain réel serait de filtrer **côté API**. Le filtre est passé en *variable*,
pas dans le texte de la requête : `ProductAttributeFilterInput` accepte très
probablement une contrainte de catégorie, sans sortir du gabarit accepté par le
pare-feu. Il faut la relever, pas la deviner :

```bash
uv run --extra discovery python tools/discover_api.py --out var/discovery
```

Le script visite désormais `/categorie/vehicules`, ce qui capture la requête
que l'application émet pour une catégorie. Reporter ensuite la forme exacte du
filtre dans `pipeline._lots_de_vente`.

## 7. Pièges relevés, à ne pas réintroduire

1. **`professional_only` change de type selon le niveau.** `String` `"0"`/`"1"`
   sur une vente, `Int` `0`/`1` sur un lot. Absorbé une fois pour toutes par
   `domain/codes.vers_booleen`.
2. **La mention « pro » d'une vente ne prédit pas celle de ses lots.** La vente
   467 est `professional_only = "0"` alors que **tous** ses lots véhicules sont
   `professional_only = 1`. Seul le niveau lot fait foi.
3. **Le texte libre ment.** Une description relevée porte
   « Lot réservé aux **porfessionnels** ». Aucune règle ne doit se fonder sur la
   détection textuelle de cette mention : l'attribut structuré est la seule
   source.
4. **`location` est toujours `null`**, au niveau vente comme au niveau lot. Le
   lieu de retrait ne s'obtient que par `dropoff_location`.
5. **`pageSize` n'est pas libre.** Au-delà de la valeur employée par
   l'application (8), la requête sort du gabarit accepté par le pare-feu.

## 8. Rejouer la reconnaissance

```bash
uv sync --extra discovery
uv run playwright install chromium
uv run --extra discovery python tools/discover_api.py --out var/discovery
```

Le script ouvre Chromium, intercepte **toutes** les réponses JSON
(`page.on("response")`), et écrit dans `--out` :

| Fichier | Contenu |
|---|---|
| `captures.json` | une ligne par réponse : URL, statut, forme du payload |
| `bodies/*.json` | les charges utiles complètes |
| `ventes.html`, `vente.html`, `lot.html` | le DOM rendu, pour comparaison |
| `cookies.json` | la session obtenue |

Ajouter `--headed` pour observer le navigateur, `--vente-id 467` pour cibler une
vente précise.

### Mettre à jour les opérations figées

Si une opération a changé, extraire le nouveau texte de `captures.json`,
remplacer la constante correspondante dans `operations.py`, régénérer
`tests/fixtures/api/operations_reference.json`, puis **relancer
`tools/verifier_fixtures.py`** avant de versionner : les captures fraîches
contiennent des données personnelles.

## 9. Versions du contrat de sortie

| Version | Date | Changement |
|---|---|---|
| `1.0` | 2026-08-25 | Contrat initial. Schéma : [`schemas/sortie-1.0.json`](../schemas/sortie-1.0.json) |
