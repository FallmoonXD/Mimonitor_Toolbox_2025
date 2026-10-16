"""Build the Android native helper and its reusable session worker."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android-jar", required=True)
    parser.add_argument("--d8", required=True)
    parser.add_argument("--javac", default=shutil.which("javac"))
    parser.add_argument("--output", default="assets/runtime/MtkDirectTool.jar")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="mimonitor-native-") as temporary:
        classes, dex = Path(temporary) / "classes", Path(temporary) / "dex"
        classes.mkdir()
        dex.mkdir()
        sources = [root / "tools/mtk_direct" / name for name in ("MtkDirectTool.java", "ToolboxSession.java")]
        subprocess.run([args.javac, "--release", "8", "-encoding", "UTF-8", "-cp", args.android_jar,
                        "-d", str(classes), *map(str, sources)], check=True)
        subprocess.run([args.d8, "--lib", args.android_jar, "--min-api", "28", "--output", str(dex),
                        *map(str, classes.rglob("*.class"))], check=True)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            source_hashes = "".join(hashlib.sha256(source.read_text(encoding="utf-8").encode("utf-8")).hexdigest() + "  " + source.name + "\n"
                                    for source in sources).encode("utf-8")
            for name, content in (("classes.dex", (dex / "classes.dex").read_bytes()),
                                  ("META-INF/source-sha256", source_hashes)):
                entry = zipfile.ZipInfo(name, date_time=(2025, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, content)
        print(output.resolve())


if __name__ == "__main__":
    main()
