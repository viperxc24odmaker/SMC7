# Smooth Launcher

A clean, premium Minecraft launcher. Microsoft + offline login, version &
Fabric installation, and a network layer built to survive flaky connections.

Built with Python + PyQt6 and `minecraft-launcher-lib`. Ships as a Windows
`.exe` via GitHub Actions.

---

## Features

- **Microsoft login** (real Xbox/Minecraft auth) with an in-app Azure **Client ID**
  field — paste yours in Settings and it just works.
- **Offline login** — username + true vanilla offline UUID, so worlds stay consistent.
- **Multiple accounts**, switch active with one tap.
- **Vanilla or Fabric** install + launch (defaults to **1.21.11**, the client test target).
- **Bulletproof networking**: global timeouts, automatic retries with backoff,
  cached version list, and full offline-launch fallback. A bad connection shows a
  friendly message and lets you retry — it never freezes or crashes.
- Premium dark UI: layered surfaces, one accent, rounded cards, animated toggles.

---

## Building the `.exe` (GitHub Actions)

1. Push this whole folder to a GitHub repo.
2. **Create `.github/workflows/build.yml` manually in GitHub's web editor.**
   Drag-and-drop upload skips hidden folders (anything starting with `.`), so the
   workflow won't run if you upload the folder as a zip. Make the file by hand.
3. Go to the **Actions** tab → run **Build Smooth Launcher (Windows)** (or just push).
4. Download the `SmoothLauncher-windows` artifact, unzip, run `SmoothLauncher.exe`.

The build uses PyInstaller **onedir** mode (most reliable for Qt WebEngine).

## Running from source (if you ever get a local Python env)

```bash
pip install -r requirements.txt
python run.py
```

---

## Setting up Microsoft login (Azure)

Microsoft requires every launcher to use its own Azure app registration. Once you
have the Client ID, paste it into **Settings → Microsoft login**.

1. Go to <https://portal.azure.com> → **Microsoft Entra ID** → **App registrations**
   → **New registration**.
2. Name it `Smooth Launcher`. For account types choose
   **Personal Microsoft accounts only** (or "any org directory + personal").
3. Under **Redirect URI**, pick platform **Public client/native (mobile & desktop)**
   and set it to:
   `https://login.microsoftonline.com/common/oauth2/nativeclient`
   (this is the default already filled in the launcher).
4. Click **Register**, then copy the **Application (client) ID**.
5. In **Authentication**, make sure **Allow public client flows** is enabled.
6. Paste the Client ID into Smooth Launcher → Settings → Save. Now hit **+ Microsoft**.

> ⚠️ Heads up: Microsoft/Mojang may require your Azure app to be approved for the
> Minecraft API. If sign-in returns an **"Azure app not permitted"** error, that's
> not a launcher bug — you need to request Minecraft API access for your app
> through Microsoft/Mojang. Offline login works with no setup at all.

---

## Where your data lives

Config + accounts are stored in your per-user app folder
(`%APPDATA%/SmoothLauncher/config.json` on Windows). Microsoft refresh tokens are
kept there in plain text for silent re-login — it's a local file on your own
machine, same as other launchers, but don't share it.

---

## Roadmap (next phases)

- **Smooth Client** — Fabric 1.21.11 mod with 35+ QoL/HUD modules (built & tested
  on 1.21.11 first), auto-installed by this launcher.
- **Cosmetics** — wings & capes, client-and-game-side visible to other Smooth users.
