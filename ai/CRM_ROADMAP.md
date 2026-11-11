# ServiciiAproape — fluxul complet al lucrării

## Obiectiv și graniță

Extindem marketplace-ul existent într-un spațiu privat de lucru pentru fiecare
furnizor: **client → ofertă → acceptare → lucrare → factură → încasare → garanție**.
Cererea, oferta acceptată și propunerea de vizită există deja. Niciuna dintre
acestea nu este încă o factură fiscală sau o plată. Plata reală a abonamentelor
și a lucrărilor rămâne ultima integrare, conform deciziei proprietarei.

Furnizorul este prestatorul și emitentul eventualei facturi pentru lucrare;
ServiciiAproape oferă software-ul, nu devine vânzătorul lucrării.
Facturile pentru abonamentul platformei constituie un flux contabil separat.
Proprietara a confirmat această separare; implementarea fiscală necesită în continuare
validare contractuală și contabilă înainte de emitere.

## Contracte care nu trebuie încălcate

- Fiecare obiect comercial aparține unui singur `ProviderProfile`; toate citirile
  și mutațiile sunt filtrate după apartenența activă. Un furnizor dintr-o cerere
  trimisă mai multor firme nu poate vedea ofertele, clienții sau lucrările altuia.
- Oferta trimisă este imuabilă. Acceptarea exact unei versiuni valabile creează
  cel mult o lucrare pentru acea cerere, tranzacțional și idempotent. Repetarea
  POST-ului, refresh-ul sau notificarea duplicată nu creează o a doua lucrare.
- `ProviderLead.Status` rămâne indicatorul funnel-ului comercial; starea lucrării,
  programarea, factura, transmiterea RO e-Factura și încasarea sunt stări separate.
  O vizită confirmată nu înseamnă că lucrarea a fost executată.
- Înaintea unui CRM manual, un client introdus de firmă nu devine automat cont
  ServiciiAproape și nu primește acces la proiectele altui furnizor. Asocierea
  cu un cont de client cere verificarea explicită a identității și acordul potrivit.
- Documentele fiscale emise nu se șterg odată cu anonimizarea cererii de ofertă.
  Arhiva fiscală, retenția proiectului, fotografiile și mesajele au politici
  separate; nicio factură emisă nu se editează în loc.
- Notificările prin e-mail conțin numai informația minimă și un link către
  spațiul autorizat; nu includ oferta integrală, adresa lucrării, factura ori
  fotografiile. Trimiterea se face după commit și poate fi reluată idempotent.

## Etape de livrare

### Registrul privat de clienți — bază implementată

Proprietarul firmei poate adăuga, căuta, edita și arhiva contacte proprii în
panoul privat. Sunt obligatorii numele, cel puțin telefonul sau e-mailul și o
confirmare explicită că firma are un motiv legitim pentru administrarea datelor.
Fiecare modificare folosește revizie optimistă și păstrează un eveniment fără
conținut personal. Arhivarea nu șterge fișa și are moment explicit.

O fișă introdusă manual nu creează cont de client, nu trimite e-mail și nu oferă
acces la portal. Datele sunt izolate per furnizor și intră în exportul persoanei
vizate numai la potrivirea exactă a adresei verificate. O fișă activă poate fi
acum asociată explicit unei cereri existente dintr-un selector paginat și
căutabil. Legătura are revizie și jurnal propriu și poate fi eliminată fără a
rescrie datele originale trimise de client. Nu există potrivire, deduplicare,
cont sau e-mail automat; oferta și lucrarea folosesc legătura prin cererea lor
existentă. Dintr-o cerere neasociată, proprietarul poate deschide și un formular
precompletat, poate corecta datele, confirmă folosirea lor și creează fișa împreună
cu asocierea într-o singură tranzacție. Dacă există deja o fișă, directorul activ
rămâne vizibil pentru selecție explicită; sistemul nu presupune identitatea după
nume, e-mail sau telefon. Deduplicarea pe telefon și politica automată de retenție pentru
arhivă trebuie definite înainte de importuri masive.

Solicitarea asociată poate deschide acum formularul existent de ofertă cu
descrierea proiectului precompletată. Acțiunea este numai o pregătire în browser:
nu creează ofertă, nu trimite e-mail și nu schimbă destinatarul din solicitarea
inițială. Prețul, durata și valabilitatea rămân decizii explicite ale firmei, iar
trimiterea trece prin validarea și confirmarea deja existente.

Oferta poate fi acum împărțită în până la patru poziții clare, fiecare cu
descriere, cantitate, unitate și preț unitar. Totalul este calculat din poziții
atât în interfață, cât și autoritar pe server; valoarea transmisă de browser nu
poate înlocui calculul. Clientul vede același deviz în oferta directă și în
comparația dintre firme. Ofertele istorice primesc la migrare o singură poziție
echivalentă, fără pierdere de sumă sau descriere. Pozițiile sunt comerciale și
nu reprezintă încă linii fiscale, TVA ori factură emisă.

### Asistentul de comenzi — început, fără execuție autonomă

Panoul firmei acceptă acum o instrucțiune strictă de tipul „Creează ofertă pentru
dl. Ionescu: montare 3 aparate AC, 7.500 lei”. Un parser local, fără API extern
și fără cost suplimentar, identifică **o singură cerere activă a firmei** și
completează în memorie suma și descrierea în formularul de ofertă. Nu creează
client, nu persistă ciorna, nu trimite oferta și nu trimite e-mail. Proprietarul
completează durata și valabilitatea, verifică termenii și abia apoi folosește
acțiunea explicită de trimitere deja existentă. Sintaxa nesuportată și numele
ambigue sunt refuzate, nu ghicite.

Comanda exactă „Cine nu mi-a plătit?” este acum o interogare read-only peste
registrul manual al firmei. Răspunsul arată numărul soldurilor, totalul și câte
au depășit scadența, apoi deschide filtrul detaliat; nu include date în URL și
spune explicit că nu a verificat banca. Comenzile „Programează lucrarea marți”
și „Lucrarea s-a terminat” rămân dezactivate: programarea și finalizarea manuală
există, dar interpretarea sigură a datelor relative și selecția unei lucrări nu
sunt încă implementate. Nu vom afișa răspunsuri inventate. Un model AI
generativ poate ulterior propune același **plan de acțiune structurat** printr-un
adaptor separat, dar decizia finală rămâne în formularul și tranzacțiile serverului;
datele personale nu merg la un serviciu extern fără alegere și temei explicite.

### 1. Lucrarea după acceptarea ofertei — bază implementată

Adăugăm `ProviderWorkOrder` legat de oferta acceptată și de firma emitentă, creat
automat în aceeași tranzacție cu acceptarea directă sau din comparație.
Păstrăm suma și descrierea ofertei ca referință imuabilă, nu ca factură.
Prima felie afișează lucrarea „De programat” în spațiile private ale firmei și
clientului. Proprietarul poate acum programa și reprograma execuția la o dată
exactă, apoi confirma finalizarea după acea dată. Schimbările au revizie și
evenimente cu actor și timp. O programare viitoare poate fi anulată explicit:
intervalul dispare din agendă, clientul primește notificare, iar oferta
acceptată și lucrarea rămân active pentru reprogramare. Confirmarea începutului
și a finalului de către tehnician sunt acum disponibile pentru lucrările
atribuite. Finalizarea nu emite factură.

Panoul firmei are acum o secțiune „Lucrări” pentru ofertele acceptate, cu
filtre și numărări distincte pentru de programat, programate și finalizate.
Lista este paginată și deschide cererea privată exactă pentru programare sau
verificare; nu confundă vizita de constatare cu executarea. Din aceeași
secțiune se poate deschide o agendă săptămânală, doar în citire, pentru orele
de început ale lucrărilor încă programate și orele estimate de încheiere,
atunci când firma le completează. Datele vechi nu primesc o durată inventată.
Agenda semnalează suprapunerile dintre intervalele complete ale firmei, inclusiv
lucrări aflate în afara paginii curente. Un avertisment distinct arată când
același tehnician activ este atribuit la două intervale complete suprapuse,
atât în agendă și fișa firmei, cât și în lista sa. Avertismentul nu blochează
programarea și nu confirmă disponibilitatea reală pentru intervalele fără oră
de încheiere.
Începutul confirmat de tehnician este afișat în fișa lucrării; agenda rămâne
doar o estimare de interval, nu dovada prezenței sau a capacității echipei.

**Gata când:** acceptarea dublă nu dublează lucrarea; furnizorii concurenți nu
pot accesa lucrarea; cererile vechi fără ofertă acceptată rămân valide;
testele acoperă fluxul direct, comparația și permisiunile.

### 2. Calendar și echipă

Adăugăm roluri per firmă: proprietar, coordonator, tehnician. Proprietarul
invită și revocă membrii; revocarea taie imediat accesul. Coordonatorul
programează intervalul și atribuie un tehnician; tehnicianul vede doar
lucrările atribuite și poate confirma începutul/finalul. Verificăm suprapuneri,
fus orar, reprogramări și notificări. Vizita de constatare existentă rămâne
distinctă de programarea execuției.

Prima fundație tehnică este separată de contul proprietarului: apartenența de
tehnician nu deschide inboxul firmei. Atribuirea unei lucrări programate are
revizie și eveniment cu actor; cititorul de tehnician filtrează doar lucrările
sale active, neanonimizate. Revocarea taie accesul imediat, iar anularea
programării șterge atribuirea curentă, păstrând evenimentul. Proprietarul poate
acum invita la o adresă de e-mail un tehnician, retrage invitația, atribui o
lucrare programată și revoca accesul. Invitația este valabilă 48 de ore,
tokenul este stocat doar ca digest și acceptarea cere cont nou sau parola
contului existent cu aceeași adresă. Tehnicianul vede doar lista paginată a
propriilor lucrări programate; nu poate folosi inboxul proprietarului.
Tehnicianul confirmă începutul numai după ora programată și finalizarea numai
după începutul confirmat, cu revizie și eveniment cu actor. Finalizarea
actualizează starea lucrării și a cererii și notifică clientul prin canalul
existent, fără emitere de factură. Proprietarul poate finaliza în continuare
o lucrare dacă tehnicianul pierde accesul. Rolul de coordonator și
disponibilitatea reală pe intervale urmează separat.

### 3. Dovada execuției și garanția

Fotografii înainte/după doar în spațiul privat, cu limită, verificare MIME,
scanare de malware, eliminarea metadatelor EXIF, drepturi de acces și politică
de retenție. Finalizarea cere confirmare explicită, nu este dedusă din poze.
Garanția are condiții, început, sfârșit și document al prestatorului; nu o
promitem automat doar pentru că există o lucrare.

**Condiție înainte de activarea încărcării:** procesarea actuală a
portofoliului reencodează imaginile și elimină EXIF, însă mediul de dezvoltare
nu oferă scanner antimalware. Pentru fotografiile private ale lucrărilor trebuie
mai întâi definit un serviciu de scanare fail-closed, izolarea fișierelor în
carantină, ștergerea lor la retenția cererii și testele de acces pentru firmă,
tehnician și client. Nu activăm formularul doar pe baza curățării metadatelor.

### 4. Pregătirea facturării și registrul de încasări, fără plată integrată — implementat

După finalizarea explicită a lucrării, proprietarul poate salva o singură ciornă
internă cu suma și descrierea, precompletate din oferta acceptată. Ciorna este
privată firmei, editabilă cu revizie optimistă și ștearsă odată cu proiectul la
retenția curentă. Nu are număr, serie, TVA sau scadență, nu este afișată ca
factură clientului, nu se trimite și nu înregistrează plată. Este material de
pregătire, nu document fiscal și nu se păstrează ca unul.

Firma poate completa separat, într-o pagină privată, denumirea legală,
identificatorul fiscal, numărul de înregistrare și adresa pe care le declară ca
viitoare date ale emitentului. Formularul nu copiază automat date ONRC, iar
fiecare schimbare păstrează o revizie cu actor și moment. Salvarea nu validează
identitatea fiscală și nu deblochează emiterea.

Panoul furnizorului are o listă paginată a lucrărilor finalizate, separând
lucrările fără ciornă, ciornele gata de urmărit, soldurile restante și sumele
declarate integral încasate. După salvarea ciornei, proprietarul poate deschide
o evidență privată cu scadență și referință; suma este înghețată, iar ciorna nu
mai poate fi editată. Încasările manuale sunt înregistrări aditive cu dată, sumă,
referință și actor. O eroare se anulează cu motiv și rămâne în istoric, în loc să
fie ștearsă. Soldul însumează numai înregistrările active, nu poate deveni
negativ și nu este prezentat drept confirmare bancară.

Evidența și încasările sunt incluse în exportul persoanei vizate și urmează
retenția proiectului existent. Nu există număr fiscal, TVA, emitere, e-mail către
client sau integrare de plată. Aceste limite sunt afișate direct în interfață.

Pentru soldurile deschise există un reminder **strict intern**. Proprietarul îl
poate programa sau reprograma, îl vede în filtrul „De urmărit azi” și îl poate
marca realizat; nicio acțiune nu contactează clientul. Fiecare schimbare păstrează
revizie, actor, dată anterioară și dată nouă. După o urmărire realizată sau o
încasare parțială se aplică o pauză minimă de șapte zile, iar încasarea integrală
închide automat reminderul activ și jurnalizează motivul. Un reminder extern va
fi permis numai după existența unui document fiscal și definirea textului legal.

Configurăm identitatea fiscală a **fiecărui emitent**, seriile și numerotarea,
TVA, liniile, avansurile, corecțiile și cumpărătorul B2B/B2C. Un contabil sau
consilier fiscal validează regulile înainte de butonul „Emite”. Ciorna poate fi
editată; factura emisă este imuabilă și se corectează prin document fiscal nou.
Încasarea manuală cu dată, sumă și referință este acum disponibilă și nu este
prezentată drept confirmare bancară. Reminderul poate porni numai de la scadența
și soldul verificat, cu pauză după încasare, limită de frecvență și jurnal.

### 5. RO e-Factura, după verificare fiscală

Construim un adaptor separat, dezactivat implicit, pentru XML UBL conform
specificației în vigoare. Conectarea OAuth este individuală per emitent și
legată de autorizarea ANAF/certificatul calificat; tokenurile sunt criptate,
rotite și inaccesibile altor firme. Salvăm XML-ul exact transmis și identificatorul
de încărcare, apoi urmărim asincron starea, mesajele, erorile și răspunsul
descărcat. Retrimiterile sunt idempotente; interfața distinge **ciornă / emisă /
în curs de transmitere / transmisă / respinsă**. Nu declarăm conformitate
fiscală sau depunere reușită doar după un răspuns HTTP de upload.

Înainte de producție sunt obligatorii teste în mediul ANAF, audit de securitate,
validare cu contabil/fiscalist, procedură de recuperare la indisponibilitate și
o verificare actualizată a obligațiilor, excepțiilor și termenelor B2B/B2C.

### 6. Plăți reale — ultima etapă

După stabilizarea facturării și a abonamentelor, alegem procesatorul și
implementăm separat plata abonamentului platformei și plata facturii lucrării.
Evenimentele procesatorului se verifică criptografic, sunt idempotente și se
reconciliază cu registrul intern. Niciun status „plătit” nu apare pe baza unui
redirect de browser.

## Pachete propuse, nu abonamente active

| Plan | Preț-țintă | Limită/valoare de validat cu firme-pilot |
| --- | ---: | --- |
| Esențial | 49 lei/lună | profil, cereri, oferte, acceptări și o evidență simplă a lucrărilor pentru proprietar |
| Echipă | 99 lei/lună | Esențial + roluri, calendar, atribuire, fotografii și rapoarte operaționale |
| Business | 199 lei/lună | Echipă + fluxul de facturare, remindere și, numai după validare, RO e-Factura |

Limitele de utilizatori, documente, spațiu foto și costurile externe trebuie
stabilite după un pilot. Site-ul construit și administrat pentru firmă este
serviciu uman separat: planul Partener existent propune 299 lei/lună, cu scop
și costuri suplimentare explicite. Nu îl reducem tacit la 199 lei și nu schimbăm
prețurile publicate până la aprobarea ofertei comerciale. Cifra
`1.000 × 99 = 99.000 lei/lună` este venit brut recurent ipotetic, nu prognoză
de profit; pilotul trebuie să măsoare conversia, costul suportului și retenția.

## Decizii înainte de etapa fiscală

1. Emitentul este confirmat: fiecare firmă facturează clientul în nume propriu;
   platforma facturează separat numai abonamentul său. De validat cu specialistul
   fiscal: mandatul, identificarea emitentului și tratarea cazurilor excepționale.
2. Cine aprobă conținutul fiscal și corecțiile: proprietar, contabil sau rol
   dedicat; ce poate face un tehnician.
3. Limitele finale ale planurilor și dacă RO e-Factura intră în Business sau
   este un modul tarifat separat.
4. Perioada de păstrare a fotografiilor, garanțiilor și documentelor fiscale,
   precum și rolurile GDPR dintre platformă și firmă.

## Surse oficiale consultate (18 septembrie 2026)

- ANAF, [informare despre extinderea B2C din 2025](https://static.anaf.ro/static/3/Ploiesti/20240712105001_comunicat_modificari_la_e-factura.pdf).
- ANAF, [modificări aplicabile din 2026, inclusiv termenul de cinci zile lucrătoare](https://static.anaf.ro/static/3/Ploiesti/20260115111226_comunicat%20ajfp%20arges%20-%20modificari%20ro%20e-factura%20site.pdf).
- [Legea 88/2026](https://static.anaf.ro/static/10/Anaf/legislatie/L_88_2026.pdf), cu nuanțe pentru beneficiarii persoane fizice.
- ANAF, [înregistrarea aplicațiilor și autorizarea OAuth](https://www.anaf.mfinante.gov.ro/InregOauth/index.xhtml) și [serviciile web e-Factura](https://static.anaf.ro/static/10/Anaf/Informatii_R/Servicii_web/url_eFactura.html).
