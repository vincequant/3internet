#!/usr/bin/env python3
"""結束指定帳號的遊戲客戶端（大廳保留）。

列出目前三個 prefix（丁满／风云／風夜）的 SANPK，勾選後只殺那幾個。
"""
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

PREFIXES = {
    '丁满': 'prefix-dingman-local',
    '风云': 'prefix-sikarugir10',
    '風夜(小白)': 'prefix-fengye-shadow',
}
SGI = os.path.expanduser('~/Library/Application Support/SGI-Wine')


def running():
    out = {}
    for pid in subprocess.run(['pgrep', '-f', 'SANPK.exe'], capture_output=True, text=True).stdout.split():
        try:
            lsof = subprocess.run(['lsof', '-p', pid], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        for name, pref in PREFIXES.items():
            if pref in lsof:
                out.setdefault(name, []).append(pid)
    return out


class App:
    def __init__(self, root):
        self.root = root
        root.title('結束客戶端（大廳保留）')
        root.configure(bg='#f3efe4')
        self.vars = {}
        frame = tk.Frame(root, bg='#f3efe4')
        frame.pack(fill='both', expand=True, padx=16, pady=14)
        tk.Label(frame, text='勾選要結束的帳號視窗：', bg='#f3efe4', font=('PingFang TC', 13, 'bold')).pack(anchor='w')
        self.body = tk.Frame(frame, bg='#f3efe4')
        self.body.pack(fill='x', pady=8)
        self.refresh()
        bar = tk.Frame(frame, bg='#f3efe4')
        bar.pack(fill='x', pady=(8, 0))
        tk.Button(bar, text='↻ 重新整理', command=self.refresh).pack(side='left')
        tk.Button(bar, text='結束所選', bg='#f7e5e5', fg='#8a2b2b',
                  command=self.end_selected).pack(side='left', padx=8)
        tk.Button(bar, text='全部結束', bg='#f7e5e5', fg='#8a2b2b',
                  command=self.end_all).pack(side='left', padx=8)
        tk.Button(bar, text='關閉', command=root.destroy).pack(side='right')

    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        self.vars.clear()
        cur = running()
        if not cur:
            tk.Label(self.body, text='目前沒有執行中的客戶端', bg='#f3efe4').pack(anchor='w')
            return
        for name, pids in sorted(cur.items()):
            var = tk.BooleanVar(value=True)
            self.vars[name] = (var, pids)
            tk.Checkbutton(self.body, text='%s（pid %s）' % (name, ', '.join(pids)),
                           variable=var, bg='#f3efe4', activebackground='#f3efe4',
                           selectcolor='#ffffff').pack(anchor='w')

    def end_all(self):
        for name, (var, pids) in self.vars.items():
            var.set(True)
        self.end_selected()

    def end_selected(self):
        killed = []
        for name, (var, pids) in self.vars.items():
            if not var.get():
                continue
            for pid in pids:
                try:
                    os.kill(int(pid), 9)
                    killed.append('%s(%s)' % (name, pid))
                except OSError:
                    pass
        messagebox.showinfo('結束客戶端', '已結束：\n' + ('\n'.join(killed) if killed else '（沒有選取）'))
        self.refresh()


if __name__ == '__main__':
    root = tk.Tk()
    root.geometry('460x300')
    App(root)
    if '--list' in sys.argv:
        print(running())
        root.destroy()
    else:
        root.mainloop()
