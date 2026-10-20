"""Windows clipboard bytes for the lobby chat, which does read CF_UNICODETEXT."""


def unicode_clipboard(text):
    if type(text) is not str:
        raise ValueError('剪贴板文字无效')
    return text.encode('utf-16le') + b'\x00\x00'
