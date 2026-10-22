import os,sys,tkinter as tk
from pathlib import Path
from omni_window import OmniWindow
root=tk.Tk();root.geometry('1280x900');app=OmniWindow(root)
root.title('三国志全知情报 · Mac / CrossOver 测试版')
app.status.config(text='等待同一 Mac 上 CrossOver 采集桥 :8769')
root.mainloop()
