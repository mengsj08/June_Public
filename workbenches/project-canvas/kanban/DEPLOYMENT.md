# Deployment

The public Phase 1 runtime is a local, loopback-only demo. It does not ship a
remote authentication profile and must not be exposed directly to the Internet.

## Local quick start

Prerequisites:

- Python 3 with `venv`
- Node.js and npm

From the repository root:

```bash
./start.sh
```

The launcher creates `.venv/`, installs Python dependencies, installs frontend
dependencies when needed, builds `canvas-studio/dist`, starts the backend on
`127.0.0.1:8890`, and opens the fictional demo canvas through `open` on macOS
or `xdg-open` on Linux when available. A missing opener logs a degradation and
does not stop the service.

Useful options:

```bash
./start.sh --no-open
./start.sh --port 9000
```

`start.sh` uses `.kanban.config.json` when present. Otherwise it uses the
tracked local-only `demo/kanban.demo.config.json`. Copy
`kanban/.kanban.config.example.json` to the repository root when creating a
deployment-specific configuration. Local config, credentials, runtime state,
virtual environments, dependencies, and build output are gitignored.

For non-demo local use, authentication defaults to a random token generated at
first start in `.kanban.auth-token`. The file is gitignored and forced to mode
`0600`; paste its value into the login screen. The tracked fictional demo is an
intentional exception with `local_bypass=true` so the one-command demo remains
frictionless. `local_bypass`, `autologin`, and legacy `auth.mode=quiz` are never
safe defaults and must remain explicit opt-ins.

## Platform support

| Platform | Status | Notes |
|---|---|---|
| macOS / Darwin | verified | Desktop open and Terminal bridge retain the existing adapter behavior. |
| Linux | mock-tested, **not verified on a real Linux host** | Uses `xdg-open` and detached subprocess launch. Missing desktop capabilities are hidden or return a readable 503 response. |
| Windows | native runtime unsupported | Use WSL and follow the Linux path; use `--no-open` when WSL has no graphical opener. |

AppleScript, `.app` bundle control, and macOS system-proxy inspection are
darwin-only optional adapters. The public project does not ship or promise an
`.app` wrapper, codesign flow, launchd installer, or native Windows launcher.

## Paths and optional integrations

`paths.repo_root`, `paths.workspace_root`, and `paths.data_root` make deployment
boundaries explicit. Relative values resolve from the cloned repository.
`KANBAN_REPO_ROOT` may be used when the code is launched through a wrapper, and
`KANBAN_CONFIG` may select a different configuration file.

The public defaults only trust `.` and `demo` through `open_allowed_roots`.
External workspace roots must be added explicitly. Sibling tools, automation,
knowledge sources, relationship data, session archives, network tooling,
research boards, and Conversation Maps are all opt-in. An integration is hidden
when it is disabled, incomplete, outside the allowlist, or absent on disk.

Canvas Studio is served from `canvas-studio/dist` by default. A missing build
returns a small explainer page instead of crashing the Kanban service.

## Remote deployment gate

The service intentionally binds to loopback. Local bypass in the demo profile
is only for that loopback demo. Before any remote deployment, provide a real
authentication layer, TLS, secure-cookie handling, CSRF/proxy tests, secret
management, and a reviewed process supervisor configuration. Those controls are
outside Phase 1 and no Nginx/systemd recipe is claimed as safe here.

Setting `bind_host` to a non-loopback address is an explicit risk acceptance,
not a deployment recipe. Configure exact `allowed_hosts` as well; the server
prints a high-visibility warning. Host/Origin guards and the local token do not
replace TLS, proxy hardening, or a reviewed remote identity provider.
