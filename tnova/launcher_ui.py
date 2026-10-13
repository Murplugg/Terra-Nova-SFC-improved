"""Small development UI. Long operations run off the Tk event thread."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import logging
import tkinter as tk
from tkinter import ttk, messagebox

from .sessions import Sessions


class Launcher:

    def __init__(self, root, home):
        self.root = root
        self.sessions = Sessions(home)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.rows = []
        self.last_error = None
        root.title('Terra Nova — portable launcher (development)')
        root.geometry('780x490')
        root.minsize(660, 430)
        root.protocol('WM_DELETE_WINDOW', self.close)
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Terra Nova', font=('Segoe UI', 21, 'bold')).pack(anchor='w')
        ttk.Label(
            outer, text='Retail and Prequel share the in-game main menu.'
        ).pack(
            anchor='w', pady=(0, 12)
        )
        self.play = ttk.Button(
            outer, text='Play', command=lambda: self.start('Starting game…', self.sessions.play)
        )
        self.play.pack(anchor='w')
        ttk.Label(
            outer, text='Saved states', font=('Segoe UI', 11, 'bold')
        ).pack(
            anchor='w', pady=(18, 5)
        )
        self.table = ttk.Treeview(
            outer, columns=('campaign', 'date'), height=7, selectmode='browse'
        )
        self.table.heading('#0', text='Name')
        self.table.heading('campaign', text='Campaign')
        self.table.heading('date', text='Saved (local time)')
        self.table.column('#0', width=310, minwidth=170)
        self.table.column('campaign', width=95, stretch=False)
        self.table.column('date', width=180, stretch=False)
        self.table.pack(fill='both', expand=True)
        line = ttk.Frame(outer)
        line.pack(fill='x', pady=8)
        self.load = ttk.Button(line, text='Load selected state', command=self.load_selected)
        self.load.pack(side='left')
        self.refresh = ttk.Button(line, text='Refresh', command=self.refresh_states)
        self.refresh.pack(side='left', padx=8)
        save_line = ttk.Frame(outer)
        save_line.pack(fill='x')
        ttk.Label(save_line, text='Name:').pack(side='left')
        self.name = ttk.Entry(save_line)
        self.name.insert(0, 'Saved game')
        self.name.pack(side='left', fill='x', expand=True, padx=8)
        self.save = ttk.Button(save_line, text='Save paused game', command=self.save_game)
        self.save.pack(side='left')
        ttk.Label(
            outer,
            text='Pause during a mission before saving. Exit the current game before loading.'
        ).pack(
            anchor='w', pady=(9, 2)
        )
        self.status = tk.StringVar(value='Ready. Development build — use your own saved states.')
        ttk.Label(outer, textvariable=self.status, wraplength=715).pack(anchor='w')
        self.buttons = (self.play, self.load, self.refresh, self.save, self.name)
        self.refresh_states()

    def refresh_states(self):
        from datetime import datetime
        try:
            selected = self.table.selection()
            old = self.rows[int(selected[0])].folder if selected else None
            self.rows = self.sessions.states()
            self.table.delete(*self.table.get_children())
            for i, row in enumerate(self.rows):
                date = datetime.fromisoformat(row.saved_at
                                              ).astimezone().strftime('%Y-%m-%d %H:%M:%S')
                self.table.insert(
                    '',
                    'end',
                    iid=str(i),
                    text=row.title,
                    values=('Prequel' if row.campaign == 'prequel' else 'Retail', date)
                )
                if row.folder == old:
                    self.table.selection_set(str(i))
        except Exception as exc:
            self.fail(exc)

    def save_game(self):
        title = self.name.get()
        self.start('Checking installation and saving…', lambda: self.sessions.save(title))

    def load_selected(self):
        selection = self.table.selection()
        if not selection:
            self.status.set('Select a saved state first.')
            return
        folder = self.rows[int(selection[0])].folder
        self.start('Checking and loading saved state…', lambda: self.sessions.load(folder))

    def start(self, message, operation):
        if self.pending:
            return
        for widget in self.buttons:
            widget.state(['disabled'])
        self.status.set(message)
        self.pending = self.pool.submit(operation)
        self.root.after(100, self.poll)

    def poll(self):
        if not self.pending.done():
            self.root.after(100, self.poll)
            return
        future, self.pending = self.pending, None
        for widget in self.buttons:
            widget.state(['!disabled'])
        try:
            result = future.result()
            self.status.set(
                'State saved. The game remains paused.' if isinstance(result, dict)
                and 'snapshot' in result else 'Game started. Use the game window to continue.'
            )
            self.refresh_states()
        except Exception as exc:
            self.fail(exc)

    def fail(self, error):
        self.last_error = error
        logging.exception('Launcher operation failed', exc_info=error)
        message = str(error)
        if 'paused mission' in message or 'Pause' in message:
            message = 'Pause the game during a mission, then try saving again.'
        self.status.set(message)
        messagebox.showerror('Terra Nova', message, parent=self.root)

    def close(self):
        if self.pending:
            self.status.set(
                'Please wait for the current operation to finish before closing the launcher.'
            )
            return
        self.pool.shutdown(wait=False)
        self.root.destroy()


def run(home):
    logging.basicConfig(
        filename=Path(home) / 'launcher.log',
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        encoding='utf-8'
    )
    root = tk.Tk()
    try:
        Launcher(root, home)
    except Exception as exc:
        messagebox.showerror('Terra Nova', str(exc), parent=root)
        root.destroy()
        raise
    root.mainloop()
