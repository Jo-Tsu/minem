# MineM macOS Client

This directory contains the Tauri desktop shell. It opens the existing MineM
web application in the macOS system WebView and starts a local MineM service.

The vNext runtime initializes user-scoped state under
`~/Library/Application Support/MineM`, writes bootstrap progress to
`runtime/bootstrap-state.json`, and publishes the active service address in
`runtime/service.json`. `MINEM_DATA_DIR` remains available for isolated
development and migration tests.

The packaged client always owns its runtime. It never adopts a Docker,
development, legacy, or separately started MineM service. When port `8790` is
occupied, the client starts the bundled sidecar on a free loopback port and
publishes that address to the runtime manifest.

The app creates a no-admin user launcher at `~/.local/bin/minem` on first
startup. The menu-bar app and Creator Assistant also expose an optional
system-wide “Install CLI” action for `/usr/local/bin/minem`. The packaged
service is a multi-call executable: the app starts it in server mode, while
either launcher uses CLI mode and follows the runtime in
`/Applications/MineM.app` after client upgrades.
When no managed runtime is active, the CLI launches `MineM.app` in the
background and waits for the new service manifest before executing a command.

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
