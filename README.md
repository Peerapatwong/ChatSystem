# NetworkSocket — Client-Side Command Guide

## What is NetworkSocket?

**NetworkSocket** is a lightweight, threaded TCP chat / file‑sharing server for **localhost:9999**. It lets multiple users:
- Log in with a username and password.
- List users, groups, direct files, and group files.
- Send / retrieve / reject files between users.
- Direct message another user.
- Manage groups (create, join, leave, group messages).
- Generate images and summarize PDFs via Google Gemini AI.

The most recent commit adds **AI features** (Gemini ask‑model, image generation, PDF summarization).

---

## Quick start

```bash
# 1. Clone the repo (or copy the three files)
git clone https://github.com/Jojo-Supawit/NetworkSocket.git
cd NetworkSocket

# 2. Create .env.example and edit it:
cat > .env.example <<'EOF'
HOST=localhost
PORT=9999
GOOGLE_API_KEY=YOUR_GEMINI_API_KEY
EOF
# then run:
python server.py
```

The server starts with:

```
[SERVER STARTED] Running on localhost:9999

Enter your username: <your_user>
Logging in successfully
```

After login the terminal prompt changes to `> `. From there you type **client‑side commands** (see below) and send them over the TCP socket the server is listening on.

---

## Connecting from your terminal

There is no separate client executable — the same process (`server.py`) runs both as a server. You interact via standard input, which sends JSON lines to `localhost:9999`:

```bash
# In one terminal:
python3 server.py          # or python server.py
```

When asked for username it prints:

```
[NEW CONNECTION] Connected from 0.0.0.0:xxxx
Enter your username: <alice>
Logging in successfully
> 
```

Then every command is a line starting with `/` and arguments after the slash are passed as JSON payloads.

## Classic Windows GUI client

The repository also includes a dependency-free Tkinter GUI with an old Windows
look. Start the server, then launch the GUI in another terminal:

```bash
python server.py
python gui_client.py
```

Enter the host, port, and a unique user name, then choose **Connect**. The GUI
keeps permanent controls to a minimum:

- Double-click a user or group to open its own independent chat window.
- Open dedicated Gemini and server-log windows from the **Chat** menu.
- Type a message and press **Enter** (or choose **Send**) in any chat window.
- Right-click users, groups, or files for contextual actions.
- The Gemini window combines chat, image creation, and PDF summaries; private
  and group windows include their relevant file and group actions.
- The **Refresh** button reloads users and groups immediately; the GUI also
  refreshes those two lists automatically every five seconds.
- Press **F5** to refresh users, groups, and incoming files.

The GUI uses only Python's standard library. On Linux, the optional OS package
for Tk may need to be installed (often named `python3-tk`).

### Raw client → server request shape

Each message is a **single JSON object**:

```json
{
  "action": "<command>",
  "data": { ... }   # optional, only for actions that need it (e.g. send_file data, direct_message msg)
}
```

Examples:

- Login: `login {"username":"alice"}`
- List users: `/list_users` → `{"action":"list_users","data":null}`
- Direct message: `direct_message {"target_name":"bob","msg":"hello"}` or `"/dm bob hello"`
- Create group: `/create_group "mygroup"` → `{"action":"create_group","group":"mygroup"}`

---

## Supported commands

### Authentication
| Command | What it does |
|---|---|
| `/login <username>` | Sends login request; server replies with status **011** + `"Logging in successfully"`. First time only. Returns 010 if username already taken. |
| `/logout` | Sends logout, closes the connection (resets `is_connected`). |

### Listing users
- `/list_users` → all users and their addresses.
- `/list_groups` → group names.
- `/list_files` → files belonging to each user.
- `/list_direct_files` → files you can send directly without joining a group.
- `/list_group_files <group>` → files in a specific group.

### Direct messaging
- `/direct_message <target_name> "<msg>"`  
  or shorthand `"/dm target_name msg"`
- Sends a private message to the user identified by `<target_name>@<addr>`. Returns **200** (target not found) / **201** (sent).

### Groups
- `/create_group <group_name>` → creates new group.
- `/join_group <group_name>` → joins an existing group. Returns **310** if already a member.
- `/leave_group <group_name>` → leaves a group. Returns **320** if doesn't exist or not a member.
- `/group_message <group_name> "<msg>"` / `"/gm <group_name> msg"`
  - Sends a message to every member of the group.

### File operations
| Action | Syntax (client side) | Server action |
|---|---|---|
| Send file | `/send_file <target_name> <file_name> <data>` | writes `data` into `users[<target>].files[<file_name>]`; returns **401** if not yet sent, **400** if target unknown or file already exists. |
| Retrieve file (your own) | `/retrieve_file <file_name>` / `direct_retrieve_file` | returns content; **410** if missing, **411** on first read, **421** once removed. |
| Reject file | `/reject_file <file_name>` | removes from user's files list; returns **420/421**. |
| Create group + send its file | `/create_group <g>` → then `/send_file <tgt> f.txt <data>` | creates group, tracks members/files. |

### AI / Image & PDF
- `/generate_image <file_name> "<prompt>"` — asks Gemini to create an image.
- `/pdf_sumarize <base64_pdf_data>` — sends a base64‑encoded PDF and text "Summarize this document"; returns the summary.

### Ask Google Gemini
- `/ask_gemini "<prompt>"` → calls `client.interactions.create(model="gemini-3.5-flash-lite", input=prompt)`. Returns **501** on failure or the interaction output.

---

## Example session

```bash
$ python server.py
[SERVER STARTED] Running on localhost:9999

Enter your username: alice
Logging in successfully
> /list_users
alice@localhost:9999, bob@localhost:9999
...

> /direct_message bob "Hey, are you free?"
→ [Server]: [alice] Sent direct message to bob...
```

After login the `>` prompt lets you type any of the commands above. Each command is a JSON line that the server decodes and dispatches.

---

## How authentication works

1. **First connection without a valid login** → server replies with status **000** "Not authenticated" and sets `is_logged_in = False`.
2. Sending `/login <username>`:
   - If username exists in `users` → **010** "Username already used".
   - Otherwise → adds entry, sends **011** "Logging in successfully", sets `is_logged_in = True`.
3. All commands after login require `is_logged_in == True`. Trying to log in again or use a non‑existent user yields error codes.

---

## File I/O details

- Files are transferred as raw bytes.
- `openFileToString(path)` reads the file in binary and returns its hex representation.
- `stringToFile(data, path)` writes `data` (base64‑decoded) as binary to disk.
- The server keeps a per‑user `files` dict; retrieval pops the entry from that dict after returning.

---

## Help & where to find more

- **Repository history:** 4 commits on `main`, latest `80d2180 — feat: add AI features`.
- **Branches / tags:** none listed for this repo.
- The code lives in three files:
  - `.env.example` (environment template)
  - `.gitignore`
  - `server.py` and `client.py` (shared server logic, see the previous overview).
