# Chat Log Receiver

Receives clan chat messages submitted remotely by staff running the `chat-logger` RuneLite plugin, dedupes and persists them to Supabase, and resolves each sender to a clan `member_id` where possible.

## Setup

```sh
cd chat-log-receiver
pip install -r requirements.txt
cp .env.template .env  # fill in SUPABASE_DB_URL and RECEIVER_AUTH_TOKEN
```

Before first run, execute (in order) in the Supabase SQL Editor:
1. `../admin-bot/chat_log_receiver_role.sql` — creates the restricted `chat_log_receiver` Postgres role (set a real password before running).
2. `../admin-bot/chat_log_entries_table.sql` — creates the table, indexes, and RLS policy.

`SUPABASE_DB_URL` should use the `chat_log_receiver` role's credentials, not the default `postgres` superuser connection string (which has `BYPASSRLS` and would make the table's RLS policy a no-op).

## Run

```sh
uvicorn main:app --reload
```

## Endpoints

- `POST /submit` — the chat-logger plugin's remote submission endpoint. Requires `Authorization: <RECEIVER_AUTH_TOKEN>`, body is a JSON array of chat entries.
- `GET /health` — liveness check.

## Configuring the plugin

In the chat-logger plugin's settings, under "Remote Submission":
- **Endpoint**: `https://<this-service's-railway-url>/submit`
- **Authorization**: the shared `RECEIVER_AUTH_TOKEN` value
- Enable "Remote Clan Chat" (and/or Friends/Group Chat as desired)
