"""Explicit light Tk defaults, independent of macOS appearance."""
def apply_light_defaults(root):
    colors={
      '*foreground':'#302c22', '*background':'#f7f4ea',
      '*insertBackground':'#302c22', '*selectBackground':'#705723',
      '*selectForeground':'#ffffff', '*disabledForeground':'#716b5c',
      '*activeForeground':'#302c22', '*activeBackground':'#e4dcc5',
      '*highlightBackground':'#c8c3ae', '*highlightColor':'#8b722f',
      '*Button.foreground':'#302c22', '*Button.background':'#e7e0c9',
      '*Button.highlightThickness':0, '*Button.borderWidth':1, '*Button.relief':'flat',
      '*Entry.foreground':'#302c22', '*Entry.background':'#fffdf5',
      '*Entry.highlightThickness':1, '*Entry.borderWidth':1, '*Entry.relief':'solid',
      '*Checkbutton.foreground':'#302c22', '*Checkbutton.selectColor':'#f7f4ea',
      '*Checkbutton.highlightThickness':0,
      '*Labelframe.foreground':'#655020', '*Label.foreground':'#302c22',
    }
    for pattern,value in colors.items():root.option_add(pattern,value,60)
