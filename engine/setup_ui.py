"""Folder-picker front end for the same verified installer used at the command line."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import os
from queue import Empty, Queue
import struct
import sys
import tempfile
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from install_portable import install


FIELDS = (
    ('retail', 'Retail game folder (TNOVA)'),
    ('download_demo', 'Downloadable demo folder (TNDEMO1)'),
    ('cd_demo', 'CD demo folder (TNDEMO2)'),
    ('cd_image', 'Retail CD image (TNF108.ISO)'),
    ('destination', 'New TNova Native folder'),
    ('tools_cache', 'Build tools folder'),
)


def setup_options(values, copy_data=False):
    """Catch incomplete selections early; authoritative checks stay in install()."""
    options = {}
    for name, label in FIELDS:
        text = values[name].strip()
        if not text:
            raise ValueError('Choose ' + label.lower() + '.')
        options[name] = Path(text).expanduser().resolve()
    for name in ('retail', 'download_demo', 'cd_demo'):
        if not options[name].is_dir():
            raise ValueError('Folder not found: ' + str(options[name]))
    if not options['cd_image'].is_file():
        raise ValueError('CD image not found: ' + str(options['cd_image']))
    options['data_mode'] = 'copy' if copy_data else 'shared'
    return options


def storage_summary(result):
    data = result['storage']
    mib = 1024 * 1024
    return (f"Shared {data['linked_bytes'] / mib:,.0f} MiB of game data; "
            f"wrote {data['written_bytes'] / mib:,.0f} MiB plus "
            f"{data['cache_bytes_added'] / mib:,.0f} MiB of shared CD data. "
            f"Files copied because sharing was unavailable: {data['copy_fallbacks']}.")


class Setup:
    def __init__(self, root):
        self.root = root
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.events = Queue()
        self.log = None
        self.destination = None
        root.title('TNova Native — Setup')
        root.minsize(760, 620)
        root.protocol('WM_DELETE_WINDOW', self.close)
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(1, weight=1)
        ttk.Label(outer, text='Set up TNova Native', font=('Segoe UI', 20, 'bold')).grid(
            row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(outer, text=(
            'Choose your original game files and a new installation folder.\n'
            'Requires the supported English retail v1.09 game, both demos and retail CD ISO.'
        ), wraplength=710).grid(row=1, column=0, columnspan=3, sticky='w', pady=(8, 14))
        self.values, self.controls = {}, []
        for row, (name, label) in enumerate(FIELDS, 2):
            ttk.Label(outer, text=label).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=5)
            value = tk.StringVar()
            if name == 'destination':
                value.set(r'C:\Games\TNovaNative')
            elif name == 'tools_cache':
                value.set(str(Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'TNovaTools'))
            self.values[name] = value
            entry = ttk.Entry(outer, textvariable=value, width=45)
            entry.grid(row=row, column=1, sticky='ew')
            button = ttk.Button(outer, text='Browse…', command=lambda key=name: self.browse(key))
            button.grid(row=row, column=2, padx=(8, 0))
            self.controls.extend((entry, button))
        self.copy_data = tk.BooleanVar(value=False)
        copy = ttk.Checkbutton(outer, text='Copy all game data (uses more disk space)', variable=self.copy_data)
        copy.grid(row=8, column=0, columnspan=3, sticky='w', pady=(10, 0))
        self.controls.append(copy)
        ttk.Label(outer, text=(
            'Default: share unchanged assets where supported; keep saves and settings separate.\n'
            'Treat shared assets as read-only. Choose copies if you plan to edit original resources.\n'
            'First setup downloads about 95 MB of tools; allow 700 MB for tools and temporary work.'
        ), wraplength=710).grid(row=9, column=0, columnspan=3, sticky='w', pady=(5, 12))
        buttons = ttk.Frame(outer)
        buttons.grid(row=10, column=0, columnspan=3, sticky='w')
        self.start_button = ttk.Button(buttons, text='Set up game', command=self.start)
        self.start_button.pack(side='left')
        self.controls.append(self.start_button)
        self.open_game = ttk.Button(buttons, text='Open game folder', command=lambda: os.startfile(self.destination), state='disabled')
        self.open_game.pack(side='left', padx=8)
        self.open_log = ttk.Button(buttons, text='Open setup log', command=lambda: os.startfile(self.log), state='disabled')
        self.open_log.pack(side='left')
        self.bar = ttk.Progressbar(outer, mode='indeterminate')
        self.bar.grid(row=11, column=0, columnspan=3, sticky='ew', pady=(18, 8))
        self.status = tk.StringVar(value='Ready. Original files and existing installations will not be overwritten.')
        ttk.Label(outer, textvariable=self.status, wraplength=710).grid(row=12, column=0, columnspan=3, sticky='w')

    def browse(self, name):
        if name == 'cd_image':
            selected = filedialog.askopenfilename(parent=self.root, title='Select the supported retail CD ISO', filetypes=[('CD images', '*.iso'), ('All files', '*')])
        else:
            title = 'Choose folder'
            if name == 'destination':
                title = 'Choose a parent folder; setup adds a new TNovaNative folder inside it'
            selected = filedialog.askdirectory(parent=self.root, title=title)
            if selected and name == 'destination':
                selected = str(Path(selected) / 'TNovaNative')
        if selected:
            self.values[name].set(selected)
            if name == 'retail':
                parent = Path(selected).parent
                for key, relative in (('download_demo', 'TNDEMO1'), ('cd_demo', 'TNDEMO2'), ('cd_image', '_ISO/TNF108.ISO')):
                    candidate = parent / relative
                    if not self.values[key].get() and candidate.exists():
                        self.values[key].set(str(candidate))

    def start(self):
        if self.pending:
            return
        try:
            options = setup_options({key: value.get() for key, value in self.values.items()}, self.copy_data.get())
            self.log = Path(tempfile.gettempdir()) / f'TNovaNative-setup-{datetime.now():%Y%m%d-%H%M%S-%f}-{os.getpid()}.log'
            self.log.write_text('TNova Native setup\n' + '\n'.join(f'{key}: {value}' for key, value in options.items()) + '\n', encoding='utf-8')
        except (ValueError, OSError) as exc:
            messagebox.showerror('Setup needs your attention', str(exc), parent=self.root)
            return
        for control in self.controls:
            control.state(['disabled'])
        self.open_game.state(['disabled'])
        self.open_log.state(['!disabled'])
        self.bar.start(15)
        self.status.set('Starting setup…')
        self.pending = self.pool.submit(install, Path(__file__).resolve().parent, None,
            options.pop('destination'), progress=lambda stage, message: self.events.put(f'[{stage}/5] {message}'), **options)
        self.root.after(100, self.poll)

    def record(self, message):
        # An unwritable diagnostic log must not turn a successful install into failure.
        try:
            with self.log.open('a', encoding='utf-8') as stream:
                stream.write(message + '\n')
        except OSError:
            pass

    def poll(self):
        try:
            while True:
                message = self.events.get_nowait()
                self.record(message)
                self.status.set(message)
        except Empty:
            pass
        if not self.pending.done():
            self.root.after(100, self.poll)
            return
        future, self.pending = self.pending, None
        self.bar.stop()
        for control in self.controls:
            control.state(['!disabled'])
        try:
            result = future.result()
            self.destination = result['destination']
            message = ('Ready to play. Open the game folder and start Terra Nova Launcher.exe '
                       '(or Play.cmd in a developer package).\n' + storage_summary(result))
            self.status.set(message)
            self.record(message)
            self.open_game.state(['!disabled'])
        except Exception as exc:
            self.record(traceback.format_exc())
            self.status.set('Setup stopped. Correct the selected paths or see the setup log, then try again.')
            messagebox.showerror('Setup stopped', f'{exc}\n\nDetails: {self.log}', parent=self.root)

    def close(self):
        if self.pending:
            self.status.set('Setup is still running. Please wait before closing this window.')
            return
        self.pool.shutdown(wait=False)
        self.root.destroy()


def main():
    root = tk.Tk()
    if os.name != 'nt' or sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8 or sys.flags.optimize:
        root.withdraw()
        messagebox.showerror('Python required', 'Use 64-bit Windows CPython 3.12 without -O to run setup.', parent=root)
        root.destroy()
        return 1
    Setup(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
