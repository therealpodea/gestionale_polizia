# 🚀 Gestionale Polizia d'Estovia — Guida Deploy su Railway

Segui questi passi **nell'ordine**. Non serve saper programmare.

---

## PASSO 1 — Crea un account GitHub

1. Vai su **https://github.com**
2. Clicca **"Sign up"**
3. Registrati con email e password
4. Conferma l'email

---

## PASSO 2 — Carica i file su GitHub

1. Vai su **https://github.com/new** (crea un nuovo repository)
2. Nome repository: `gestionale-estovia`
3. Lascia tutto il resto di default → clicca **"Create repository"**
4. Nella pagina che si apre, clicca **"uploading an existing file"**
5. **Trascina** questi 3 file nella finestra:
   - `main.py`
   - `gestionale.html`
   - `requirements.txt`
6. In basso clicca **"Commit changes"**

✅ I file sono ora su GitHub.

---

## PASSO 3 — Crea un account Railway

1. Vai su **https://railway.app**
2. Clicca **"Start a New Project"**
3. Scegli **"Login with GitHub"** → autorizza Railway
4. Torna su Railway dopo il login

---

## PASSO 4 — Deploy su Railway

1. Clicca **"New Project"**
2. Scegli **"Deploy from GitHub repo"**
3. Seleziona **"gestionale-estovia"**
4. Railway inizia il deploy automaticamente ⏳

---

## PASSO 5 — Imposta la password segreta

Questa è la password che la **dirigenza** usa per accedere e modificare i dati.

1. Nel pannello Railway clicca sul tuo progetto
2. Vai su **"Variables"** (menu laterale)
3. Clicca **"Add Variable"**
4. Inserisci:
   - **Name:** `GESTIONALE_API_KEY`
   - **Value:** scegli una password sicura (es. `Estovia@2026!`)
5. Clicca **"Add"**
6. Railway fa il redeploy automaticamente

> ⚠️ Questa password è quella che usi nel gestionale alla voce "Password Dirigenza"

---

## PASSO 6 — Ottieni il tuo URL

1. Nel pannello Railway clicca **"Settings"**
2. Scorri fino a **"Domains"**
3. Clicca **"Generate Domain"**
4. Ottieni un URL tipo: `https://gestionale-estovia.up.railway.app`

**Condividi questo URL con tutti i membri del server Discord!**

---

## Come funziona per gli utenti

### Dirigenza:
- Apre l'URL
- Tab **"Dirigenza"** → inserisce la password impostata nel PASSO 5
- Ha accesso completo: aggiungere agenti, sanzioni, promozioni, ecc.

### Agenti (sola lettura):
- Apre l'URL
- Tab **"Accesso Agente"** → inserisce il suo nick Discord
- Vede il suo profilo, storico, bacheca comunicati

---

## Aggiornare i file in futuro

Se vuoi aggiornare il gestionale:
1. Vai su GitHub → `gestionale-estovia`
2. Clicca sul file da aggiornare
3. Clicca l'icona matita ✏️
4. Modifica e clicca **"Commit changes"**
5. Railway si aggiorna automaticamente in 1-2 minuti

---

## Problemi comuni

**Il sito non si apre:**
→ Aspetta 2-3 minuti dopo il deploy, Railway ci mette un po' la prima volta.

**"Errore connessione al server":**
→ Controlla che la variabile `GESTIONALE_API_KEY` sia impostata correttamente.

**Ho perso la password dirigenza:**
→ Vai su Railway → Variables → cambia `GESTIONALE_API_KEY` con una nuova password.

---

## Costi

Railway offre **5$ di credito gratuito al mese**.
Un gestionale leggero come questo consuma circa **0.50-1$ al mese** → è **gratis** in pratica.
