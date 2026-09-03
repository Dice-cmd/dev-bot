"""Private local tabbed control panel for prank features."""

import asyncio
import tkinter as tk
from tkinter import messagebox, ttk


class ControlPanel:
    def __init__(self, bot):
        self.bot = bot
        self.window = None
        self.guild_box = None
        self.notebook = None
        self.status = None
        self.guilds = []
        self.targets = []
        self.sounds = []
        self.tab_data = {}

    def start(self):
        import threading

        threading.Thread(target=self._run, name="control-panel", daemon=True).start()

    def _run(self):
        self.window = tk.Tk()
        self.window.title("Discord Prank Controls")
        self.window.geometry("640x620")
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)

        top = ttk.Frame(self.window, padding=(16, 16, 16, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Server to prank").pack(side="left")
        self.guild_box = ttk.Combobox(top, state="readonly", width=42)
        self.guild_box.pack(side="left", padx=(10, 0), fill="x", expand=True)
        self.guild_box.bind("<<ComboboxSelected>>", lambda event: self._refresh_tabs())

        controls = ttk.Frame(self.window, padding=(16, 0, 16, 8))
        controls.pack(fill="x")
        ttk.Button(controls, text="+ Sound prank tab", command=lambda: self._add_tab("sound")).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="+ Text prank tab", command=lambda: self._add_tab("text")).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="+ Leave-in-style tab", command=lambda: self._add_tab("leave")).pack(side="left")

        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.status = ttk.Label(self.window, text="Choose a server, then add a prank tab", padding=16)
        self.status.pack(fill="x")

        self._refresh_guilds()
        self.window.mainloop()

    def _run_async(self, coroutine, on_success=None):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.bot.loop)

        def finished(result):
            try:
                value = result.result()
                if on_success:
                    self.window.after(0, lambda: on_success(value))
            except Exception as error:
                self.window.after(0, lambda: self._set_status(f"Error: {error}"))

        future.add_done_callback(finished)

    def _refresh_guilds(self):
        self.guilds = list(self.bot.guilds)
        self.guild_box["values"] = [f"{guild.name} ({guild.id})" for guild in self.guilds]
        if self.guilds:
            self.guild_box.current(0)

    def _selected_guild(self):
        index = self.guild_box.current()
        return self.guilds[index] if index >= 0 else None

    def _refresh_tabs(self):
        for tab_id in self.notebook.tabs():
            tab = self.window.nametowidget(tab_id)
            self._close_tab(tab, self.tab_data.pop(tab_id, {}), forget=False)
        self._set_status("Server selected. Add a prank tab.")

    def _add_tab(self, mode):
        guild = self._selected_guild()
        if not guild:
            self._set_status("Choose a server first")
            return
        if any(data.get("mode") == mode for data in self.tab_data.values()):
            category = {"sound": "Sound", "text": "Text", "leave": "Leave-in-style"}[mode]
            self.status.configure(text=f"Warning: You already opened a {category} prank tab", foreground="red")
            return
        tab = ttk.Frame(self.notebook, padding=16)
        title = {"sound": "Sound", "text": "Text", "leave": "Leave"}[mode]
        self.notebook.add(tab, text=f"{title} prank")
        self.notebook.select(tab)
        tab_data = {"guild": guild, "mode": mode}
        self.tab_data[str(tab)] = tab_data
        self._add_close_button(tab, tab_data)

        if mode == "leave":
            self._build_leave_tab(tab, tab_data)
        else:
            self._build_target_tab(tab, tab_data)

    def _add_close_button(self, tab, tab_data):
        ttk.Button(tab, text="Close tab", command=lambda: self._close_tab(tab, tab_data)).pack(anchor="e")

    def _close_tab(self, tab, tab_data, forget=True):
        guild = tab_data["guild"]
        sound_cog = self.bot.get_cog("SoundPrank")
        text_cog = self.bot.get_cog("TextPrank")
        if tab_data.get("mode") == "sound" and tab_data.get("active") and tab_data.get("target"):
            self._run_async(sound_cog.gui_toggle_autoprank(guild, tab_data["target"], tab_data.get("sound_ids", [])))
        elif tab_data.get("mode") == "text" and tab_data.get("active"):
            for target in tab_data.get("targets", []):
                self._run_async(text_cog.gui_toggle(guild, [target]))
        if forget:
            self.tab_data.pop(str(tab), None)
            self.notebook.forget(tab)

    def _build_target_tab(self, tab, tab_data):
        targets = [member for member in tab_data["guild"].members if not member.bot]
        tab_data["targets"] = targets

        if tab_data["mode"] == "sound":
            ttk.Label(tab, text="Target member").pack(anchor="w")
            target_box = ttk.Combobox(tab, state="readonly")
            target_box.pack(fill="x", pady=(4, 14))
            target_box["values"] = [f"{member.display_name} ({member.id})" for member in targets]
            if targets:
                target_box.current(0)
            tab_data["target_box"] = target_box
            ttk.Label(tab, text="Sounds (Ctrl-click to choose multiple)").pack(anchor="w")
            sound_list = tk.Listbox(tab, selectmode=tk.MULTIPLE, height=14, exportselection=False)
            sound_list.pack(fill="both", expand=True, pady=(4, 14))
            tab_data["sound_list"] = sound_list
            self._run_async(self.bot.get_cog("SoundPrank").gui_get_sounds(tab_data["guild"]), lambda sounds: self._fill_sound_list(tab_data, sounds))
            ttk.Button(tab, text="Play selected sound", command=lambda: self._play_selected(tab_data)).pack(fill="x", pady=2)
            ttk.Button(tab, text="Toggle sound prank", command=lambda: self._toggle_sound(tab_data)).pack(fill="x", pady=2)
        else:
            target_list = tk.Listbox(tab, selectmode=tk.MULTIPLE, height=14, exportselection=False)
            target_list.pack(fill="both", expand=True, pady=(4, 14))
            tab_data["target_list"] = target_list
            ttk.Label(tab, text="Each selected member's message has a 25% chance of deletion").pack(anchor="w", pady=(0, 14))
            for member in targets:
                target_list.insert(tk.END, f"{member.display_name} ({member.id})")
            ttk.Button(tab, text="Toggle text prank", command=lambda: self._toggle_text(tab_data)).pack(fill="x", pady=2)

    def _build_leave_tab(self, tab, tab_data):
        ttk.Label(tab, text="Target member").pack(anchor="w")
        target_box = ttk.Combobox(tab, state="readonly")
        target_box.pack(fill="x", pady=(4, 14))
        targets = [member for member in tab_data["guild"].members if not member.bot]
        target_box["values"] = [f"{member.display_name} ({member.id})" for member in targets]
        if targets:
            target_box.current(0)
        tab_data["targets"] = targets
        tab_data["target_box"] = target_box

        ttk.Label(tab, text="The selected member must be in a voice channel.").pack(anchor="w", pady=(8, 14))
        ttk.Button(tab, text="Start leave-in-style", command=lambda: self._leave(tab_data)).pack(fill="x")

    def _fill_sound_list(self, tab_data, sounds):
        self.sounds = sounds
        tab_data["sounds"] = sounds
        tab_data["sound_list"].delete(0, tk.END)
        for sound in sounds:
            tab_data["sound_list"].insert(tk.END, f"{sound[1]} ({sound[0]})")
        self._set_status(f"Loaded {len(sounds)} sounds")

    def _selected_target(self, tab_data):
        index = tab_data["target_box"].current()
        return tab_data["targets"][index] if index >= 0 else None

    def _play_selected(self, tab_data):
        target = self._selected_target(tab_data)
        selected = tab_data["sound_list"].curselection()
        if not target or not selected:
            self._set_status("Choose a target and sound")
            return
        sound_id = tab_data["sounds"][selected[0]][0]
        self._run_async(self.bot.get_cog("SoundPrank").gui_play_sound(tab_data["guild"], sound_id), lambda _: self._set_status("Sound played"))

    def _toggle_sound(self, tab_data):
        target = self._selected_target(tab_data)
        sound_ids = [tab_data["sounds"][index][0] for index in tab_data["sound_list"].curselection()]
        if target:
            tab_data["target"] = target
            tab_data["sound_ids"] = sound_ids
            self._run_async(
                self.bot.get_cog("SoundPrank").gui_toggle_autoprank(tab_data["guild"], target, sound_ids),
                lambda value: self._mark_active(tab_data, value),
            )

    def _toggle_text(self, tab_data):
        selected_indexes = tab_data["target_list"].curselection()
        targets = [tab_data["targets"][index] for index in selected_indexes]
        if not targets:
            self._set_status("Choose at least one target")
            return
        tab_data["target"] = targets[0]
        tab_data["targets"] = targets
        self._run_async(
            self.bot.get_cog("TextPrank").gui_toggle(tab_data["guild"], targets),
            lambda value: self._mark_active(tab_data, value),
        )

    def _leave(self, tab_data):
        target = self._selected_target(tab_data)
        if not target:
            self._set_status("Choose a target")
            return
        confirmed = messagebox.askyesno(
            "Confirm leave-in-style",
            "This will kick everyone out of the call!\n\nDo you want to continue?",
            parent=self.window,
        )
        if confirmed:
            self._run_async(
                self.bot.get_cog("LeaveStyle").gui_start(tab_data["guild"], target),
                self._set_status,
            )

    def _set_status(self, text):
        if self.status:
            self.status.configure(text=text, foreground="black")

    def _mark_active(self, tab_data, status):
        tab_data["active"] = "now on" in status.lower()
        self._set_status(status)