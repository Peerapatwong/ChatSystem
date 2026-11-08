"""A small, Windows-classic GUI client for NetworkSocket.

Run with::

    python gui_client.py

The module deliberately uses only the Python standard library.  Socket work is
done off the Tk event loop and all widget updates are marshalled through a
queue, so a slow server cannot freeze the window.
"""

from __future__ import annotations

import json
import queue
import socket
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk


APP_NAME = "NetworkSocket Chat"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9999


class SocketClient:
    """Newline-delimited JSON transport used by both CLI and GUI clients."""

    def __init__(self, events: queue.Queue):
        self.events = events
        self.sock: socket.socket | None = None
        self.connected = False
        self._send_lock = threading.Lock()

    def connect(self, host: str, port: int, username: str) -> None:
        if self.connected:
            return
        try:
            sock = socket.create_connection((host, port), timeout=8)
            sock.settimeout(None)
            self.sock = sock
            self.connected = True
            threading.Thread(target=self._receive, daemon=True).start()
            self.send("login", {"username": username})
        except OSError as exc:
            self.close(notify=False)
            self.events.put(("connection_error", str(exc)))

    def send(self, action: str, data=None) -> bool:
        sock = self.sock
        if not self.connected or sock is None:
            self.events.put(("connection_error", "Not connected to a server."))
            return False
        raw = (json.dumps({"action": action, "data": data}) + "\n").encode("utf-8")
        try:
            with self._send_lock:
                sock.sendall(raw)
            return True
        except OSError as exc:
            self.events.put(("connection_error", str(exc)))
            self.close()
            return False

    def _receive(self) -> None:
        buffer = ""
        try:
            while self.connected and self.sock is not None:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        try:
                            self.events.put(("response", json.loads(line)))
                        except json.JSONDecodeError as exc:
                            self.events.put(("protocol_error", str(exc)))
        except (OSError, UnicodeDecodeError) as exc:
            if self.connected:
                self.events.put(("connection_error", str(exc)))
        finally:
            was_connected = self.connected
            self.close(notify=False)
            if was_connected:
                self.events.put(("disconnected", None))

    def close(self, notify: bool = True) -> None:
        sock, self.sock = self.sock, None
        self.connected = False
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if notify:
            self.events.put(("disconnected", None))


class ChatWindow(tk.Tk):
    BG = "#c0c0c0"
    LIGHT = "#ffffff"
    SHADOW = "#808080"
    NAVY = "#000080"

    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("920x620")
        self.minsize(700, 460)
        self.configure(bg=self.BG)

        self.events: queue.Queue = queue.Queue()
        self.client = SocketClient(self.events)
        self.username = ""
        self.pending_downloads: dict[tuple[str, str | None], Path] = {}
        self.active_files_group: str | None = None

        self.host_var = tk.StringVar(value=DEFAULT_HOST)
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.user_var = tk.StringVar()
        self.target_var = tk.StringVar(value="Server")
        self.message_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Not connected")

        self._configure_style()
        self._build_menu()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._quit)
        self.after(75, self._drain_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "winnative" in style.theme_names():
            style.theme_use("winnative")
        elif "classic" in style.theme_names():
            style.theme_use("classic")
        style.configure("TFrame", background=self.BG)
        style.configure("TLabel", background=self.BG, font=("MS Sans Serif", 9))
        style.configure("TButton", font=("MS Sans Serif", 9), padding=(8, 2))
        style.configure("TNotebook", background=self.BG)
        style.configure("TNotebook.Tab", font=("MS Sans Serif", 9), padding=(7, 2))

    def _build_menu(self) -> None:
        menu = tk.Menu(self, tearoff=False, font=("MS Sans Serif", 9))

        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Connect...", command=self._toggle_connection, accelerator="Ctrl+N")
        file_menu.add_command(label="Disconnect", command=self._disconnect)
        file_menu.add_separator()
        file_menu.add_command(label="Send file...", command=self._send_file)
        file_menu.add_command(label="Download selected file...", command=self._download_file)
        file_menu.add_command(label="Reject / remove selected file", command=self._remove_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._quit, accelerator="Alt+F4")
        menu.add_cascade(label="File", menu=file_menu)

        chat_menu = tk.Menu(menu, tearoff=False)
        chat_menu.add_command(label="Message selected user", command=self._select_user)
        chat_menu.add_command(label="Message selected group", command=self._select_group)
        chat_menu.add_separator()
        chat_menu.add_command(label="Refresh lists", command=self._refresh_all, accelerator="F5")
        chat_menu.add_command(label="Clear transcript", command=self._clear_transcript)
        menu.add_cascade(label="Chat", menu=chat_menu)

        group_menu = tk.Menu(menu, tearoff=False)
        group_menu.add_command(label="Create...", command=self._create_group)
        group_menu.add_command(label="Join selected", command=self._join_group)
        group_menu.add_command(label="Leave selected", command=self._leave_group)
        group_menu.add_command(label="Remove selected...", command=self._remove_group)
        menu.add_cascade(label="Groups", menu=group_menu)

        tools_menu = tk.Menu(menu, tearoff=False)
        tools_menu.add_command(label="Ask Gemini", command=lambda: self.target_var.set("Gemini"))
        tools_menu.add_command(label="Summarize PDF...", command=self._summarize_pdf)
        tools_menu.add_command(label="Generate image...", command=self._generate_image)
        menu.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Command help", command=self._show_help)
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo(
            "About", f"{APP_NAME}\nClassic GUI for the NetworkSocket protocol."))
        menu.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menu)
        self.bind_all("<Control-n>", lambda _e: self._toggle_connection())
        self.bind_all("<F5>", lambda _e: self._refresh_all())

    def _build_ui(self) -> None:
        connection = ttk.LabelFrame(self, text="Connection", padding=7)
        connection.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(connection, text="Host:").grid(row=0, column=0, sticky="w")
        ttk.Entry(connection, textvariable=self.host_var, width=18).grid(row=0, column=1, padx=(3, 10))
        ttk.Label(connection, text="Port:").grid(row=0, column=2, sticky="w")
        ttk.Entry(connection, textvariable=self.port_var, width=7).grid(row=0, column=3, padx=(3, 10))
        ttk.Label(connection, text="User name:").grid(row=0, column=4, sticky="w")
        self.user_entry = ttk.Entry(connection, textvariable=self.user_var, width=18)
        self.user_entry.grid(row=0, column=5, padx=(3, 10))
        self.connect_button = ttk.Button(connection, text="Connect", command=self._toggle_connection)
        self.connect_button.grid(row=0, column=6)
        connection.columnconfigure(7, weight=1)
        self.user_entry.bind("<Return>", lambda _e: self._toggle_connection())

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=4)

        sidebar = ttk.Frame(pane, width=220)
        pane.add(sidebar, weight=0)
        self.notebook = ttk.Notebook(sidebar)
        self.notebook.pack(fill="both", expand=True)
        self.users_list = self._add_list_tab("Users")
        self.groups_list = self._add_list_tab("Groups")
        self.files_list = self._add_list_tab("Files")
        self.users_list.bind("<Double-1>", lambda _e: self._select_user())
        self.groups_list.bind("<Double-1>", lambda _e: self._select_group())
        self.files_list.bind("<Double-1>", lambda _e: self._download_file())
        for widget in (self.users_list, self.groups_list, self.files_list):
            widget.bind("<Button-3>", self._show_context_menu)

        transcript_frame = ttk.LabelFrame(pane, text="Conversation", padding=5)
        pane.add(transcript_frame, weight=1)
        self.transcript = tk.Text(
            transcript_frame, wrap="word", state="disabled", bg=self.LIGHT,
            fg="#000000", relief="sunken", bd=2, font=("Fixedsys", 10),
            padx=6, pady=6, selectbackground=self.NAVY,
        )
        scroll = ttk.Scrollbar(transcript_frame, command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=scroll.set)
        self.transcript.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.transcript.tag_configure("system", foreground="#000080")
        self.transcript.tag_configure("error", foreground="#800000")
        self.transcript.tag_configure("self", foreground="#008000")
        self.transcript.tag_configure("heading", font=("Fixedsys", 10, "bold"))

        composer = ttk.LabelFrame(self, text="Message", padding=7)
        composer.pack(fill="x", padx=8, pady=4)
        ttk.Label(composer, text="To:").grid(row=0, column=0, sticky="w")
        self.target_box = ttk.Combobox(
            composer, textvariable=self.target_var, state="readonly", width=23,
            values=("Server", "Gemini"),
        )
        self.target_box.grid(row=0, column=1, padx=(3, 8), sticky="ew")
        self.message_entry = ttk.Entry(composer, textvariable=self.message_var)
        self.message_entry.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        ttk.Button(composer, text="Send", command=self._send_message).grid(row=0, column=3)
        composer.columnconfigure(2, weight=1)
        self.message_entry.bind("<Return>", lambda _e: self._send_message())

        status = tk.Label(
            self, textvariable=self.status_var, anchor="w", relief="sunken", bd=1,
            bg=self.BG, font=("MS Sans Serif", 9), padx=5,
        )
        status.pack(fill="x", side="bottom", padx=8, pady=(0, 6))
        self._write("NetworkSocket GUI ready. Enter connection details and click Connect.\n", "system")
        self.user_entry.focus_set()

    def _add_list_tab(self, name: str) -> tk.Listbox:
        frame = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(frame, text=name)
        box = tk.Listbox(
            frame, bg=self.LIGHT, relief="sunken", bd=2, font=("MS Sans Serif", 9),
            selectmode="browse", exportselection=False, selectbackground=self.NAVY,
            selectforeground=self.LIGHT,
        )
        scroll = ttk.Scrollbar(frame, command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        box.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return box

    def _show_context_menu(self, event) -> None:
        widget: tk.Listbox = event.widget
        index = widget.nearest(event.y)
        if index >= 0:
            widget.selection_clear(0, "end")
            widget.selection_set(index)
        popup = tk.Menu(self, tearoff=False)
        if widget is self.users_list:
            self._select_user()
            popup.add_command(label="Message", command=self._select_user)
            popup.add_command(label="Send file...", command=self._send_file)
        elif widget is self.groups_list:
            self._select_group()
            popup.add_command(label="Message", command=self._select_group)
            popup.add_command(label="Join", command=self._join_group)
            popup.add_command(label="Leave", command=self._leave_group)
            popup.add_separator()
            popup.add_command(label="List files", command=self._list_group_files)
            popup.add_command(label="Send file...", command=self._send_file)
        else:
            popup.add_command(label="Download...", command=self._download_file)
            popup.add_command(label="Reject / remove", command=self._remove_file)
        popup.tk_popup(event.x_root, event.y_root)

    def _toggle_connection(self) -> None:
        if self.client.connected:
            self._disconnect()
            return
        host = self.host_var.get().strip()
        username = self.user_var.get().strip()
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Connection", "Port must be a number from 1 to 65535.")
            return
        if not host or not username:
            messagebox.showerror("Connection", "Host and user name are required.")
            return
        self.status_var.set(f"Connecting to {host}:{port}...")
        self.connect_button.configure(state="disabled")
        self.username = username
        threading.Thread(target=self.client.connect, args=(host, port, username), daemon=True).start()

    def _disconnect(self) -> None:
        if self.client.connected:
            self.client.send("logout", None)
        self.client.close(notify=False)
        self._set_disconnected("Disconnected")

    def _set_connected(self) -> None:
        self.connect_button.configure(text="Disconnect", state="normal")
        self.status_var.set(f"Connected as {self.username} to {self.host_var.get()}:{self.port_var.get()}")
        self._write(f"Connected as {self.username}.\n", "system")
        self._refresh_all()
        self.message_entry.focus_set()

    def _set_disconnected(self, message: str) -> None:
        self.connect_button.configure(text="Connect", state="normal")
        self.status_var.set(message)
        self.target_var.set("Server")

    def _selected(self, box: tk.Listbox) -> str | None:
        selection = box.curselection()
        return str(box.get(selection[0])) if selection else None

    def _select_user(self) -> None:
        name = self._selected(self.users_list)
        if name:
            self.target_var.set(f"User: {name}")
            self.message_entry.focus_set()

    def _select_group(self) -> None:
        name = self._selected(self.groups_list)
        if name:
            self.target_var.set(f"Group: {name}")
            self.message_entry.focus_set()

    def _send_message(self) -> None:
        message = self.message_var.get().strip()
        target = self.target_var.get()
        if not message:
            return
        if not self.client.connected:
            messagebox.showwarning("Send", "Connect to a server first.")
            return
        if target.startswith("User: "):
            name = target[6:]
            if self.client.send("direct_message", {"target_name": name, "msg": message}):
                self._write(f"You -> {name}: {message}\n", "self")
        elif target.startswith("Group: "):
            name = target[7:]
            if self.client.send("group_message", {"group": name, "msg": message}):
                self._write(f"You -> [{name}]: {message}\n", "self")
        elif target == "Gemini":
            if self.client.send("ask_gemini", {"prompt": message}):
                self._write(f"You -> Gemini: {message}\n", "self")
        else:
            messagebox.showinfo("Choose a recipient", "Double-click a user or group, or choose Gemini from the To list.")
            return
        self.message_var.set("")

    def _refresh_all(self) -> None:
        if self.client.connected:
            self.client.send("list_users", None)
            self.client.send("list_groups", None)
            self.client.send("list_direct_files", None)

    def _create_group(self) -> None:
        name = simpledialog.askstring("Create group", "Group name:", parent=self)
        if name and self.client.send("create_group", {"group": name.strip()}):
            self.after(250, self._refresh_all)

    def _join_group(self) -> None:
        name = self._selected(self.groups_list)
        if not name:
            messagebox.showinfo("Join group", "Select a group first.")
        else:
            self.client.send("join_group", {"group": name})

    def _leave_group(self) -> None:
        name = self._selected(self.groups_list)
        if not name:
            messagebox.showinfo("Leave group", "Select a group first.")
        else:
            self.client.send("leave_group", {"group": name})

    def _remove_group(self) -> None:
        name = self._selected(self.groups_list)
        if name and messagebox.askyesno("Remove group", f"Remove group '{name}' for everyone?"):
            self.client.send("remove_group", {"group": name})

    def _list_group_files(self) -> None:
        group = self._selected(self.groups_list)
        if group:
            self.target_var.set(f"Group: {group}")
            self.client.send("list_group_files", {"group": group})
            self.notebook.select(2)
            self.status_var.set(f"Showing files for group: {group}")

    def _send_file(self) -> None:
        target = self.target_var.get()
        if not (target.startswith("User: ") or target.startswith("Group: ")):
            messagebox.showinfo("Send file", "Select a user or group first.")
            return
        path_text = filedialog.askopenfilename(parent=self, title="Send file")
        if not path_text:
            return
        path = Path(path_text)
        try:
            data = path.read_bytes().hex()
        except OSError as exc:
            messagebox.showerror("Send file", str(exc))
            return
        if target.startswith("User: "):
            payload = {"target_name": target[6:], "file_name": path.name, "data": data}
            self.client.send("direct_send_file", payload)
        elif target.startswith("Group: "):
            payload = {"group": target[7:], "file_name": path.name, "data": data}
            self.client.send("group_send_file", payload)

    def _download_file(self) -> None:
        name = self._selected(self.files_list)
        if not name:
            messagebox.showinfo("Download", "Select a file first.")
            return
        group = self.active_files_group
        destination = filedialog.asksaveasfilename(parent=self, initialfile=name)
        if not destination:
            return
        self.pending_downloads[(name, group)] = Path(destination)
        if group:
            self.client.send("group_retrieve_file", {"group": group, "file_name": name})
        else:
            self.client.send("direct_retrieve_file", {"file_name": name})

    def _remove_file(self) -> None:
        name = self._selected(self.files_list)
        if not name:
            messagebox.showinfo("Remove file", "Select a file first.")
            return
        if self.active_files_group:
            self.client.send("group_remove_file", {"group": self.active_files_group, "file_name": name})
        else:
            self.client.send("direct_reject_file", {"file_name": name})
        self.after(250, self._refresh_all)

    def _summarize_pdf(self) -> None:
        path_text = filedialog.askopenfilename(parent=self, title="Summarize PDF", filetypes=[("PDF documents", "*.pdf")])
        if not path_text:
            return
        try:
            data = Path(path_text).read_bytes().hex()
        except OSError as exc:
            messagebox.showerror("Summarize PDF", str(exc))
            return
        self.client.send("pdf_sumarize", {"data": data})
        self._write(f"Sent {Path(path_text).name} for summarization.\n", "system")

    def _generate_image(self) -> None:
        prompt = simpledialog.askstring("Generate image", "Describe the image:", parent=self)
        if not prompt:
            return
        destination = filedialog.asksaveasfilename(
            parent=self, title="Save generated image", defaultextension=".png",
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
        )
        if not destination:
            return
        name = Path(destination).name
        self.pending_downloads[(name, None)] = Path(destination)
        self.client.send("generate_image", {"file_name": name, "prompt": prompt})

    def _show_help(self) -> None:
        messagebox.showinfo(
            "Command help",
            "Double-click a user or group to make it the message destination.\n"
            "Press Enter in the message field to send.\n\n"
            "Use the File, Chat, Groups, and Tools menus—or right-click a list item—"
            "for all other commands. Press F5 to refresh the lists.",
        )

    def _clear_transcript(self) -> None:
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")

    def _write(self, text: str, tag: str | None = None) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", text, tag or ())
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    @staticmethod
    def _address(data) -> str:
        if isinstance(data, (list, tuple)) and len(data) >= 2:
            return f"{data[0]}:{data[1]}"
        return str(data or "unknown")

    def _replace_list(self, box: tk.Listbox, values) -> None:
        box.delete(0, "end")
        for value in values:
            box.insert("end", value)

    def _update_targets(self) -> None:
        values = ["Server", "Gemini"]
        values += [f"User: {self.users_list.get(i)}" for i in range(self.users_list.size())]
        values += [f"Group: {self.groups_list.get(i)}" for i in range(self.groups_list.size())]
        self.target_box.configure(values=values)

    def _handle_response(self, response: dict) -> None:
        status = str(response.get("status", ""))
        data = response.get("data")
        if status == "010":
            self.client.close(notify=False)
            self._set_disconnected("Login rejected")
            messagebox.showerror("Login", str(data))
        elif status == "011":
            self._set_connected()
        elif status == "101":
            names = [item[0] for item in (data or []) if item and item[0] != self.username]
            self._replace_list(self.users_list, names)
            self._update_targets()
        elif status == "111":
            self._replace_list(self.groups_list, data or [])
            self._update_targets()
        elif status in {"121", "131"}:
            self.active_files_group = None if status == "121" else (
                self.target_var.get()[7:] if self.target_var.get().startswith("Group: ") else None
            )
            self._replace_list(self.files_list, data or [])
        elif status == "201" and isinstance(data, dict):
            self._write(f"{data.get('from')}@{self._address(data.get('addr'))}: {data.get('msg', '')}\n")
        elif status == "331" and isinstance(data, dict):
            self._write(f"[{data.get('group')}] {data.get('from')}: {data.get('msg', '')}\n")
        elif status in {"401", "431"} and isinstance(data, dict):
            group = f" in [{data.get('group')}]" if data.get("group") else ""
            self._write(f"{data.get('from')} sent {data.get('file_name')}{group}.\n", "system")
            self._refresh_all()
        elif status in {"411", "441", "511"} and isinstance(data, dict):
            group = self.active_files_group if status == "441" else None
            key = (str(data.get("file_name")), group)
            destination = self.pending_downloads.pop(key, None)
            if destination is None:
                # The user may have changed the visible file scope while the
                # response was in flight. Filename is unique within a scope.
                matching_key = next(
                    (item for item in self.pending_downloads if item[0] == str(data.get("file_name"))),
                    None,
                )
                if matching_key is not None:
                    destination = self.pending_downloads.pop(matching_key)
            if destination is None and status == "511":
                destination = self.pending_downloads.pop((str(data.get("file_name")), None), None)
            if destination:
                try:
                    import base64
                    raw = base64.b64decode(data.get("data", "")) if status == "511" else bytes.fromhex(data.get("data", ""))
                    destination.write_bytes(raw)
                    self._write(f"Saved {destination}.\n", "system")
                except (OSError, ValueError) as exc:
                    messagebox.showerror("Save file", str(exc))
        elif status in {"501", "521"}:
            label = "Gemini summary" if status == "521" else "Gemini"
            self._write(f"{label}:\n", "heading")
            self._write(f"{data}\n")
        else:
            is_error = status in {"000", "200", "300", "310", "320", "330", "340", "400", "410", "420", "430", "440", "450", "500", "510", "520"}
            if isinstance(data, dict):
                text = data.get("msg", json.dumps(data))
            else:
                text = str(data)
            self._write(f"Server [{status}]: {text}\n", "error" if is_error else "system")
            if not is_error and status in {"301", "311", "321", "341", "421", "451"}:
                self.after(150, self._refresh_all)

    def _drain_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "response":
                    self._handle_response(value)
                elif kind == "connection_error":
                    self._set_disconnected("Connection failed")
                    self._write(f"Connection error: {value}\n", "error")
                elif kind == "protocol_error":
                    self._write(f"Protocol error: {value}\n", "error")
                elif kind == "disconnected":
                    self._set_disconnected("Server disconnected")
                    self._write("Server disconnected.\n", "error")
        except queue.Empty:
            pass
        self.after(75, self._drain_events)

    def _quit(self) -> None:
        if self.client.connected:
            self.client.send("logout", None)
        self.client.close(notify=False)
        self.destroy()


def main() -> None:
    ChatWindow().mainloop()


if __name__ == "__main__":
    main()
