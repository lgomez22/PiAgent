"""
coder.py — Script-writing assistant.

Primary targets: Python and Bash/Shell (runs natively on RPi).
For other languages it generates the code and notes how to run it,
since compiling/interpreting other langs on a bare Pi may need extra setup.

Design goals:
  • Zero external dependencies (no LLM API call — runs offline on Pi)
  • Template + keyword matching for common tasks
  • Extensible: add new templates or languages easily
  • Stays well under the 1 GB memory cap
"""

import textwrap
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Language metadata
# ---------------------------------------------------------------------------
LANG_INFO = {
    "python": {
        "ext": ".py",
        "shebang": "#!/usr/bin/env python3",
        "run_hint": "python3 script.py",
        "native": True,
    },
    "bash": {
        "ext": ".sh",
        "shebang": "#!/usr/bin/env bash",
        "run_hint": "bash script.sh  (or chmod +x script.sh && ./script.sh)",
        "native": True,
    },
    "shell": None,  # alias → bash
    "sh":    None,  # alias → bash
    "javascript": {
        "ext": ".js",
        "shebang": "",
        "run_hint": "node script.js   (install Node.js first: sudo apt install nodejs)",
        "native": False,
    },
    "typescript": {
        "ext": ".ts",
        "shebang": "",
        "run_hint": "npx ts-node script.ts   (needs Node.js + TypeScript)",
        "native": False,
    },
    "rust": {
        "ext": ".rs",
        "shebang": "",
        "run_hint": "rustc script.rs -o script && ./script   (install Rust: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh)",
        "native": False,
    },
    "go": {
        "ext": ".go",
        "shebang": "",
        "run_hint": "go run script.go   (install Go: sudo apt install golang)",
        "native": False,
    },
    "c": {
        "ext": ".c",
        "shebang": "",
        "run_hint": "gcc script.c -o script && ./script   (gcc is usually pre-installed on RPi)",
        "native": False,
    },
    "cpp": {
        "ext": ".cpp",
        "shebang": "",
        "run_hint": "g++ script.cpp -o script && ./script",
        "native": False,
    },
    "ruby": {
        "ext": ".rb",
        "shebang": "#!/usr/bin/env ruby",
        "run_hint": "ruby script.rb   (install: sudo apt install ruby)",
        "native": False,
    },
}

# Resolve aliases
LANG_INFO["shell"] = LANG_INFO["bash"]
LANG_INFO["sh"]    = LANG_INFO["bash"]


# ---------------------------------------------------------------------------
# Template registry — (keywords) → (python_code, bash_code)
# ---------------------------------------------------------------------------
TEMPLATES = [
    {
        "keywords": ["hello", "world"],
        "description": "Hello World",
        "python": textwrap.dedent("""\
            #!/usr/bin/env python3
            print("Hello, World!")
        """),
        "bash": textwrap.dedent("""\
            #!/usr/bin/env bash
            echo "Hello, World!"
        """),
    },
    {
        "keywords": ["file", "list", "directory", "ls"],
        "description": "List files in a directory",
        "python": textwrap.dedent("""\
            #!/usr/bin/env python3
            import os, sys

            path = sys.argv[1] if len(sys.argv) > 1 else "."
            for entry in sorted(os.listdir(path)):
                full = os.path.join(path, entry)
                kind = "DIR " if os.path.isdir(full) else "FILE"
                size = os.path.getsize(full) if os.path.isfile(full) else 0
                print(f"  [{kind}] {entry:40s} {size:>10,} bytes")
        """),
        "bash": textwrap.dedent("""\
            #!/usr/bin/env bash
            DIR="${1:-.}"
            echo "Listing: $DIR"
            ls -lah "$DIR"
        """),
    },
    {
        "keywords": ["backup", "copy", "rsync"],
        "description": "Backup a directory",
        "python": textwrap.dedent("""\
            #!/usr/bin/env python3
            import shutil, sys, os
            from datetime import datetime

            src  = sys.argv[1] if len(sys.argv) > 1 else "."
            dest = sys.argv[2] if len(sys.argv) > 2 else "./backup"

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_full = os.path.join(dest, f"backup_{timestamp}")

            print(f"Backing up {src} → {dest_full}")
            shutil.copytree(src, dest_full)
            print("Done ✓")
        """),
        "bash": textwrap.dedent("""\
            #!/usr/bin/env bash
            SRC="${1:-.}"
            DEST="${2:-./backup}"
            STAMP=$(date +%Y%m%d_%H%M%S)
            TARGET="$DEST/backup_$STAMP"

            echo "Backing up $SRC → $TARGET"
            mkdir -p "$TARGET"
            rsync -avz "$SRC/" "$TARGET/"
            echo "Done ✓"
        """),
    },
    {
        "keywords": ["monitor", "cpu", "memory", "ram", "temp", "system", "pi"],
        "description": "System monitor (CPU, RAM, temp — great for RPi)",
        "python": textwrap.dedent("""\
            #!/usr/bin/env python3
            \"\"\"Lightweight system monitor — works on RPi 3B/4.\"\"\"
            import os, time

            def cpu_percent(interval: float = 0.5) -> float:
                with open("/proc/stat") as f:
                    parts = f.readline().split()
                idle1, total1 = int(parts[4]), sum(int(x) for x in parts[1:])
                time.sleep(interval)
                with open("/proc/stat") as f:
                    parts = f.readline().split()
                idle2, total2 = int(parts[4]), sum(int(x) for x in parts[1:])
                return round((1 - (idle2 - idle1) / (total2 - total1)) * 100, 1)

            def ram_info() -> dict:
                with open("/proc/meminfo") as f:
                    lines = {l.split()[0].rstrip(":"): int(l.split()[1])
                             for l in f if l.split()[0].rstrip(":") in
                             ("MemTotal", "MemAvailable", "MemFree")}
                total = lines.get("MemTotal", 0)
                avail = lines.get("MemAvailable", 0)
                return {"total_mb": total // 1024,
                        "used_mb": (total - avail) // 1024,
                        "free_mb": avail // 1024}

            def cpu_temp() -> Optional[float]:
                try:
                    with open("/sys/class/thermal/thermal_zone0/temp") as f:
                        return int(f.read().strip()) / 1000.0
                except FileNotFoundError:
                    return None

            if __name__ == "__main__":
                print("=" * 40)
                print("  RPi System Monitor")
                print("=" * 40)
                while True:
                    cpu  = cpu_percent()
                    ram  = ram_info()
                    temp = cpu_temp()
                    print(f"  CPU : {cpu:5.1f}%")
                    print(f"  RAM : {ram['used_mb']:,} / {ram['total_mb']:,} MB used")
                    if temp is not None:
                        print(f"  Temp: {temp:.1f} °C")
                    print("-" * 40)
                    time.sleep(2)
        """),
        "bash": textwrap.dedent("""\
            #!/usr/bin/env bash
            echo "========================================"
            echo "  RPi System Monitor"
            echo "========================================"
            while true; do
                echo "  CPU  : $(top -bn1 | grep 'Cpu(s)' | awk '{print $2}')%"
                echo "  RAM  : $(free -m | awk '/Mem:/ {print $3 "/" $2 " MB used"}')"
                if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
                    TEMP=$(( $(cat /sys/class/thermal/thermal_zone0/temp) / 1000 ))
                    echo "  Temp : ${TEMP} °C"
                fi
                echo "----------------------------------------"
                sleep 2
            done
        """),
    },
    {
        "keywords": ["cron", "schedule", "timer", "interval", "repeat"],
        "description": "Cron job helper / scheduled task",
        "python": textwrap.dedent("""\
            #!/usr/bin/env python3
            \"\"\"Simple interval scheduler — no cron needed.
            Usage: python3 scheduler.py <interval_seconds> <command>
            Example: python3 scheduler.py 300 'python3 heartbeat.py'
            \"\"\"
            import sys, os, time, subprocess

            if len(sys.argv) < 3:
                print(__doc__)
                sys.exit(1)

            interval = int(sys.argv[1])
            command  = " ".join(sys.argv[2:])
            print(f"Running every {interval}s: {command}")

            while True:
                print(f"[{time.strftime('%H:%M:%S')}] Running...")
                subprocess.run(command, shell=True)
                time.sleep(interval)
        """),
        "bash": textwrap.dedent("""\
            #!/usr/bin/env bash
            # Usage: bash scheduler.sh <interval_seconds> <command...>
            INTERVAL="${1:-60}"
            shift
            CMD="$*"

            echo "Running every ${INTERVAL}s: $CMD"
            while true; do
                echo "[$(date +%H:%M:%S)] Running..."
                eval "$CMD"
                sleep "$INTERVAL"
            done
        """),
    },
    {
        "keywords": ["http", "server", "serve", "web"],
        "description": "Simple HTTP server",
        "python": textwrap.dedent("""\
            #!/usr/bin/env python3
            \"\"\"Quick HTTP file server.
            Usage: python3 http_server.py [port] [directory]
            \"\"\"
            import sys, http.server, socketserver, os

            port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
            directory = sys.argv[2] if len(sys.argv) > 2 else "."
            os.chdir(directory)

            handler = http.server.SimpleHTTPRequestHandler
            with socketserver.TCPServer(("", port), handler) as httpd:
                print(f"Serving {directory} on http://0.0.0.0:{port}")
                httpd.serve_forever()
        """),
        "bash": textwrap.dedent("""\
            #!/usr/bin/env bash
            PORT="${1:-8080}"
            DIR="${2:-.}"
            cd "$DIR"
            echo "Serving $DIR on http://0.0.0.0:$PORT"
            python3 -m http.server "$PORT"
        """),
    },
    {
        "keywords": ["gpio", "led", "pin", "raspberry", "hardware"],
        "description": "GPIO LED blink (RPi hardware)",
        "python": textwrap.dedent("""\
            #!/usr/bin/env python3
            \"\"\"Blink an LED on GPIO pin 17.
            Requires: sudo pip install RPi.GPIO
            \"\"\"
            import time
            try:
                import RPi.GPIO as GPIO
            except ImportError:
                print("Install RPi.GPIO: sudo pip install RPi.GPIO")
                raise

            PIN = 17
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(PIN, GPIO.OUT)

            print(f"Blinking LED on GPIO {PIN}. Ctrl+C to stop.")
            try:
                while True:
                    GPIO.output(PIN, GPIO.HIGH)
                    print("  LED ON")
                    time.sleep(1)
                    GPIO.output(PIN, GPIO.LOW)
                    print("  LED OFF")
                    time.sleep(1)
            except KeyboardInterrupt:
                GPIO.cleanup()
                print("Stopped.")
        """),
        "bash": textwrap.dedent("""\
            #!/usr/bin/env bash
            # GPIO blink via sysfs (no library needed, but limited)
            PIN=17
            echo "$PIN" > /sys/class/gpio/export 2>/dev/null
            echo "out" > /sys/class/gpio/gpio${PIN}/direction

            echo "Blinking GPIO $PIN. Ctrl+C to stop."
            trap 'echo 0 > /sys/class/gpio/gpio${PIN}/value; echo "$PIN" > /sys/class/gpio/unexport; exit' INT

            while true; do
                echo 1 > /sys/class/gpio/gpio${PIN}/value; echo "  LED ON";  sleep 1
                echo 0 > /sys/class/gpio/gpio${PIN}/value; echo "  LED OFF"; sleep 1
            done
        """),
    },
]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _detect_lang(text: str) -> Tuple[str, str]:
    """Extract language hint from the start of the text, return (lang, remainder)."""
    tokens = text.split(None, 1)
    if not tokens:
        return "python", text
    candidate = tokens[0].lower().rstrip(":,.")
    if candidate in LANG_INFO:
        return candidate, tokens[1] if len(tokens) > 1 else ""
    return "python", text  # default to Python


def _match_template(task: str) -> Optional[dict]:
    """Find best matching template by keyword overlap.
    Exact whole-word matches score 2, substring matches score 1.
    Ties are broken by whether the template's primary keyword (first in list)
    is an exact word match in the task."""
    task_lower = task.lower()
    task_words = set(task_lower.split())
    best, best_score, best_primary = None, 0, False
    for t in TEMPLATES:
        score = 0
        for kw in t["keywords"]:
            if kw in task_words:
                score += 2   # exact word match
            elif kw in task_lower:
                score += 1   # substring match
        primary_exact = t["keywords"][0] in task_words if t["keywords"] else False
        # Prefer higher score; on tie, prefer primary keyword exact match
        if (score > best_score) or (score == best_score and primary_exact and not best_primary):
            best, best_score, best_primary = t, score, primary_exact
    return best if best_score > 0 else None


def _generic_skeleton(lang: str, task: str) -> str:
    """Fallback: produce a commented skeleton for any language."""
    info = LANG_INFO.get(lang, LANG_INFO["python"])
    shebang = info["shebang"]
    ext = info["ext"]
    lines = []
    if shebang:
        lines.append(shebang)
    lines.append(f"# Task: {task}")
    lines.append(f"# Language: {lang}")
    lines.append("#")
    lines.append("# TODO: Implement your logic here")
    lines.append("")

    if lang == "python":
        lines.append('def main():')
        lines.append('    """Entry point."""')
        lines.append('    print("Hello from your script")')
        lines.append("")
        lines.append('if __name__ == "__main__":')
        lines.append("    main()")
    elif lang in ("bash", "shell", "sh"):
        lines.append("set -euo pipefail")
        lines.append('echo "Script started"')
        lines.append("# Your commands here")
    elif lang in ("javascript", "typescript"):
        lines.append("function main() {")
        lines.append('    console.log("Hello from your script");')
        lines.append("}")
        lines.append("main();")
    elif lang == "rust":
        lines.append("fn main() {")
        lines.append('    println!("Hello from your script");')
        lines.append("}")
    elif lang == "go":
        lines.append('package main')
        lines.append('import "fmt"')
        lines.append("func main() {")
        lines.append('    fmt.Println("Hello from your script")')
        lines.append("}")
    elif lang == "c":
        lines.append("#include <stdio.h>")
        lines.append("int main() {")
        lines.append('    printf("Hello from your script\\n");')
        lines.append("    return 0;")
        lines.append("}")
    elif lang == "cpp":
        lines.append("#include <iostream>")
        lines.append("int main() {")
        lines.append('    std::cout << "Hello from your script" << std::endl;')
        lines.append("    return 0;")
        lines.append("}")
    elif lang == "ruby":
        lines.append('puts "Hello from your script"')
    else:
        lines.append("# Unsupported language — fill in manually")

    return "\n".join(lines) + "\n"


class CoderAssistant:
    def handle(self, text: str):
        lang, task = _detect_lang(text)
        info = LANG_INFO.get(lang, LANG_INFO["python"])

        # Resolve alias
        if lang in ("shell", "sh"):
            lang = "bash"

        template = _match_template(task if task else lang)

        print(f"\n{'─' * 55}")
        print(f"  📝  Code Assistant — {lang.upper()}")
        print(f"{'─' * 55}\n")

        if template:
            print(f"  Matched template: {template['description']}\n")
            if lang in template:
                # Template has a version in the requested language — use it directly
                code = template[lang]
            else:
                # Template exists but not for this lang — generate a skeleton
                # in the requested language and hint at the Python/Bash versions below
                print(f"  ⚠️  No {lang} version in template — generating {lang} skeleton.\n")
                code = _generic_skeleton(lang, task or template["description"])
        else:
            print(f"  No exact template match. Generating skeleton for: \"{task or 'general script'}\"\n")
            code = _generic_skeleton(lang, task or "general script")

        # Print the code
        print(f"  {'─' * 50}")
        for line in code.splitlines():
            print(f"    {line}")
        print(f"  {'─' * 50}\n")

        # Run hint
        print(f"  💡 Run: {info['run_hint']}")
        if not info["native"]:
            print(f"  ⚠️  This language is NOT native to RPi — see install notes above.")
        print()

        # If user asked for a non-Python/Bash language and we have a template,
        # also show how it would look in that language as a suggestion
        if lang not in ("python", "bash") and template:
            print(f"  💡 Tip: For best RPi compatibility, consider the Python or Bash version:")
            for alt in ("python", "bash"):
                if alt in template:
                    print(f"\n      === {alt.upper()} version ===")
                    for line in template[alt].splitlines():
                        print(f"        {line}")
            print()