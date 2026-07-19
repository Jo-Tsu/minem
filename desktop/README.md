# MineM macOS Client

This directory contains the Tauri desktop shell. It opens the existing MineM
web application in the macOS system WebView and starts a local MineM service.

## Development

```bash
npm --prefix desktop install
npm run desktop:dev
```

Development launches `python3 server.py` from the project root. It uses
`~/Library/Application Support/MineM/` for runtime data, so it does not share
the repository data directory or a Docker SQLite instance.

## Build a DMG

```bash
python3 -m pip install -r desktop/requirements-build.txt
npm --prefix desktop install
npm run desktop:build
```

`desktop:build` first builds the React assets, then packages the Python service
as a macOS sidecar, and finally runs Tauri to produce the `.dmg` installer.
