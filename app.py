import asyncio
import platform
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import requests

LRCLIB = "https://lrclib.net/api/get"

class Track:
    def __init__(self, artist="", title="", album="", duration=0):
        self.artist = artist
        self.title = title
        self.album = album
        self.duration = duration

    @property
    def key(self):
        return (self.artist.strip().lower(), self.title.strip().lower())

def linux_track():
    # Prefer playerctl when available: it talks to MPRIS and does not capture audio.
    try:
        p = subprocess.run(
            ["playerctl", "-p", "spotify", "metadata",
             "--format", "{{artist}}\t{{title}}\t{{album}}\t{{duration(mpris)}}"],
            capture_output=True, text=True, timeout=2
        )
        if p.returncode == 0 and p.stdout.strip():
            parts = p.stdout.strip().split("\t")
            if len(parts) >= 2:
                artist, title = parts[0], parts[1]
                album = parts[2] if len(parts) > 2 else ""
                dur = 0
                if len(parts) > 3:
                    try: dur = int(float(parts[3]) / 1000)
                    except Exception: pass
                if artist and title:
                    return Track(artist, title, album, dur)
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # Fallback: direct MPRIS over D-Bus using dbus-send, no Python dbus package required.
    try:
        names = subprocess.check_output(
            ["bash", "-lc", "busctl --user list 2>/dev/null | awk '$1 ~ /^org\\.mpris\\.MediaPlayer2\\./ {print $1}'"],
            text=True, timeout=2
        ).splitlines()
        names = [n.strip() for n in names if n.strip()]
        spotify = next((n for n in names if n == "org.mpris.MediaPlayer2.spotify"), None)
        service = spotify or (names[0] if names else None)
        if not service:
            return None
        out = subprocess.check_output(
            ["busctl", "--user", "get-property", service,
             "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Metadata"],
            text=True, timeout=2
        )
        # busctl's variant dump is intentionally parsed conservatively.
        title_m = re.search(r'"xesam:title"\s+v\s+s\s+"([^"]*)"', out)
        artist_m = re.search(r'"xesam:artist"\s+v\s+as\s+\d+\s+"([^"]*)"', out)
        if title_m and artist_m:
            return Track(artist_m.group(1), title_m.group(1))
    except Exception:
        pass
    return None

def windows_track():
    # Uses Windows Runtime media-session metadata. No microphone/system-audio capture.
    try:
        import asyncio
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
        async def get():
            manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
            session = manager.get_current_session()
            if session is None:
                return None
            props = await session.try_get_media_properties_async()
            artist = str(props.artist or "").strip()
            title = str(props.title or "").strip()
            album = str(props.album_title or "").strip()
            if artist and title:
                return Track(artist, title, album)
            return None
        return asyncio.run(get())
    except Exception:
        return None

def current_track():
    if platform.system() == "Windows":
        return windows_track()
    if platform.system() == "Linux":
        return linux_track()
    return None

def fetch_lyrics(track):
    try:
        r = requests.get(
            LRCLIB,
            params={"artist_name": track.artist, "track_name": track.title},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None

def parse_lrc(text):
    rows = []
    if not text:
        return rows
    rx = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")
    for line in text.splitlines():
        m = rx.match(line.strip())
        if m:
            seconds = int(m.group(1))*60 + float(m.group(2))
            rows.append((seconds, m.group(3).strip()))
    rows.sort()
    return rows

class App:
    BG = "#0d0f14"
    PANEL = "#151922"
    FG = "#f4f5f7"
    MUTED = "#969cab"
    ACCENT = "#a78bfa"
    LINE = "#292e3a"

    def __init__(self, root):
        self.root = root
        self.root.title("Lyrics — Now Playing")
        self.root.geometry("1080x760")
        self.root.minsize(820, 600)
        self.root.configure(bg=self.BG)
        self.running = True
        self.last_key = None
        self.current = None
        self.synced = []
        self.current_line = -1
        self.build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self.monitor, daemon=True).start()
        self.tick()

    def build(self):
        header = tk.Frame(self.root, bg=self.BG)
        header.pack(fill="x", padx=34, pady=(28, 16))
        tk.Label(header, text="  ●  EN ÉCOUTE  ", bg="#241d38", fg=self.ACCENT,
                 font=("TkDefaultFont", 9, "bold"), padx=8, pady=5).pack(anchor="w")
        self.title_label = tk.Label(header, text="Aucun morceau détecté", bg=self.BG,
                                    fg=self.FG, font=("TkDefaultFont", 25, "bold"), anchor="w")
        self.title_label.pack(fill="x", pady=(12, 2))
        self.artist_label = tk.Label(header, text="Lance un morceau dans Spotify ou ton lecteur multimédia",
                                     bg=self.BG, fg=self.MUTED, font=("TkDefaultFont", 13), anchor="w")
        self.artist_label.pack(fill="x")

        card = tk.Frame(self.root, bg=self.PANEL, highlightthickness=1, highlightbackground=self.LINE)
        card.pack(fill="both", expand=True, padx=28, pady=(4, 28))

        bar = tk.Frame(card, bg=self.PANEL)
        bar.pack(fill="x", padx=28, pady=(20, 0))
        tk.Label(bar, text="MÉTADONNÉES SYSTÈME • AUCUNE CAPTURE AUDIO", bg=self.PANEL,
                 fg=self.MUTED, font=("TkDefaultFont", 9)).pack(side="left")
        self.section = tk.Label(bar, text="", bg=self.PANEL, fg=self.ACCENT,
                                font=("TkDefaultFont", 9, "bold"))
        self.section.pack(side="right")

        area = tk.Frame(card, bg=self.PANEL)
        area.pack(fill="both", expand=True, padx=28, pady=18)
        self.canvas = tk.Canvas(area, bg=self.PANEL, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        sb.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=sb.set)
        self.inner = tk.Frame(self.canvas, bg=self.PANEL)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        # Défilement à la molette : Windows/macOS + Linux.
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel)
        self.canvas.bind("<Button-5>", self.on_mousewheel)
        self.inner.bind("<MouseWheel>", self.on_mousewheel)
        self.inner.bind("<Button-4>", self.on_mousewheel)
        self.inner.bind("<Button-5>", self.on_mousewheel)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))

        self.empty = tk.Label(self.inner, text="Les paroles apparaîtront ici\n\ndès qu'un morceau sera détecté.",
                              bg=self.PANEL, fg=self.MUTED, font=("TkDefaultFont", 15), justify="center")
        self.empty.pack(pady=180)

        footer = tk.Frame(self.root, bg=self.BG)
        footer.pack(fill="x", padx=34, pady=(0, 18))
        self.status = tk.Label(footer, text="Recherche du lecteur…", bg=self.BG, fg=self.MUTED,
                               font=("TkDefaultFont", 9), anchor="w")
        self.status.pack(side="left")
        tk.Label(footer, text="LRCLIB • paroles synchronisées si disponibles", bg=self.BG,
                 fg="#686d78", font=("TkDefaultFont", 9)).pack(side="right")

    def clear(self):
        for w in self.inner.winfo_children(): w.destroy()

    def show_track(self, tr):
        self.title_label.config(text=tr.title)
        self.artist_label.config(text=tr.artist + (f"  •  {tr.album}" if tr.album else ""))
        self.status.config(text="Morceau détecté • récupération des paroles…")
        self.section.config(text="")
        self.clear()
        tk.Label(self.inner, text="Recherche des paroles…", bg=self.PANEL, fg=self.MUTED,
                 font=("TkDefaultFont", 14)).pack(pady=180)

    def on_mousewheel(self, event):
        """Défilement vertical des paroles à la molette."""
        if getattr(event, "num", None) == 4:
            amount = -3
        elif getattr(event, "num", None) == 5:
            amount = 3
        else:
            amount = -max(1, int(event.delta / 40))
        self.canvas.yview_scroll(amount, "units")
        return "break"

    def show_lyrics(self, synced, plain):
        self.synced = synced
        self.clear()
        if synced:
            lines = [x[1].strip() for x in synced]
            for i, line in enumerate(lines):
                if not line:
                    tk.Frame(self.inner, height=12, bg=self.PANEL).pack(fill="x")
                    continue
                is_head = line.startswith("[") and line.endswith("]") and len(line) < 40
                lbl = tk.Label(self.inner, text=line[1:-1].upper() if is_head else line,
                               bg=self.PANEL, fg=self.ACCENT if is_head else self.MUTED,
                               font=("TkDefaultFont", 9, "bold") if is_head else ("TkDefaultFont", 16),
                               anchor="w", justify="left", padx=14, pady=6)
                lbl.pack(fill="x", pady=(12 if is_head else 1, 1))
                lbl._lyric_index = i
            self.status.config(text="Paroles synchronisées chargées")
        elif plain:
            for line in plain.splitlines():
                if not line.strip():
                    tk.Frame(self.inner, height=12, bg=self.PANEL).pack(fill="x")
                else:
                    tk.Label(self.inner, text=line, bg=self.PANEL, fg=self.MUTED,
                             font=("TkDefaultFont", 16), anchor="w", padx=14, pady=6).pack(fill="x")
            self.status.config(text="Paroles chargées")
        else:
            tk.Label(self.inner, text="Paroles introuvables.", bg=self.PANEL, fg=self.MUTED,
                     font=("TkDefaultFont", 14)).pack(pady=180)

    def monitor(self):
        while self.running:
            tr = current_track()
            key = tr.key if tr else None
            if key and key != self.last_key:
                self.last_key = key
                self.current = tr
                self.root.after(0, lambda t=tr: self.show_track(t))
                data = fetch_lyrics(tr)
                self.root.after(0, lambda d=data: self.show_lyrics(
                    parse_lrc((d or {}).get("syncedLyrics", "")),
                    (d or {}).get("plainLyrics", "")))
            elif not key:
                self.root.after(0, lambda: self.status.config(
                    text="Aucun lecteur multimédia compatible détecté"))
            time.sleep(2)

    def tick(self):
        if self.running: self.root.after(500, self.tick)

    def close(self):
        self.running = False
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
