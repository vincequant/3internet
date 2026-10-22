"""Per-machine density, independent of which game's data is being viewed."""
import json
from pathlib import Path
CONFIG=Path(__file__).resolve().parent.parent/'display.local.json'
SCALE=1.0
CHOICES=('自动','75%','80%','85%','90%','100%','110%')
def settings(width,height,choice='自动'):
 if choice not in CHOICES:choice='自动'
 scale=(.85 if height<1000 else 1.) if choice=='自动' else int(choice[:-1])/100
 return scale,min(1420 if scale<1 else 1280,max(640,width-48)),min(900,max(480,height-140))
def configure(root):
 global SCALE
 choice='自动'
 if CONFIG.exists():
  try:choice=json.loads(CONFIG.read_text())['scale']
  except (ValueError,KeyError):pass
 SCALE,width,height=settings(root.winfo_screenwidth(),root.winfo_screenheight(),choice)
 root.sgi_ui_scale=SCALE
 root.tk.call('tk','scaling',float(root.tk.call('tk','scaling'))*SCALE)
 root.geometry(f'{width}x{height}+16+38')
 return choice if choice in CHOICES else '自动'
def pixels(value):return max(1,round(value*SCALE))
def save(choice):
 if choice not in CHOICES:raise ValueError('无效界面缩放')
 temp=CONFIG.with_suffix('.tmp');temp.write_text(json.dumps({'scale':choice},ensure_ascii=False));temp.replace(CONFIG)
