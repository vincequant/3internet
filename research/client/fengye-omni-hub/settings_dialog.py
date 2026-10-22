# -*- coding: utf-8 -*-
"""後台設定視窗：登入帳號庫＋偽名庫的新增／刪除／切換。

主頁只留「線路 → 房間號 → 一鍵登入」，帳號與偽名的增刪集中到這裡。

用法（由 native_window 呼叫）：
    from settings_dialog import open_settings
    open_settings(self.root, self.command_service, on_change=callback)
"""
import tkinter as tk
from tkinter import ttk

TITLE = '帳號與偽名設定'
BG = '#f7f7f4'
INK = '#22333b'
MUTED = '#6b7b83'
ACCENT = '#cbe7e4'
WARN = '#a33b3b'


def open_settings(parent, service, on_change=None):
    win = tk.Toplevel(parent)
    win.title(TITLE)
    win.configure(bg=BG)
    win.geometry('760x460')
    win.transient(parent)

    hint = tk.Label(win, bg=BG, fg=MUTED, anchor='w',
                    text='帳號庫與偽名庫都存在本機實驗室目錄；發行包不會帶走。改完按「關閉」即可，主頁下拉會同步。')
    hint.pack(fill='x', padx=14, pady=(12, 6))

    body = tk.Frame(win, bg=BG)
    body.pack(fill='both', expand=True, padx=12, pady=6)

    state = {'accounts': [], 'names': []}

    # ---------------- 帳號 ----------------
    left = tk.Frame(body, bg=BG)
    left.pack(side='left', fill='both', expand=True, padx=(0, 8))
    tk.Label(left, text='登入帳號', bg=BG, fg=INK, font=('Helvetica', 12, 'bold')).pack(anchor='w')
    acc_list = tk.Listbox(left, height=9, exportselection=False)
    acc_list.pack(fill='both', expand=True, pady=(4, 6))

    form = tk.Frame(left, bg=BG)
    form.pack(fill='x')
    tk.Label(form, text='帳號', bg=BG, fg=INK).grid(row=0, column=0, sticky='w')
    acc_user = tk.StringVar()
    ttk.Entry(form, textvariable=acc_user, width=18).grid(row=0, column=1, sticky='w', padx=4, pady=2)
    tk.Label(form, text='密碼', bg=BG, fg=INK).grid(row=0, column=2, sticky='w')
    acc_pass = tk.StringVar()
    ttk.Entry(form, textvariable=acc_pass, width=18, show='*').grid(row=0, column=3, sticky='w', padx=4)
    tk.Label(form, text='備註', bg=BG, fg=INK).grid(row=1, column=0, sticky='w')
    acc_label = tk.StringVar()
    ttk.Entry(form, textvariable=acc_label, width=18).grid(row=1, column=1, sticky='w', padx=4, pady=2)

    acc_active = tk.Label(left, text='', bg=BG, fg=MUTED, anchor='w')
    acc_active.pack(fill='x', pady=(4, 0))

    def refresh_accounts():
        state['accounts'] = service.read_accounts().get('accounts') or []
        acc_list.delete(0, 'end')
        for row in state['accounts']:
            label = row.get('username', '')
            if row.get('label'):
                label += '  (%s)' % row['label']
            acc_list.insert('end', label)
        active = service.read_accounts().get('active') or ''
        acc_active.configure(text='目前使用：%s' % (active or '（未設定）'))

    def on_pick_account(_event=None):
        sel = acc_list.curselection()
        if not sel:
            return
        row = state['accounts'][sel[0]]
        acc_user.set(row.get('username') or '')
        acc_pass.set(row.get('password') or '')
        acc_label.set(row.get('label') or '')

    acc_list.bind('<<ListboxSelect>>', on_pick_account)

    def save_account():
        result = service.remember_account(acc_user.get(), acc_pass.get(), acc_label.get())
        acc_active.configure(text=('已存並設為目前：%s' % result['username']) if result.get('ok')
                             else '存失敗：%s' % (result.get('error') or '未知'))
        refresh_accounts()
        if on_change:
            on_change()

    def delete_account():
        sel = acc_list.curselection()
        if not sel:
            acc_active.configure(text='先在上面選一個帳號')
            return
        row = state['accounts'][sel[0]]
        result = service.delete_account(row.get('username'))
        acc_active.configure(text=('已刪除：%s' % result['username']) if result.get('ok')
                             else '刪失敗：%s' % (result.get('error') or '未知'))
        refresh_accounts()
        if on_change:
            on_change()

    def use_account():
        sel = acc_list.curselection()
        if not sel:
            acc_active.configure(text='先在上面選一個帳號')
            return
        row = state['accounts'][sel[0]]
        result = service.use_account(row.get('username'))
        acc_active.configure(text=('已切換：%s' % result['username']) if result.get('ok')
                             else '切換失敗：%s' % (result.get('error') or '未知'))
        refresh_accounts()
        if on_change:
            on_change()

    btns = tk.Frame(left, bg=BG)
    btns.pack(fill='x', pady=(6, 0))
    tk.Button(btns, text='新增／更新', bg=ACCENT, fg='#164d51', command=save_account).pack(side='left')
    tk.Button(btns, text='設為目前', bg='#ffffff', command=use_account).pack(side='left', padx=6)
    tk.Button(btns, text='刪除', bg='#f7e5e5', fg=WARN, command=delete_account).pack(side='left')

    # ---------------- 偽名 ----------------
    right = tk.Frame(body, bg=BG)
    right.pack(side='left', fill='both', expand=True)
    tk.Label(right, text='進房偽名', bg=BG, fg=INK, font=('Helvetica', 12, 'bold')).pack(anchor='w')
    name_list = tk.Listbox(right, height=9, exportselection=False)
    name_list.pack(fill='both', expand=True, pady=(4, 6))
    name_row = tk.Frame(right, bg=BG)
    name_row.pack(fill='x')
    name_var = tk.StringVar()
    ttk.Entry(name_row, textvariable=name_var, width=18).pack(side='left')
    name_hint = tk.Label(right, text='', bg=BG, fg=MUTED, anchor='w')
    name_hint.pack(fill='x', pady=(4, 0))

    def refresh_names():
        state['names'] = service.read_names().get('names') or []
        name_list.delete(0, 'end')
        for name in state['names']:
            name_list.insert('end', name)

    def add_name():
        result = service.remember_name(name_var.get())
        name_hint.configure(text=('已加入：%s' % result['name']) if result.get('ok')
                            else '加不進：%s' % (result.get('error') or '未知'))
        refresh_names()
        if on_change:
            on_change()

    def use_name():
        sel = name_list.curselection()
        if not sel:
            name_hint.configure(text='先在清單選一個名字')
            return
        result = service.set_active_name(state['names'][sel[0]])
        name_hint.configure(text=('目前偽名：%s' % result['name']) if result.get('ok')
                            else '設不了：%s' % (result.get('error') or '未知'))
        if on_change:
            on_change()

    def del_name():
        sel = name_list.curselection()
        if not sel:
            name_hint.configure(text='先在清單選一個名字')
            return
        result = service.forget_name(state['names'][sel[0]])
        name_hint.configure(text=('已刪除：%s' % result['name']) if result.get('ok')
                            else '刪不掉：%s' % (result.get('error') or '未知'))
        refresh_names()
        if on_change:
            on_change()

    nb = tk.Frame(right, bg=BG)
    nb.pack(fill='x', pady=(6, 0))
    tk.Button(nb, text='新增偽名', bg=ACCENT, fg='#164d51', command=add_name).pack(side='left')
    tk.Button(nb, text='設為目前', bg='#ffffff', command=use_name).pack(side='left', padx=6)
    tk.Button(nb, text='刪除所選', bg='#f7e5e5', fg=WARN, command=del_name).pack(side='left')

    tk.Button(win, text='關閉', command=win.destroy).pack(pady=10)

    refresh_accounts()
    refresh_names()
    win.lift()
    return win
