import re
layouts = {
    'lower': [
        "q w e r t y u i o p å",
        "a s d f g h j k l æ ø",
        "⇧ z x c v b n m ⌫",
        "123 , [ space ] . ↵"
    ]
}
for row in layouts['lower']:
    keys = re.findall(r'\[ space \]|[^ ]+', row)
    print(keys)
