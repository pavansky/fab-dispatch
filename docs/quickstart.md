# Quick start

Pick whichever suits you. All three run the same app; the local ones need no accounts or keys.

## 1. Live, in 10 seconds

Open **[fab-dispatch.vercel.app](https://fab-dispatch.vercel.app)** and click **Try it as a guest**.
Guests get full dispatcher access to the sample fabs.

## 2. In your browser, with nothing installed

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/pavansky/fab-dispatch?quickstart=1)

GitHub builds a development environment, installs everything and starts the app; the preview opens
by itself (about 3 minutes the first time). Click **Continue as Dispatcher**.

## 3. On your machine, with one command

You need **Python 3.11–3.14** and **Node.js 20.19+**.

```bash
git clone https://github.com/pavansky/fab-dispatch.git
cd fab-dispatch
python3 run.py
```

`run.py` checks your versions, installs what's missing (once), starts the API and the UI together
and opens **http://localhost:5173**. Click **Continue as Dispatcher**. Press **Ctrl-C** to stop both.
On Windows, use `py run.py`.

!!! note "Other ways"
    - `make start` does the same as `python3 run.py`.
    - `docker compose up --build` runs a production-like stack (Postgres, Qdrant, API, nginx) on
      **http://localhost:8080**.
    - Prefer two terminals? The [README](https://github.com/pavansky/fab-dispatch#quick-start) has the
      manual steps for macOS, Linux and Windows.

## Then

- Take the [5-minute tour](reviewers.md#the-app-in-5-minutes), or press **?** in the app.
- Ask the assistant (**/**): *"Why is J006 unassigned?"*
- Interactive API docs: **http://localhost:5173/api/docs**.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Python 3.11–3.14 is required` | Install a supported Python, then run it explicitly, for example `python3.12 run.py`. |
| `Node.js 20.19+ is required` | Install Node 22 LTS from [nodejs.org](https://nodejs.org). |
| `Is port 8000 free?` | Another process holds the port. Stop it (`lsof -i :8000` on macOS/Linux) and retry. |
| *Can't reach the API* in the app | The API stopped; check the terminal running `run.py`. |
| Start from a clean slate | Stop the app and delete `backend/data/`. |
