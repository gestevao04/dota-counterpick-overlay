# Privacy Policy for Dota 2 Draft Overlay

**Last Updated: November 2026**

Dota 2 Draft Overlay is an open-source application. This privacy policy explains what data the application handles and how it is used.

### 1. Data Collection and Telemetry
We **do not** collect, store, transmit, or sell any personal data, telemetry, analytics, or usage statistics. The developer of this application has no access to your data.

### 2. Local Data Storage
The application stores a `config.json` file on your local machine. This file contains:
* Your Stratz API token.
* Your user preferences (selected team, position, UI state).
* Downloaded data cache (hero lists, win rates, portraits).

This data is stored locally in the program's folder (or in `%APPDATA%\DotaDraftOverlay` if the program folder is read-only). You can delete these files at any time to remove all stored data.

### 3. Third-Party Network Requests
To function, the overlay must communicate with public APIs. When the application makes a request, it sends standard HTTP data (including your IP address).

* **STRATZ API (api.stratz.com):** Your API token is sent to STRATZ to authenticate the request and download aggregate hero win-rate data. Your token is subject to STRATZ's own privacy policy.
* **OpenDota API (api.opendota.com):** Used to fetch the current list of heroes.
* **Valve CDN (cdn.cloudflare.steamstatic.com):** Used to download hero portrait images.

The application only sends aggregate game data queries to STRATZ (e.g., "what is the win rate of Hero A against Hero B in the Legend bracket"). It **does not** send your personal match history, player ID, or Steam credentials.

### 4. Screen Capture
The application uses screen capture to read the hero portraits on the Dota 2 draft screen. These screenshots are processed locally on your machine using OpenCV and are never uploaded to any server.

### 5. Fair Play
The overlay only reads pixels on your screen. It does not read game memory, inject into the game process, or automate inputs. It contains no cheat functionality.

### 6. Contact
If you have any questions about this privacy policy, please open an issue on the GitHub repository.