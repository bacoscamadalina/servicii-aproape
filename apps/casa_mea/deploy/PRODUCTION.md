# ServiciiAproape — instalare completă de producție (separată de preview)

## Ce este gata și ce NU face instalarea

`../docker-compose.production.yml` pornește PostgreSQL 17, aplicația Django prin Gunicorn,
un pas unic de migrare/verificare și Caddy pentru HTTPS. Baza și portofoliile au
volume persistente; numai Caddy publică porturile 80/443. Nu se folosește `runserver`.

**Fișierul Compose și imaginea NU conțin baza de date.** Pentru aceleași date trebuie
transferat separat un backup privat și restaurat explicit. Acesta include conturi,
hashuri de parole, cereri, emailuri, audituri și fișiere private: nu îl publica în
GitHub, într-un registry, într-un bucket public sau într-un link de download.
Transferă-l numai pe un server propriu/de încredere, prin SSH/SFTP. Hashurile detectează
coruperea, nu dovedesc cine a creat arhiva; nu restaura backupuri de la necunoscuți.

**Limita actuală de publicare:** cele 42 de cataloage din baza locală sunt
`internal_preview`, fără aprobări publice. Copierea păstrează firmele și istoricul,
dar producția (`DEBUG=False`) nu le afișează vizitatorilor. Instalarea NU inventează
aprobări, NU schimbă vizibilitatea și NU ocolește verificările. Publicarea necesită
separat revizia reală și activarea auditată a fiecărui catalog prin mecanismul
existent. Dovezile directe și profilurile preview au, de asemenea, propriile limite.
Prin urmare, „oricine vede exact tot ce văd local” nu este încă un rezultat al acestui pas.

## 1. Backup privat pe calculatorul cu baza actuală

Oprește scrierile pe durata exportului: serverul local (`Ctrl+C` în terminalul lui),
importurile și alte procese care editează baza sau portofoliile. `pg_dump` oferă un
snapshot SQL consistent, dar baza și fișierele nu au o tranzacție comună. Flagul
`--writes-paused` este confirmarea operatorului, nu oprește procese automat.

Din proiect, cu Python și Docker disponibile:

```bash
cd /home/madalina/Documents/ChatGPT/CasaMea/apps/casa_mea
python deploy/backup_local.py deploy/backups/current --writes-paused
```

Comanda citește containerul `casamea-postgres-pilot` fără a afișa parola și creează
un director nou cu permisiuni 700 și fișiere 600: `database.dump`,
`private_media.tar.gz`, `manifest.json`. Directorul existent nu este suprascris.
Pentru un export ulterior alege alt nume. Manifestul apare numai după export complet
și fixează SHA-256/dimensiunea fișierelor și artefactele sursă din imagine.
Un export incomplet, fără manifest, nu poate fi restaurat. Repornește serverul local
după export. Fișierele brute ONRC/MF nu sunt necesare pentru citirea catalogului;
pentru importuri viitoare trebuie transferate/procurate separat.

Noile exporturi folosesc manifest schema 2 și fixează suplimentar numărul fișierelor
media și volumul lor necomprimat. Copiile schema 1 existente rămân compatibile.
După copierea backupului pe server și apoi periodic, verifică bundle-ul selectat în
`.env` fără restaurare:

```bash
docker compose -f docker-compose.production.yml run --rm verify-backup
```

Serviciul montează backupul read-only, verifică hashurile și artefactele-sursă, parsează
dumpul cu PostgreSQL 17 `pg_restore --list`, respinge membri tar nesiguri și aplică
`CASAMEA_BACKUP_MAX_AGE_HOURS` (implicit 26). Emite JSON agregat și cod nenul la orice
problemă; programează această comandă zilnic în schedulerul gazdei și alertează la cod
nenul. Verificarea nu oprește scrierile și nu creează un backup nou.

**Acest pas pentru baza reală nu a fost executat în validarea implementării.**
Testele de transfer folosesc exclusiv date sintetice.

## 2. Configurare pe server

Sunt necesare Docker Engine cu pluginul Compose, un domeniu cu DNS către server și
porturile 80/443 disponibile. Copiază codul aplicației și backupul privat. Nu copia
direct fișierele unui volum PostgreSQL aflat în funcțiune.

Din directorul `apps/casa_mea` de pe server:

```bash
cp .env.example .env
chmod 600 .env
python -c "import secrets; print(secrets.token_urlsafe(64))"
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Editează `.env`: domeniul real (fără `https://` sau port), două valori aleatoare
DISTINCTE pentru `CASAMEA_SECRET_KEY` și `CASAMEA_POSTGRES_PASSWORD`, calea directorului
de backup, credențialele SMTP STARTTLS și identitatea juridică publică a operatorului:
`CASAMEA_LEGAL_OPERATOR_NAME`, `CASAMEA_LEGAL_OPERATOR_ADDRESS`, o adresă validă
`CASAMEA_PRIVACY_EMAIL` și contactul pentru planul Partener în
`CASAMEA_COMMERCIAL_EMAIL`. Nu trimite secretele în chat. Aceste date de contact nu
sunt secrete: verifică după pornire că apar corect în subsol, pe pagina
`/confidentialitate/` și în acțiunea comercială de pe `/abonament/`.

Stabilește împreună cu persoana responsabilă de conformitate și cele patru durate de
retenție din `.env`: revendicări neconfirmate/înlocuite, revendicări respinse și
sesizări publice închise, respectiv cereri închise privind datele personale. Valorile exemplu sunt un punct de pornire tehnic, nu
consiliere juridică. Producția refuză durate lipsă, prea mici sau mai mari de zece ani.
Pagina de confidențialitate afișează exact valorile active ale mediului.
Producția refuză acum configurația SMTP goală sau invalidă; nu folosește backendul de
consolă și nu tipărește tokenuri. Nu promova fluxurile de revendicare înaintea unui
test real de livrare.

Cheia secretă nouă invalidează sesiunile și unele linkuri de resetare vechi;
utilizatorii trebuie să se autentifice din nou. Hashurile parolelor sunt păstrate.
Cheia protejează și pseudonimele limitelor persistente de autentificare/resetare;
rotirea ei pornește ferestre noi, fără a dezvălui adresele vechi stocate.
Autentificările furnizorilor și administratorilor au bugete separate, persistente în
PostgreSQL: maximum cinci încercări pentru același identificator în 15 minute, comune
tuturor workerelor Gunicorn și șterse după autentificarea reușită. Acest control nu
înlocuiește limitarea traficului și monitorizarea la marginea infrastructurii publice.
Rotește credențialele de test/de administrator înainte de acces public. Istoricul
privat rămâne în bază și poate fi accesat numai prin permisiunile aplicației.

## 3. Restaurare explicită, apoi pornire

```bash
docker compose -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.production.yml build
docker compose -f docker-compose.production.yml run --rm restore
docker compose -f docker-compose.production.yml up -d
docker compose -f docker-compose.production.yml ps
docker compose -f docker-compose.production.yml logs --tail=50 bootstrap
docker compose -f docker-compose.production.yml exec web python manage.py verify_cloud_catalogue
```

Nu rula `migrate` înaintea restaurării inițiale: ținta trebuie să fie goală.
Restaurarea verifică hashurile și versiunile surselor, refuză o bază/volume populate,
folosește `pg_restore --single-transaction --exit-on-error` și păstrează fișierele
într-un volum privat, fără rută generică `/media/`. Numai după finalizarea ambelor
copii se scrie markerul `.restore-complete`. Bootstrap cere markerul, aplică migrațiile,
auditează fiecare catalog județean și execută verificările Django pentru producție.
Un restart nu reimportă și nu șterge date.

## 4. Auditul și aplicarea retenției

Comanda este read-only în mod implicit și afișează numai numere agregate, fără nume,
adrese, texte libere sau identificatori de înregistrări:

```bash
docker compose -f docker-compose.production.yml exec web python manage.py apply_data_retention
```

Verifică raportul, salvează-l în registrul operațional și investighează separat orice
`stale_claims_in_review`; aceste cereri nu sunt modificate automat. Numai după aprobarea
duratelor și a raportului rulează aplicarea explicită:

```bash
docker compose -f docker-compose.production.yml exec web python manage.py apply_data_retention --apply --acknowledgement APPLY_CONFIGURED_DATA_RETENTION
```

Aplicarea anonimizează datele de contact din revendicările neconfirmate/înlocuite sau
respinse, conținutul liber și notele interne din sesizările închise și datele de contact/notele cererilor
privind datele după perioada configurată, păstrând starea și dovada deciziei.
Pentru solicitările de client finalizate și expirate, elimină și legătura cu contul;
într-o cerere comparată, invalidează accesul părinte numai după ce toate copiile
trimise firmelor au trecut prin retenție. Numărul de proiecte și stările rămân în
agregatele fără identitate.
Nu atinge revendicările aprobate, conturile, profilurile ori cererile în analiză. Șterge
contoarele tehnice mai vechi de 24 de ore și interacțiunile pseudonimizate cu profilurile
care au ieșit din fereastra maximă de raportare de 90 de zile; este idempotentă. Pentru automatizare,
programează această comandă în infrastructura privată numai după prima rulare manuală;
nu o adăuga în bootstrap sau în pornirea serverului.

După aplicare, și periodic, verifică separat că rândurile deja anonimizate nu mai
păstrează texte, conversații, oferte nescrubate ori legături de acces. Auditul
verifică și că revendicările/înscrierile anonimizate nu mai au date de contact,
hashuri de acreditare sau documente justificative:

```bash
docker compose -f docker-compose.production.yml exec web python manage.py audit_retention_integrity
```

Raportul conține numai numere agregate. Un exit nenul cere investigație; auditul nu
repară date și nu aplică din nou retenția. Sesizările deja anonimizate în versiuni
anterioare, dar cu note interne rămase, apar din nou în auditul read-only al eligibilității;
doar aplicarea confirmată le curăță.

## 5. Cereri privind datele personale

În Django Admin, acordă separat permisiunile `add_datasubjectrequest`,
`view_datasubjectrequest` și `process_data_subject_request` numai persoanelor care
administrează cererile primite la adresa publică de confidențialitate. Înregistrarea
calculează termenul inițial de o lună calendaristică. Procesarea nu permite editarea
liberă a cererii: confirmarea identității, analiza, soluționarea/refuzul motivat și
eventuala prelungire unică sunt tranzacții cu revizie și evenimente protejate.

Prelungirea adaugă două luni la termenul inițial și poate fi înregistrată numai înainte
ca acesta să expire, după comunicarea motivului către persoană. Registrul nu trimite
automat răspunsuri și nu execută automat ștergeri: operatorul trebuie să verifice
sistemele vizate, să comunice prin canalul confirmat și să documenteze doar minimumul
necesar, fără copii de acte sau identificatori inutili.

Pentru o cerere de acces sau portabilitate aflată în analiză după confirmarea identității,
Adminul poate genera un pachet JSON controlat. Pachetul este transmis direct browserului
cu politică `no-store`; aplicația nu îl păstrează în container ori în volumul media.
Evenimentul auditat conține numai amprenta SHA-256. Operatorul trebuie să verifice separat
fișierele binare din portofoliu și orice alt sistem menționat în cerere, apoi să trimită
răspunsul prin canalul adecvat. Migrarea `0025` trebuie aplicată înainte de folosirea
acțiunii; bootstrapul de producție o aplică în fluxul normal de migrare după restaurare.

Mesajul `Catalogue copied, NOT publicly approved` este intenționat pentru baza actuală.
Nu înseamnă că firmele lipsesc din PostgreSQL. Nu seta `CASAMEA_DEBUG=1` pentru a-l
ocoli; configurația cloud îl ignoră deliberat.

După configurarea DNS/HTTPS verifică `/`, `/en/`, căutarea județ–localitate,
`/admin/login/` și o livrare email controlată. Caddy solicită automat certificatul
pentru domeniul configurat. Dacă folosești deja proxy-ul furnizorului cloud, adaptează
doar intrarea HTTPS; aplicația nu trebuie expusă direct cât timp are încredere în
`X-Forwarded-Proto`. Bind-mounturile Caddy/backup folosesc etichetarea `z` pentru
gazde cu SELinux; nu dezactiva SELinux global.

Auditează mai întâi configurația SMTP fără conexiune și fără trimitere:

```bash
docker compose -f docker-compose.production.yml exec web \
  python manage.py verify_smtp_delivery
```

Pentru singura probă reală, folosește o adresă controlată de operator și confirmarea
explicită. Comanda trimite un mesaj sintetic fără cont, firmă, revendicare sau token:

```bash
docker compose -f docker-compose.production.yml exec web \
  python manage.py verify_smtp_delivery \
  --send \
  --recipient operator@domeniul-tau.ro \
  --acknowledgement SEND_SYNTHETIC_SMTP_PROBE
```

Ieșirea JSON nu include destinatarul. Un rezultat valid confirmă acceptarea de către
serverul SMTP, nu livrarea în inbox sau reputația domeniului; verifică separat SPF,
DKIM, DMARC și mesajul primit. Nu folosi adresa unei persoane fără acord.

De pe o altă mașină conectată la internet rulează verificarea HTTP automată, folosind
originea canonică fără cale, query sau port. Nu folosi opțiuni care ignoră certificatul:

```bash
python deploy/smoke_production.py --base-url https://serviciiaproape.ro/
```

Comanda verifică redirecționarea HTTP→HTTPS, ambele limbi, adminul, protecția profilului,
inaccesibilitatea unei căi media private, cookie-ul CSRF și headerele de securitate.
Emite JSON și iese nenul la orice abatere. Un rezultat valid dovedește suprafața HTTP,
nu aprobarea firmelor; rulează separat `audit_production_readiness` pentru județele
comerciale aprobate. Înlocuiește domeniul din exemplu cu domeniul configurat real.

HSTS este activ pentru domeniul configurat. Nu se activează automat politica pentru
toate subdomeniile și înscrierea în lista preload a browserelor; avertismentele Django
W005/W021 sunt omise explicit din acest motiv. Toate celelalte avertismente de
deployment opresc bootstrapul.

Aplicația trimite și o politică CSP strictă, fără `unsafe-inline` sau `unsafe-eval`,
plus o Permissions-Policy care dezactivează camera, microfonul și geolocația. Nu adăuga
scripturi/stiluri inline și nu relaxa politica pentru a remedia un asset lipsă; resursele
publice proprii trebuie colectate prin WhiteNoise. Smoke testul extern verifică aceste
headere și eșuează dacă politica este eliminată sau slăbită.

Înainte de lansare și apoi periodic, rulează auditul separat de healthcheck pentru
aria comercială aprobată. Repetă `--county` numai pentru județele decise explicit:

```bash
docker compose -f docker-compose.production.yml exec web \
  python manage.py audit_production_readiness --county Iași --county Neamț
```

Comanda emite JSON fără firme, utilizatori, rapoarte sau note și iese cu cod nenul dacă
un run nu mai trece auditul, un pointer nu este public, aprobarea exactă a expirat ori a
fost revocată, lanțul privat de sesizări ori registrul cererilor privind datele
personale ori retenția solicitărilor are drift, există migrări neaplicate sau markerul restaurării lipsește.
Folosește rezultatul într-un monitor extern și alertează la exit nenul. Nu adăuga auditul
în liveness sau în bootstrap: operatorii trebuie să poată accesa aplicația pentru
remediere chiar dacă marketplace-ul nu este pregătit.

Pentru diagnosticul agregat separat al registrului de confidențialitate rulează:

```bash
docker compose -f docker-compose.production.yml exec web \
  python manage.py audit_data_subject_requests
```

Ieșirea nu conține nume, e-mailuri, note, actori sau identificatori. Un exit nenul
înseamnă că starea, reviziile, termenele ori lanțul de evenimente trebuie investigate
în Admin; comanda nu repară și nu modifică nimic.

Aplicația scrie în fluxul standard al containerului evenimente JSON cu loggerul
`services.security`. Configurează în platforma cloud alerte după câmpul `event`, nu după
textul tradus:

- `account_login_throttled`: bugetul de autentificare Admin sau furnizor a fost epuizat;
- `provider_password_reset_throttled`: limita trimiterilor de resetare a fost atinsă;
- `provider_claim_creation_throttled`: limita cererilor de revendicare a fost atinsă;
- `provider_claim_delivery_failed`: e-mailul de confirmare nu a putut fi livrat;
- `provider_invitation_delivery_failed`: invitația contului aprobat nu a putut fi livrată.
- `smtp_probe_failed` / `smtp_probe_succeeded`: rezultatul probei sintetice explicite.

Alarmează imediat la eșecurile de livrare și la repetarea evenimentelor de limitare
într-un interval scurt. Evenimentele nu conțin identificatori de cont, destinatari,
parole, tokenuri, URL-uri sau textul excepției. Restricționează totuși accesul la loguri
și stabilește retenția în platforma cloud; aplicația nu poate configura aceste politici
în numele furnizorului de hosting.

## Recuperare, actualizări și limite

- PostgreSQL și fișierele nu pot fi comise atomic împreună. Dacă instalarea media
  eșuează după commitul SQL, markerul lipsește și aplicația nu pornește. Păstrează
  backupul original și volumele eșuate pentru diagnostic; restaurează într-o pereche
  NOUĂ de volume folosind un nume nou de proiect, de exemplu
  `docker compose -f docker-compose.production.yml -p serviciiaproape-recovery run --rm restore`, apoi
  `docker compose -f docker-compose.production.yml -p serviciiaproape-recovery up -d`. Nu porni două proxy-uri pe aceleași
  porturi. Nu șterge volumele originale ca metodă implicită de recuperare.
- Testează periodic restaurarea într-un nume de proiect unic, fără serviciul `proxy`,
  confirmă `verify_cloud_catalogue`, migrările și markerul media, apoi încearcă încă o
  restaurare pentru a confirma refuzul suprascrierii. Numai după succes elimină exact
  proiectul de test și volumele lui. Nu folosi niciodată numele proiectului de producție
  în comanda de curățare și păstrează backupul sursă.
- Nu rula `docker compose -f docker-compose.production.yml down -v`: acel flag șterge volumele persistente.
  `docker compose -f docker-compose.production.yml down` fără `-v` păstrează datele. Un volum nu este un backup.
- Înaintea actualizărilor fă un backup privat al bazei și al volumului media; configurează
  copii periodice criptate în afara serverului și probe de restaurare. Scriptul local
  acceptă `--container` și `--media-root`; nu îl îndrepta spre un director media gol
  în locul volumului real de pe server.
- Pentru un update al codului: `docker compose -f docker-compose.production.yml up -d --build`. Păstrează `.env` și
  volumele; nu rula din nou `restore`. Schimbarea parolei în `.env` NU rotește parola
  deja persistată în PostgreSQL: aceasta necesită o operațiune separată coordonată.
- Validează periodic imaginile de bază și actualizările de securitate. Dependențele
  directe Python sunt fixate; tagurile Docker sunt pe seria Python 3.14, PostgreSQL 17
  și Caddy 2 și se pot actualiza la reconstruire.
- Configurația este pentru un singur server, nu include HA, stocare distribuită sau
  un scheduler/off-host storage automat. Verificatorul este pregătit pentru scheduler,
  dar criptarea, retenția și copierea în afara serverului trebuie configurate în
  platforma aleasă. Nu a fost făcut deployment într-un cloud real.

Referințe: [ordinea de pornire Compose](https://docs.docker.com/compose/how-tos/startup-order/),
[WhiteNoise pentru Django](https://whitenoise.readthedocs.io/en/stable/django.html),
[proxy-ul Caddy și headerele transmise](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).
