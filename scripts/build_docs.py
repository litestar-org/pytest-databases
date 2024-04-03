# MIT License

# Copyright (c) 2024 Litestar

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


from __future__ import annotations

import argparse
import shutil
import subprocess  # noqa: S404
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

REDIRECT_TEMPLATE = """
<!DOCTYPE HTML>
<html lang="en-US">
    <head>
        <title>Page Redirection</title>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="0; url={target}">
        <script type="text/javascript">window.location.href = "{target}"</script>
    </head>
    <body>
        You are being redirected. If this does not work, click <a href='{target}'>this link</a>
    </body>
</html>
"""

parser = argparse.ArgumentParser()
parser.add_argument("output")


@contextmanager
def checkout(branch: str) -> Generator[None, None, None]:
    subprocess.run(["git", "checkout", branch], check=True)  # noqa: S607
    yield
    subprocess.run(["git", "checkout", "-"], check=True)  # noqa: S607


def build(output_dir: str) -> None:
    subprocess.run(["make", "docs"], check=True)  # noqa: S607

    output_path = Path(output_dir)
    output_path.mkdir()
    output_path.joinpath(".nojekyll").touch(exist_ok=True)
    output_path.joinpath("index.html").write_text(REDIRECT_TEMPLATE.format(target="latest"))

    docs_src_path = Path("docs/_build/html")
    shutil.copytree(docs_src_path, output_path / "latest", dirs_exist_ok=True)


def main() -> None:
    args = parser.parse_args()
    build(output_dir=args.output)


if __name__ == "__main__":
    main()
