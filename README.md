# Discord Bot

A modular Python Discord bot skeleton built with [discord.py](https://discordpy.readthedocs.io/).

## Local Development (Windows / Linux)

1. Create a bot at the [Discord Developer Portal](https://discord.com/developers/applications)
2. Copy `.env.example` to `.env` and set your token:

   ```bash
   cp .env.example .env   # Linux
   copy .env.example .env # Windows
   ```

   For faster slash command updates during development, also set `GUILD_ID` to your test server's ID (right-click server → Copy Server ID, with Developer Mode enabled).

3. Install dependencies:

   ```bash
   python3 -m venv .venv

   # Linux / macOS
   source .venv/bin/activate

   # Windows
   .venv\Scripts\activate

   pip install -r requirements.txt
   ```

4. Run the bot:

   ```bash
   python run.py
   ```

## Ubuntu Server Deployment

The bot runs as a systemd service and restarts automatically on failure.

### First-time setup

On your Ubuntu server, clone the repo and run the install script:

```bash
git clone <your-repo-url> discord-bot
cd discord-bot
sudo chmod +x scripts/setup-ubuntu.sh
sudo ./scripts/setup-ubuntu.sh
```

By default this installs to `/opt/discord-bot`. Pass a custom path if needed:

```bash
sudo ./scripts/setup-ubuntu.sh /home/ubuntu/discord-bot
```

Then set your token and start the service:

```bash
sudo nano /opt/discord-bot/.env
sudo systemctl start discord-bot
```

### Service commands

```bash
sudo systemctl status discord-bot   # check status
sudo systemctl restart discord-bot  # restart after code changes
sudo systemctl stop discord-bot
sudo journalctl -u discord-bot -f   # follow logs
```

### Updating after git pull

If the server install is a git clone:

```bash
sudo chmod +x scripts/update-ubuntu.sh
sudo ./scripts/update-ubuntu.sh
```

Or manually:

```bash
cd /opt/discord-bot
sudo -u discordbot git pull
sudo -u discordbot .venv/bin/pip install -r requirements.txt
sudo systemctl restart discord-bot
```

## Project Structure

```
discord-bot/
├── run.py                      # Start the bot
├── deploy/
│   └── discord-bot.service     # systemd unit file
├── scripts/
│   ├── setup-ubuntu.sh         # first-time server install
│   └── update-ubuntu.sh        # pull + restart on server
└── bot/
    ├── main.py                 # Bot class, cog loading, startup
    ├── config.py               # Environment-based settings
    ├── logging_setup.py
    └── cogs/                   # Feature modules (one cog per file)
        ├── general.py          # Example commands (ping, hello)
        ├── mirror.py           # Cross-server embed mirroring
        └── _template.py
```

## Adding Features

1. Copy `bot/cogs/_template.py` to a new file (e.g. `moderation.py`)
2. Add slash commands with `@app_commands.command` in a `Cog` class
3. Add the module path to `COG_EXTENSIONS` in `bot/main.py`:

   ```python
   COG_EXTENSIONS = [
       "bot.cogs.general",
       "bot.cogs.moderation",  # new
   ]
   ```

Each cog is self-contained — slash commands, listeners, and setup logic live in one file. Restart the bot after adding or changing commands so they sync to Discord.

### Slash command sync

| Environment | `GUILD_ID` in `.env` | Sync behavior                          |
|-------------|----------------------|----------------------------------------|
| Development | Set to test server   | Commands appear instantly in that guild |
| Production  | Leave unset          | Commands register globally (may take up to ~1 hour) |

## Included Commands

| Command   | Description              |
|-----------|--------------------------|
| `/ping`   | Check bot latency        |
| `/hello`  | Greet the user           |

## Embed Mirroring

Copy embeds from a bot or app in one server and post them in other servers. The bot must be in every source and destination server, with permission to read the source channel and send messages in the destination channel.

### One-time copy

Use `/mirror copy` with a message link and a destination channel:

1. Right-click the source message (from another bot) → **Copy Message Link**
2. Run `/mirror copy` and paste the link
3. Pick the destination channel (can be in a different server)

### Auto-mirror

Use `/mirror add` to watch a source channel and automatically copy new embeds to a destination channel.

Discord's channel picker only works within one server, so cross-server mirrors use **channel IDs**:

1. Enable **Developer Mode** in Discord (Settings → Advanced)
2. Right-click a channel → **Copy Channel ID**
3. Paste the IDs into `/mirror add`:
   - **source_channel_id** — where the other bot posts
   - **destination_channel_id** — where copies should go (can be in another server)
   - **bot_id** (optional) — user ID of the bot/app to mirror

Add the same source multiple times with different destinations to fan out to several servers.

| Command        | Description                                      |
|----------------|--------------------------------------------------|
| `/mirror add`  | Auto-mirror new embeds from source → destination |
| `/mirror copy` | One-time copy from a message link                |
| `/mirror test` | Diagnose why a message would or would not mirror |
| `/mirror list` | Show configured mirrors                          |
| `/mirror remove` | Remove a mirror by ID                          |

Mirror configs are stored in `data/mirrors.json` on disk. Requires **Manage Server** permission to use these commands.

### Troubleshooting

- **Only new messages mirror** — embeds posted *before* `/mirror add` are not copied. Use `/mirror copy` for those.
- **Bot filter mismatch** — many bots post via **webhooks**, so their message author ID differs from the bot's user ID. Run `/mirror test` with the message link to see the real author/webhook IDs, then re-add the mirror with the correct `bot_id` or leave `bot_id` empty to mirror any bot in that channel.
- **Check bot logs** — when a message is skipped, the bot logs the reason to the console.
