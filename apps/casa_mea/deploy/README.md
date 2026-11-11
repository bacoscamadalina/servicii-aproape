# ServiciiAproape — cloud de dezvoltare

Fișierul `docker-compose.yml` din rădăcina repository-ului pornește varianta
funcțională completă: PostgreSQL persistent, Django Admin, conturi de furnizor,
revendicări, servicii, acoperire și portofoliu.

Catalogul public capturat la 9 septembrie 2026 este inclus în imagine: 72.881 de
firme, 42 de județe și șapte opțiuni de servicii, inclusiv filtrul exact pentru
electricieni. La prima pornire sunt încărcate automat
în PostgreSQL doar identitățile ONRC strict necesare fluxurilor de revendicare
(ID intern și număr public de înregistrare). Nu sunt incluse parole, conturi,
e-mailuri, cereri, audituri sau fișiere private de pe calculatorul local.

## Configurare în platforma cloud

Platforma trebuie să detecteze `docker-compose.yml` din rădăcina repository-ului,
să ofere volume Docker persistente și să permită variabile de mediu. Configurează
doar administratorul inițial din
[`managed-cloud.env.example`](managed-cloud.env.example) în interfața cloudului.
Nu publica parole reale într-un fișier `.env` sau în Git.

Nu sunt necesare `CASAMEA_DOMAIN`, `CASAMEA_SECRET_KEY`, `CASAMEA_EMAIL_HOST`,
`CASAMEA_EMAIL_HOST_USER`, `CASAMEA_EMAIL_HOST_PASSWORD` sau
`CASAMEA_DEFAULT_FROM_EMAIL`. Mesajele de revendicare, invitație și recuperare a
parolei sunt scrise în logurile containerului `web`, fără conexiune externă SMTP.
Aceasta este o facilitate de testare, nu livrare reală de e-mail.

La prima pornire, `deploy/start_managed_cloud.py`:

1. așteaptă PostgreSQL și aplică toate migrările;
2. validează checksum-urile catalogului și seed-ului ONRC;
3. încarcă exact 72.881 de identități dacă tabela este goală;
4. creează administratorul inițial din secrete;
5. execută verificările Django și pornește Gunicorn în modul de dezvoltare.

Etapa Docker `managed-cloud` verifică încă din timpul buildului că snapshotul conține
toate cele 42 de județe și șapte opțiuni de servicii și că fiecare dintre cele 72.881 de firme are
identitatea necesară fluxului de revendicare. Un artefact incomplet sau cu checksum
diferit nu poate produce o imagine utilizabilă.

Pornirile următoare nu schimbă parola administratorului și refuză explicit o bază
parțială sau un seed care nu mai corespunde catalogului. Volumele `postgres_data`
și `private_media` păstrează conturile, revendicările și portofoliile la restart și
la recrearea containerului.

## Test local al aceleiași configurații

Copiază cele trei credențiale de administrator într-un `.env` local ignorat de Git,
înlocuiește valorile marcate și pornește din rădăcina repository-ului:

```bash
cd /home/madalina/Documents/ChatGPT/CasaMea
cp apps/casa_mea/deploy/managed-cloud.env.example .env
docker compose up --build -d
```

Pentru un port local diferit, setează `APP_HOST_PORT=127.0.0.1:8005`. Varianta dev
acceptă direct HTTP și hostname-ul generat de platformă. În cloud recunoaște proxy-ul
HTTPS și originile de forma `https://*.apps.doiplusdoi.ro`, astfel încât formularele
CSRF din Django Admin și conturile furnizorilor funcționează fără domeniu fix.

## Administrare și persistență

După deploy, intră la `/admin/` pe URL-ul cloudului cu administratorul inițial. Schimbă
parola din admin după prima autentificare. Păstrează secretele de bootstrap în
managerul de secrete: ele permit recrearea administratorului numai dacă volumul
PostgreSQL este gol; nu rotesc un cont existent.

Nu șterge volumele cloudului la redeploy. `docker compose down --volumes` șterge
baza și media și trebuie folosit doar pentru medii locale dispensabile.

## Varianta separată numai pentru consultare

Fișierul `apps/casa_mea/docker-compose.yml` păstrează în continuare preview-ul fără
bază de date, admin sau scrieri. Este util doar pentru demonstrații statice:

```bash
cd apps/casa_mea
docker compose up --build -d
```

Deploy-ul complet cu backup privat, Caddy și aprobări publice controlate rămâne
documentat separat în [`PRODUCTION.md`](PRODUCTION.md) și păstrează cerințele stricte
pentru domeniu, HTTPS, secrete, identitate legală și SMTP. Catalogul inclus este o
captură istorică; o actualizare ONRC viitoare necesită un export revizuit, regenerarea
ambelor artefacte și reconstruirea imaginii.
