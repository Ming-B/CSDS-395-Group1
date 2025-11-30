# core/stored_files_sidebar.py
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from .database import DatabaseManager

class StoredFilesSidebar(ttk.Frame):
    """
    A reusable sidebar widget that lists stored files from the database.
    Can be imported and placed in any window.
    """

    def __init__(self, parent, on_file_select=None, **kwargs):
        """
        :param parent: Parent Tkinter widget
        :param on_file_select: Callback function(file_info) when a file is selected
        """
        super().__init__(parent, **kwargs)
        self.manager = DatabaseManager()
        self.on_file_select = on_file_select

        self._build_widgets()
        self.refresh_files()

    def _build_widgets(self):
        """Build the sidebar UI."""
        self.label = ttk.Label(self, text="Stored Files")
        self.label.pack(pady=(5, 2))

        # Listbox with scrollbar
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(self, yscrollcommand=self.scrollbar.set, height=15)
        self.scrollbar.config(command=self.listbox.yview)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        # Refresh button
        self.refresh_btn = ttk.Button(self, text="Refresh", command=self.refresh_files)
        self.refresh_btn.pack(pady=5)

    def refresh_files(self):
        """Load all files from the database and display in the listbox."""
        self.listbox.delete(0, tk.END)
        self.files = self.manager.get_all_files()
        for f in self.files:
            self.listbox.insert(tk.END, f.split("/")[-1])  # show only the file name

    def _on_select(self, event):
        """Handle file selection."""
        if not self.listbox.curselection():
            return
        index = self.listbox.curselection()[0]
        file_info = self.manager.get_file_by_index(index)
        if self.on_file_select:
            self.on_file_select(file_info)
