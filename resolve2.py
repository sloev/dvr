import sys
import re

with open("dvr_app/src/main.rs", "r") as f:
    content = f.read()

new_content = re.sub(
    r"<<<<<<< HEAD\n(.*?)\n=======\n>>>>>>> origin/master\n",
    r"\1\n",
    content,
    flags=re.DOTALL
)

with open("dvr_app/src/main.rs", "w") as f:
    f.write(new_content)
