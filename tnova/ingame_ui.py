"""Small picker opened by paused Prequel F5/F9; shares the launcher state code."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import logging
import tkinter as tk
from tkinter import ttk, messagebox

from .sessions import Sessions


class Picker:

    def __init__(self, root, home, mode):
        self.root, self.mode = root, mode
        self.sessions = Sessions(home)
        self.game = self.sessions.paused_prequel()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        root.title(
            'Terra Nova — ' + ('Save Prequel state' if mode == 'save' else 'Load Prequel state')
        )
        root.geometry('680x365')
        root.minsize(640, 320)
        root.protocol('WM_DELETE_WINDOW', self.close)
        body = ttk.Frame(root, padding=20)
        body.pack(fill='both', expand=True)
        ttk.Label(
            body,
            text='Prequel • ' + ('Save state' if mode == 'save' else 'Load state'),
            font=('Segoe UI', 17, 'bold')
        ).pack(
            anchor='w', pady=(0, 12)
        )
        self.controls = []
        if mode == 'save':
            ttk.Label(
                body, text='Keep this exact moment. The game will remain paused.'
            ).pack(anchor='w')
            ttk.Label(body, text='Save name:').pack(anchor='w', pady=(16, 4))
            self.name = ttk.Entry(body)
            self.name.insert(0, 'Prequel — ' + datetime.now().strftime('%Y-%m-%d %H:%M'))
            self.name.pack(fill='x')
            self.name.focus_set()
            self.name.select_range(0, 'end')
            self.controls.append(self.name)
            ttk.Label(
                body, text='Each save creates a new state, even if the name already exists.'
            ).pack(
                anchor='w', pady=8
            )
        else:
            ttk.Label(
                body, text='Loading restarts the game window. Unsaved progress will be replaced.'
            ).pack(anchor='w')
            self.rows = [s for s in self.sessions.states() if s.campaign == 'prequel']
            self.table = ttk.Treeview(body, columns=('date', ), selectmode='browse', height=6)
            self.table.heading('#0', text='Prequel state')
            self.table.heading('date', text='Saved (local time)')
            self.table.column('#0', width=360)
            self.table.column('date', width=170, stretch=False)
            self.table.pack(fill='both', expand=True, pady=8)
            for i, row in enumerate(self.rows):
                stamp = datetime.fromisoformat(row.saved_at
                                               ).astimezone().strftime('%Y-%m-%d %H:%M:%S')
                self.table.insert('', 'end', iid=str(i), text=row.title, values=(stamp, ))
            self.controls.append(self.table)
        self.status = tk.StringVar(
            value='Ready.'
            if mode == 'save' or self.rows else 'No Prequel states saved in this installation.'
        )
        ttk.Label(body, textvariable=self.status, wraplength=620).pack(anchor='w', pady=8)
        line = ttk.Frame(body)
        line.pack(side='bottom', fill='x')
        self.cancel = ttk.Button(line, text='Cancel', command=self.close)
        self.cancel.pack(side='right')
        self.go = ttk.Button(
            line, text='Save' if mode == 'save' else 'Load selected state', command=self.perform
        )
        self.go.pack(side='right', padx=8)
        self.controls += [self.go, self.cancel]
        root.bind('<Escape>', lambda event: self.close())

    def perform(self):
        if self.pending:
            return
        if self.mode == 'save':
            title = self.name.get()
            operation = lambda: self.sessions.save(title, expected=self.game)
        else:
            selected = self.table.selection()
            if not selected:
                self.status.set('Select a state first.')
                return
            folder = self.rows[int(selected[0])].folder
            operation = lambda: self.sessions.load_in_game(folder, self.game)
        for control in self.controls:
            control.state(['disabled'])
        self.status.set(
            'Saving…' if self.mode == 'save' else 'Checking the state before closing the game…'
        )
        self.pending = self.pool.submit(operation)
        self.root.after(100, self.poll)

    def poll(self):
        if not self.pending.done():
            self.root.after(100, self.poll)
            return
        future, self.pending = self.pending, None
        try:
            result = future.result()
            logging.info('In-game %s complete: %s', self.mode, result)
            self.close()
        except Exception as exc:
            logging.exception('In-game state operation failed')
            for control in self.controls:
                control.state(['!disabled'])
            self.status.set(str(exc))
            messagebox.showerror('Terra Nova', str(exc), parent=self.root)

    def close(self):
        if self.pending:
            self.status.set('Please wait for the current operation to finish.')
            return
        self.pool.shutdown(wait=False)
        self.root.destroy()


def run(home, mode):
    """A separate picker lock stops repeated keypresses opening parallel dialogs."""
    import msvcrt
    from . import state_core as core
    home = Path(home).resolve()
    core.validate_home(home)
    logging.basicConfig(
        filename=home / 'launcher.log',
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        encoding='utf-8'
    )
    with core.inside(home, '.state-picker.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'\0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        root = tk.Tk()
        try:
            Picker(root, home, mode)
            root.mainloop()
        except Exception as exc:
            logging.exception('Cannot open in-game picker')
            messagebox.showerror('Terra Nova', str(exc), parent=root)
            root.destroy()
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
