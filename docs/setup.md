# Setup guide

One-time steps to get signal-cli-rest-api running and the bot registered.

## Hardware

The workload is very light — the bot idles on a WebSocket and makes one API call per incoming message. Any of the following work:

- **Raspberry Pi 3B+ or newer.** A Pi 4 or 5 is comfortable; a Pi 3B+ is fine. Avoid the SD card for signal-cli config and the vault working copy — write a few notes to a USB stick or small SSD instead, and keep the SD card for the OS only.
- **Small cloud VPS.** A €3–5/month ARM instance (e.g. Hetzner CAX11) is a clean option: reliable uptime, easy SSH, no hardware to manage. Trade-off: your Signal registration and API key live on a third-party machine.
- **Mac (development/testing).** Docker and Python both run on Mac. Skip the systemd unit and run `python -m pipeline.bot` directly. Good way to validate the pipeline before committing to a server.

Outbound internet only — no ports need to be open externally.

## Prerequisites

- Raspberry Pi OS 64-bit (or Debian)
- Docker + Docker Compose installed
- External SSD mounted at `/mnt/ssd`
- A JMP.chat number (or any other VoIP/SIM number not already registered on Signal)
- Python 3.11+ and `uv`

---

## 1. Prepare directories

```bash
mkdir -p /mnt/ssd/signal-cli-config
```

---

## 2. Register the bot number

Start the container temporarily in `native` mode to run the registration:

```bash
docker run --rm -it \
  -e MODE=native \
  -v /mnt/ssd/signal-cli-config:/home/.local/share/signal-cli \
  -p 127.0.0.1:8080:8080 \
  bbernhard/signal-cli-rest-api:latest
```

In another terminal, request a verification SMS (replace `+49...` with your bot number):

```bash
curl -X POST "http://localhost:8080/v1/register/+49..." \
  -H "Content-Type: application/json" \
  -d '{"use_voice": false}'
```

Once you receive the SMS code:

```bash
curl -X POST "http://localhost:8080/v1/register/+49.../verify/123456"
```

Stop the temporary container (Ctrl-C).

---

## 3. Start in json-rpc mode

```bash
# from the signal-kb repo root
docker compose up -d
```

The container now listens on `ws://localhost:8080/v1/receive/<number>`.

---

## 4. Add the bot to the Signal group

In your Signal app, open the group → Group settings → Group link → enable it and copy the link (it looks like `https://signal.group/#...`).

Stop the container, then join the group using signal-cli directly:

```bash
docker compose stop

docker run --rm \
  -v /mnt/ssd/signal-cli-config:/home/.local/share/signal-cli \
  --entrypoint /usr/bin/signal-cli \
  --user 1000:1000 \
  bbernhard/signal-cli-rest-api:latest \
  --config /home/.local/share/signal-cli \
  -u +49... joinGroup \
  --uri "https://signal.group/#..."

docker compose up -d
```

> **Why not "Add members"?** Signal v2 groups send the invitation as an encrypted message that signal-cli cannot decrypt until a session is established. Joining via the group link bypasses this and works reliably.

---

## 5. Find the group ID

Connect to the WebSocket and send any message to the group from your phone:

```bash
wscat -c ws://localhost:8080/v1/receive/+49...
```

Or with Python if wscat is not available:

```bash
uv run --with websockets python3 -c "
import asyncio, websockets, json
async def main():
    async with websockets.connect('ws://localhost:8080/v1/receive/+49...') as ws:
        for _ in range(20):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                print(json.dumps(json.loads(msg), indent=2))
            except asyncio.TimeoutError:
                break
asyncio.run(main())
"
```

Alternatively, query it directly:

```bash
curl http://localhost:8080/v1/groups/+49...
```

Use the `internal_id` field from the response as `SIGNAL_GROUP_ID` — not the `id` field. Example response:

```json
{"id": "group.XXX=", "internal_id": "YIngz...==", ...}
```

Set `SIGNAL_GROUP_ID=YIngz...==` in your `.env`.

---

## 6. Set up the vault repo

```bash
cd /mnt/ssd
git clone git@github.com:<your-org>/verwaltungsdigitalisierung-kb.git
```

Ensure `tags.yaml` exists in the repo root (it is tracked in the vault repo).

---

## 7. Set up a GitHub deploy key

```bash
ssh-keygen -t ed25519 -C "signal-kb-bot" -f ~/.ssh/vault_deploy_key -N ""
cat ~/.ssh/vault_deploy_key.pub
```

Add the public key to the vault repo on GitHub: **Settings → Deploy keys → Add deploy key** (check "Allow write access").

Configure the vault repo to use this key:

```bash
cd /mnt/ssd/verwaltungsdigitalisierung-kb
git remote set-url origin git@github-vault:your-org/verwaltungsdigitalisierung-kb.git
```

Add to `~/.ssh/config`:

```
Host github-vault
    HostName github.com
    User git
    IdentityFile ~/.ssh/vault_deploy_key
```

---

## 8. Configure the bot

```bash
cd /home/pi/signal-kb
cp .env.example .env
# edit .env and fill in all values
```

---

## 9. Install Python dependencies

```bash
uv sync
```

---

## 10. Install and start the systemd service

```bash
sudo cp systemd/kb-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable kb-bot
sudo systemctl start kb-bot
sudo systemctl status kb-bot
```

Logs:

```bash
journalctl -u kb-bot -f
```

---

## Verify end-to-end

Drop a link in the Signal group. Within ~30 seconds a new commit should appear in the vault repo on GitHub.

## Reliability notes

- **systemd** restarts the bot on any crash with a 10-second delay (`Restart=on-failure, RestartSec=10`).
- **Docker Compose** restarts signal-cli-rest-api unless explicitly stopped (`restart: unless-stopped`).
- **Git push failures are non-fatal.** The markdown file is written locally first. If the push fails, the file is queued and the next successful run will push the backlog.
- **SSD for state.** The signal-cli config and vault working copy are on the SSD, not the SD card, to avoid corruption under frequent writes.
