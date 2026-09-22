#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Minecraft Java Deobfuscator / Decompiler
-----------------------------------------
Pipeline:

    input.jar
       |
       +--> static analysis
       |
       +--> Vineflower
       |
       +--> Java source cleanup
       |       +--> constant folding
       |       +--> XOR folding
       |       +--> mapping
       |       +--> identifier analysis
       |       +--> whitespace cleanup
       |
       +--> source_deobf.jar
       |
       +--> deobf_report.json

Python 3.8+
Termux friendly
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

LIB_DIR = BASE_DIR / "vineflower"

VINEFLOWER = LIB_DIR / "vineflower.jar"

INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
REPORT_DIR = BASE_DIR / "reports"
LOG_DIR = BASE_DIR / "logs"
WORK_DIR = BASE_DIR / "work"

MAPPING_FILE = BASE_DIR / "mappings.json"

for directory in (
    LIB_DIR,
    INPUT_DIR,
    OUTPUT_DIR,
    REPORT_DIR,
    LOG_DIR,
    WORK_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)


# ============================================================
# COLORS
# ============================================================

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
WHITE = "\033[97m"


def c(text: str, color: str) -> str:
    return f"{color}{text}{RESET}"


def clear():
    os.system("clear" if os.name != "nt" else "cls")


# ============================================================
# CONFIG
# ============================================================

@dataclass
class Config:
    xmx: str = "2G"

    simplify_constants: bool = True
    simplify_xor: bool = True

    apply_mapping: bool = True

    detect_classes: bool = True
    detect_methods: bool = True
    detect_fields: bool = True
    detect_variables: bool = True

    detect_strings: bool = True
    detect_xor: bool = True

    cleanup_whitespace: bool = True

    keep_workdir: bool = False


CONFIG = Config()


# ============================================================
# REGEX
# ============================================================

CLASS_RE = re.compile(
    r"\b(?:class|interface|enum|record)\s+"
    r"(class_[0-9]+|[A-Za-z_$]+_[0-9a-fA-F]{6,})"
)

METHOD_RE = re.compile(
    r"\b(method_[0-9]+|method_[0-9a-fA-F]+)\b"
)

FIELD_RE = re.compile(
    r"\b(f_[0-9a-fA-F]{6,}|field_[0-9]+)\b"
)

VAR_RE = re.compile(
    r"\bvar[0-9]+\b"
)

XOR_RE = re.compile(
    r"""
    (?P<a>
        [-+]?(?:0[xX][0-9a-fA-F]+|\d+)
    )
    \s*\^\s*
    (?P<b>
        [-+]?(?:0[xX][0-9a-fA-F]+|\d+)
    )
    """,
    re.VERBOSE,
)

HEX_RE = re.compile(
    r"(?<![\w])[-+]?0[xX][0-9a-fA-F]+(?![\w])"
)

STRING_RE = re.compile(
    r'"(?:\\.|[^"\\])*"'
)


# ============================================================
# UI
# ============================================================

def banner():
    print(c(r"""
╔══════════════════════════════════════════════════════════════╗
║             MINECRAFT DEOBF ENGINE v3.0                      ║
║        Vineflower + Mapping + Constant Analyzer              ║
╠══════════════════════════════════════════════════════════════╣
║  Decompile → Analyze → Cleanup → Mapping → Report            ║
╚══════════════════════════════════════════════════════════════╝
""", CYAN))


def pause():
    input(c("\n[ENTER] Continue...", DIM))


def progress(text: str):
    print(c(f"[•] {text}", BLUE))


def success(text: str):
    print(c(f"[+] {text}", GREEN))


def warning(text: str):
    print(c(f"[!] {text}", YELLOW))


def error(text: str):
    print(c(f"[-] {text}", RED))


# ============================================================
# JAVA
# ============================================================

def java_exists() -> bool:
    return shutil.which("java") is not None


def java_version() -> str:
    if not java_exists():
        return "Java not found"

    try:
        result = subprocess.run(
            ["java", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )

        return result.stdout.strip().splitlines()[0]

    except Exception:
        return "Unknown"


# ============================================================
# VINEFLOWER
# ============================================================

def find_vineflower() -> Optional[Path]:
    candidates = [
        VINEFLOWER,
        LIB_DIR / "vineflower-1.12.0.jar",
        LIB_DIR / "vineflower-1.11.2.jar",
        LIB_DIR / "vineflower-1.11.1.jar",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    if LIB_DIR.is_dir():
        for jar_file in sorted(LIB_DIR.glob("vineflower*.jar")):
            return jar_file

    return None


def vineflower_help() -> str:
    vf = find_vineflower()

    if not vf or not java_exists():
        return ""

    try:
        result = subprocess.run(
            [
                "java",
                "-Xmx512m",
                "-jar",
                str(vf),
                "--help",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )

        return result.stdout

    except Exception:
        return ""


def run_vineflower(
    source: Path,
    destination: Path,
) -> bool:

    vf = find_vineflower()

    if not vf:
        error("Không tìm thấy vineflower.jar")
        print(f"Đặt file tại thư mục: {LIB_DIR}")
        print(f"(ví dụ: {VINEFLOWER})")
        return False

    if not java_exists():
        error("Không tìm thấy Java.")
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "java",
        f"-Xmx{CONFIG.xmx}",
        "-jar",
        str(vf),
        str(source),
        str(destination),
    ]

    print()
    print(c("Vineflower command:", DIM))
    print(c(" ".join(cmd), DIM))
    print()

    log_file = LOG_DIR / f"vineflower_{int(time.time())}.log"

    try:
        with log_file.open(
            "w",
            encoding="utf-8",
            errors="replace",
        ) as log:

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            assert process.stdout is not None

            for line in process.stdout:
                print("  " + line.rstrip())
                log.write(line)

            return_code = process.wait()

        if return_code != 0:
            error(
                f"Vineflower failed. Exit code: {return_code}"
            )
            return False

        success("Vineflower hoàn tất.")
        return True

    except KeyboardInterrupt:
        warning("Đã dừng tiến trình.")
        try:
            process.kill()
        except Exception:
            pass

        return False

    except Exception as exc:
        error(str(exc))
        return False


# ============================================================
# INTEGER EXPRESSION ENGINE
# ============================================================

ALLOWED_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.BitXor: lambda a, b: a ^ b,
    ast.BitOr: lambda a, b: a | b,
    ast.BitAnd: lambda a, b: a & b,
    ast.LShift: lambda a, b: a << b,
    ast.RShift: lambda a, b: a >> b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
}

ALLOWED_UNARY = {
    ast.USub: lambda a: -a,
    ast.UAdd: lambda a: +a,
    ast.Invert: lambda a: ~a,
}


def safe_eval_integer(expression: str) -> Optional[int]:
    """
    Safely evaluates integer-only expressions.

    Example:
        -67860947 ^ -678609255
        10 + 20 * 3
        0xFF ^ 0x10
    """

    try:
        tree = ast.parse(
            expression,
            mode="eval",
        ).body

        def evaluate(node):

            if isinstance(node, ast.Constant):
                if isinstance(node.value, int):
                    return node.value

                raise ValueError

            if isinstance(node, ast.UnaryOp):
                func = ALLOWED_UNARY.get(type(node.op))

                if not func:
                    raise ValueError

                return func(evaluate(node.operand))

            if isinstance(node, ast.BinOp):
                func = ALLOWED_BINOPS.get(type(node.op))

                if not func:
                    raise ValueError

                left = evaluate(node.left)
                right = evaluate(node.right)

                if isinstance(node.op, ast.FloorDiv):
                    if right == 0:
                        raise ValueError

                if isinstance(node.op, ast.Mod):
                    if right == 0:
                        raise ValueError

                return func(left, right)

            raise ValueError

        return int(evaluate(tree))

    except Exception:
        return None


def fold_integer_expressions(text: str) -> Tuple[str, int]:
    """
    Repeatedly folds simple integer expressions.
    """

    replacements = 0

    # First normalize Java hex literals.
    # Python AST already understands 0x values.
    pattern = re.compile(
        r"""
        (?<![\w.])
        (
            [-+]?(?:0[xX][0-9a-fA-F]+|\d+)
            (?:\s*
                [\^\+\-\*%&|<>]
                \s*
                [-+]?(?:0[xX][0-9a-fA-F]+|\d+)
            )+
        )
        (?![\w.])
        """,
        re.VERBOSE,
    )

    for _ in range(8):

        changed = False

        def replace(match):

            nonlocal replacements
            nonlocal changed

            expr = match.group(1)

            # Avoid accidentally touching Java shift syntax
            # where our simple parser cannot safely interpret it.
            value = safe_eval_integer(expr)

            if value is None:
                return expr

            replacements += 1
            changed = True

            return str(value)

        new_text = pattern.sub(
            replace,
            text,
        )

        text = new_text

        if not changed:
            break

    return text, replacements


# ============================================================
# MAPPING
# ============================================================

DEFAULT_MAPPING = {
    "classes": {
        "class_437": "Screen",
        "class_310": "MinecraftClient",
        "class_1268": "ClientPlayerEntity",
        "class_1799": "ItemStack",
        "class_342": "EditBox",
        "class_2561": "Component",
    },

    "methods": {},

    "fields": {},
}


def load_mapping() -> Dict:
    if not MAPPING_FILE.exists():
        save_mapping(DEFAULT_MAPPING)
        return DEFAULT_MAPPING.copy()

    try:
        with MAPPING_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        return data

    except Exception as exc:
        warning(f"Mapping lỗi: {exc}")
        return DEFAULT_MAPPING.copy()


def save_mapping(data: Dict):
    with MAPPING_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )


def build_flat_mapping() -> Dict[str, str]:
    data = load_mapping()

    flat = {}

    for group in (
        "classes",
        "methods",
        "fields",
    ):
        values = data.get(group, {})

        if isinstance(values, dict):
            flat.update(values)

    return flat


# ============================================================
# SAFE IDENTIFIER MAPPING
# ============================================================

JAVA_IDENTIFIER = re.compile(
    r"[A-Za-z_$][A-Za-z0-9_$]*"
)


def replace_identifiers(
    text: str,
    mapping: Dict[str, str],
) -> Tuple[str, int]:
    """
    Replace identifiers while avoiding strings and comments.

    This is intentionally a lightweight lexer, not a Java parser.
    """

    if not mapping:
        return text, 0

    tokens = []

    i = 0
    n = len(text)

    replacements = 0

    NORMAL = 0
    STRING = 1
    CHAR = 2
    LINE_COMMENT = 3
    BLOCK_COMMENT = 4

    state = NORMAL

    while i < n:

        ch = text[i]

        # ---------------------------
        # NORMAL
        # ---------------------------

        if state == NORMAL:

            if ch == '"':
                tokens.append(ch)
                state = STRING
                i += 1
                continue

            if ch == "'":
                tokens.append(ch)
                state = CHAR
                i += 1
                continue

            if ch == "/" and i + 1 < n:

                if text[i + 1] == "/":
                    tokens.append("//")
                    state = LINE_COMMENT
                    i += 2
                    continue

                if text[i + 1] == "*":
                    tokens.append("/*")
                    state = BLOCK_COMMENT
                    i += 2
                    continue

            match = JAVA_IDENTIFIER.match(
                text,
                i,
            )

            if match:
                word = match.group(0)

                if word in mapping:
                    tokens.append(mapping[word])
                    replacements += 1
                else:
                    tokens.append(word)

                i = match.end()
                continue

            tokens.append(ch)
            i += 1
            continue

        # ---------------------------
        # STRING
        # ---------------------------

        if state == STRING:

            tokens.append(ch)

            if ch == "\\" and i + 1 < n:
                tokens.append(text[i + 1])
                i += 2
                continue

            if ch == '"':
                state = NORMAL

            i += 1
            continue

        # ---------------------------
        # CHAR
        # ---------------------------

        if state == CHAR:

            tokens.append(ch)

            if ch == "\\" and i + 1 < n:
                tokens.append(text[i + 1])
                i += 2
                continue

            if ch == "'":
                state = NORMAL

            i += 1
            continue

        # ---------------------------
        # LINE COMMENT
        # ---------------------------

        if state == LINE_COMMENT:

            tokens.append(ch)

            if ch == "\n":
                state = NORMAL

            i += 1
            continue

        # ---------------------------
        # BLOCK COMMENT
        # ---------------------------

        if state == BLOCK_COMMENT:

            tokens.append(ch)

            if (
                ch == "*"
                and i + 1 < n
                and text[i + 1] == "/"
            ):
                tokens.append("/")
                i += 2
                state = NORMAL
                continue

            i += 1
            continue

    return "".join(tokens), replacements


# ============================================================
# SOURCE ANALYSIS
# ============================================================

def analyze_source(
    text: str,
) -> Dict:

    classes = sorted(
        set(CLASS_RE.findall(text))
    )

    methods = sorted(
        set(METHOD_RE.findall(text))
    )

    fields = sorted(
        set(FIELD_RE.findall(text))
    )

    variables = sorted(
        set(VAR_RE.findall(text))
    )

    xor_matches = XOR_RE.findall(text)

    strings = STRING_RE.findall(text)

    return {
        "classes": classes,
        "methods": methods,
        "fields": fields,
        "variables": variables,
        "xor_expressions": len(xor_matches),
        "strings": len(strings),
        "lines": text.count("\n") + 1,
    }


def analyze_jar(
    jar: Path,
) -> Dict:

    result = {
        "jar": str(jar),
        "size": jar.stat().st_size,
        "classes": 0,
        "class_files": [],
        "packages": {},
        "java_entries": 0,
    }

    try:

        with zipfile.ZipFile(jar, "r") as z:

            for name in z.namelist():

                if name.endswith(".class"):

                    result["classes"] += 1
                    result["class_files"].append(name)

                    parts = name.split("/")

                    if len(parts) > 1:
                        package = "/".join(parts[:-1])

                        result["packages"][package] = (
                            result["packages"].get(package, 0) + 1
                        )

                elif name.endswith(".java"):

                    result["java_entries"] += 1

    except zipfile.BadZipFile:
        result["error"] = "Invalid ZIP/JAR"

    return result


# ============================================================
# SOURCE CLEANUP
# ============================================================

def cleanup_java_source(
    text: str,
    mapping: Dict[str, str],
) -> Tuple[str, Dict]:

    stats = {
        "mapping_replacements": 0,
        "constant_replacements": 0,
    }

    # Mapping first.
    if CONFIG.apply_mapping:
        text, count = replace_identifiers(
            text,
            mapping,
        )

        stats["mapping_replacements"] = count

    # Constant folding.
    if CONFIG.simplify_constants:
        text, count = fold_integer_expressions(text)

        stats["constant_replacements"] = count

    # Normalize CRLF.
    text = text.replace(
        "\r\n",
        "\n",
    )

    # Remove excessive empty lines.
    if CONFIG.cleanup_whitespace:

        text = re.sub(
            r"\n{4,}",
            "\n\n\n",
            text,
        )

        text = "\n".join(
            line.rstrip()
            for line in text.splitlines()
        )

        text += "\n"

    return text, stats


# ============================================================
# PROCESS DECOMPILED DIRECTORY
# ============================================================

def process_source_directory(
    source_dir: Path,
    output_jar: Path,
) -> Dict:

    mapping = build_flat_mapping()

    report = {
        "files": 0,
        "java_files": 0,
        "mapping_replacements": 0,
        "constant_replacements": 0,
        "suspicious_classes": [],
        "suspicious_methods": [],
        "suspicious_fields": [],
        "xor_expressions": 0,
    }

    with zipfile.ZipFile(
        output_jar,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as out_zip:

        for path in source_dir.rglob("*"):

            if not path.is_file():
                continue

            relative = path.relative_to(
                source_dir
            )

            archive_name = str(
                relative
            ).replace(
                os.sep,
                "/",
            )

            report["files"] += 1

            if path.suffix.lower() == ".java":

                report["java_files"] += 1

                try:
                    text = path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )

                    analysis = analyze_source(text)

                    report["xor_expressions"] += (
                        analysis["xor_expressions"]
                    )

                    report["suspicious_classes"].extend(
                        analysis["classes"]
                    )

                    report["suspicious_methods"].extend(
                        analysis["methods"]
                    )

                    report["suspicious_fields"].extend(
                        analysis["fields"]
                    )

                    cleaned, stats = cleanup_java_source(
                        text,
                        mapping,
                    )

                    report["mapping_replacements"] += (
                        stats["mapping_replacements"]
                    )

                    report["constant_replacements"] += (
                        stats["constant_replacements"]
                    )

                    out_zip.writestr(
                        archive_name,
                        cleaned.encode("utf-8"),
                    )

                except Exception as exc:

                    warning(
                        f"Java cleanup failed: {archive_name}: {exc}"
                    )

                    out_zip.write(
                        path,
                        archive_name,
                    )

            else:

                out_zip.write(
                    path,
                    archive_name,
                )

    # Deduplicate report arrays.
    for key in (
        "suspicious_classes",
        "suspicious_methods",
        "suspicious_fields",
    ):
        report[key] = sorted(
            set(report[key])
        )

    return report


# ============================================================
# VALIDATE JAR
# ============================================================

def validate_jar(
    path: Path,
) -> bool:

    try:

        with zipfile.ZipFile(path, "r") as z:

            bad = z.testzip()

            if bad:
                error(
                    f"JAR corrupted: {bad}"
                )
                return False

            return True

    except Exception as exc:
        error(
            f"JAR validation failed: {exc}"
        )
        return False


# ============================================================
# DEOBF PIPELINE
# ============================================================

def deobfuscate(
    input_jar: Path,
) -> bool:

    if not input_jar.exists():
        error("Input không tồn tại.")
        return False

    if input_jar.suffix.lower() != ".jar":
        error("Chỉ hỗ trợ .jar trong pipeline này.")
        return False

    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    name = input_jar.stem

    work = (
        WORK_DIR
        / f"{name}_{timestamp}"
    )

    decompiled = work / "decompiled"

    work.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_jar = (
        OUTPUT_DIR
        / f"{name}_deobf.jar"
    )

    report_file = (
        REPORT_DIR
        / f"{name}_report.json"
    )

    print()
    print(c(
        f"=== DEOBF: {input_jar.name} ===",
        MAGENTA,
    ))

    # --------------------------------------------------------
    # STEP 1
    # --------------------------------------------------------

    progress("Phân tích JAR...")

    jar_report = analyze_jar(
        input_jar
    )

    success(
        f"Classes: {jar_report.get('classes', 0)}"
    )

    # --------------------------------------------------------
    # STEP 2
    # --------------------------------------------------------

    progress("Decompile bằng Vineflower...")

    if not run_vineflower(
        input_jar,
        decompiled,
    ):
        return False

    # --------------------------------------------------------
    # STEP 3
    # --------------------------------------------------------

    progress("Phân tích + cleanup source...")

    cleanup_report = process_source_directory(
        decompiled,
        source_jar,
    )

    # --------------------------------------------------------
    # STEP 4
    # --------------------------------------------------------

    progress("Validate output...")

    valid = validate_jar(
        source_jar
    )

    # --------------------------------------------------------
    # STEP 5
    # --------------------------------------------------------

    final_report = {
        "tool": "Minecraft Deobf Engine",
        "version": "3.0",
        "timestamp": timestamp,

        "input": str(input_jar),

        "vineflower": {
            "path": str(find_vineflower() or ""),
            "java": java_version(),
        },

        "configuration": asdict(CONFIG),

        "jar_analysis": jar_report,

        "cleanup": cleanup_report,

        "output": {
            "file": str(source_jar),
            "valid": valid,
            "size": (
                source_jar.stat().st_size
                if source_jar.exists()
                else 0
            ),
        },
    }

    with report_file.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            final_report,
            f,
            indent=2,
            ensure_ascii=False,
        )

    # --------------------------------------------------------
    # Cleanup work
    # --------------------------------------------------------

    if not CONFIG.keep_workdir:

        try:
            shutil.rmtree(work)
        except Exception:
            pass

    # --------------------------------------------------------
    # Result
    # --------------------------------------------------------

    print()

    if valid:

        success("DEOBF HOÀN TẤT")

        print()
        print(
            c(
                f"Output : {source_jar}",
                GREEN,
            )
        )

        print(
            c(
                f"Report : {report_file}",
                CYAN,
            )
        )

        print()
        print(
            f"Java files       : {cleanup_report['java_files']}"
        )

        print(
            f"Mapping changes  : {cleanup_report['mapping_replacements']}"
        )

        print(
            f"Constant folding : {cleanup_report['constant_replacements']}"
        )

        print(
            f"XOR detected     : {cleanup_report['xor_expressions']}"
        )

        print(
            f"Suspicious class : {len(cleanup_report['suspicious_classes'])}"
        )

        print(
            f"Suspicious method: {len(cleanup_report['suspicious_methods'])}"
        )

        print(
            f"Suspicious field : {len(cleanup_report['suspicious_fields'])}"
        )

        return True

    error("Output không hợp lệ.")
    return False


# ============================================================
# SELECT JAR
# ============================================================

def choose_jar() -> Optional[Path]:

    jars = sorted(
        INPUT_DIR.glob("*.jar")
    )

    if not jars:

        warning(
            f"Không có JAR trong: {INPUT_DIR}"
        )

        path = input(
            "Nhập đường dẫn JAR: "
        ).strip()

        if not path:
            return None

        return Path(path).expanduser()

    print()

    for i, jar in enumerate(
        jars,
        1,
    ):
        size_mb = jar.stat().st_size / 1024 / 1024

        print(
            f"{c(f'[{i}]', CYAN)} "
            f"{jar.name} "
            f"{DIM}({size_mb:.2f} MB){RESET}"
        )

    print(
        c("[0] Nhập path khác", YELLOW)
    )

    choice = input(
        "\nChọn: "
    ).strip()

    if choice == "0":

        path = input(
            "Path JAR: "
        ).strip()

        return Path(path).expanduser()

    try:

        index = int(choice) - 1

        if 0 <= index < len(jars):
            return jars[index]

    except ValueError:
        pass

    error("Lựa chọn không hợp lệ.")
    return None


# ============================================================
# BATCH
# ============================================================

def batch_deobfuscate():

    jars = sorted(
        INPUT_DIR.glob("*.jar")
    )

    if not jars:
        warning("Không có JAR.")
        return

    print(
        c(
            f"\nTìm thấy {len(jars)} JAR.",
            CYAN,
        )
    )

    for index, jar in enumerate(
        jars,
        1,
    ):

        print()
        print(
            c(
                f"[{index}/{len(jars)}] {jar.name}",
                MAGENTA,
            )
        )

        deobfuscate(jar)


# ============================================================
# MAPPING MANAGER
# ============================================================

def mapping_menu():

    while True:

        clear()
        banner()

        data = load_mapping()

        print(
            c("MAPPING MANAGER", MAGENTA)
        )
        print()

        print(
            f"Classes : {len(data.get('classes', {}))}"
        )

        print(
            f"Methods : {len(data.get('methods', {}))}"
        )

        print(
            f"Fields  : {len(data.get('fields', {}))}"
        )

        print()
        print("[1] Thêm mapping")
        print("[2] Xem mapping")
        print("[3] Xóa mapping")
        print("[4] Reset mapping")
        print("[0] Back")

        choice = input(
            "\n> "
        ).strip()

        if choice == "0":
            return

        if choice == "1":

            group = input(
                "Group (classes/methods/fields): "
            ).strip()

            if group not in (
                "classes",
                "methods",
                "fields",
            ):
                error("Group không hợp lệ.")
                pause()
                continue

            old = input(
                "Tên obfuscated: "
            ).strip()

            new = input(
                "Tên mới: "
            ).strip()

            if old and new:

                data.setdefault(
                    group,
                    {}
                )[old] = new

                save_mapping(data)

                success("Đã lưu mapping.")

            pause()

        elif choice == "2":

            print()

            print(
                json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False,
                )
            )

            pause()

        elif choice == "3":

            old = input(
                "Tên cần xóa: "
            ).strip()

            removed = False

            for group in (
                "classes",
                "methods",
                "fields",
            ):

                if old in data.get(group, {}):

                    del data[group][old]
                    removed = True

            save_mapping(data)

            if removed:
                success("Đã xóa.")
            else:
                warning("Không tìm thấy.")

            pause()

        elif choice == "4":

            save_mapping(DEFAULT_MAPPING)

            success("Mapping đã reset.")
            pause()


# ============================================================
# ANALYZE MENU
# ============================================================

def analyze_menu():

    jar = choose_jar()

    if not jar:
        pause()
        return

    if not jar.exists():

        error("File không tồn tại.")
        pause()
        return

    report = analyze_jar(
        jar
    )

    clear()
    banner()

    print(
        c("STATIC ANALYSIS", MAGENTA)
    )
    print()

    print(
        f"File       : {jar.name}"
    )

    print(
        f"Size       : {report['size'] / 1024 / 1024:.2f} MB"
    )

    print(
        f"Classes    : {report['classes']}"
    )

    print(
        f"Java files : {report['java_entries']}"
    )

    print()

    packages = report.get(
        "packages",
        {}
    )

    if packages:

        print(
            c("Top packages:", CYAN)
        )

        for package, count in sorted(
            packages.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:20]:

            print(
                f"  {count:5d}  {package}"
            )

    pause()


# ============================================================
# SETTINGS
# ============================================================

def settings_menu():

    while True:

        clear()
        banner()

        print(
            c("SETTINGS", MAGENTA)
        )
        print()

        print(
            f"[1] RAM Java          : {CONFIG.xmx}"
        )

        print(
            f"[2] Constant folding  : {CONFIG.simplify_constants}"
        )

        print(
            f"[3] XOR folding       : {CONFIG.simplify_xor}"
        )

        print(
            f"[4] Apply mapping     : {CONFIG.apply_mapping}"
        )

        print(
            f"[5] Keep workdir      : {CONFIG.keep_workdir}"
        )

        print(
            "[0] Back"
        )

        choice = input(
            "\n> "
        ).strip()

        if choice == "0":
            return

        if choice == "1":

            value = input(
                "RAM (example 1G / 2G / 4G): "
            ).strip()

            if re.fullmatch(
                r"\d+[MGmg]",
                value,
            ):
                CONFIG.xmx = value.upper()

            else:
                warning("RAM không hợp lệ.")

            pause()

        elif choice == "2":

            CONFIG.simplify_constants = (
                not CONFIG.simplify_constants
            )

        elif choice == "3":

            CONFIG.simplify_xor = (
                not CONFIG.simplify_xor
            )

        elif choice == "4":

            CONFIG.apply_mapping = (
                not CONFIG.apply_mapping
            )

        elif choice == "5":

            CONFIG.keep_workdir = (
                not CONFIG.keep_workdir
            )


# ============================================================
# SYSTEM CHECK
# ============================================================

def system_check():

    clear()
    banner()

    print(
        c("SYSTEM CHECK", MAGENTA)
    )
    print()

    print(
        f"Python      : {sys.version.split()[0]}"
    )

    print(
        f"Java        : {java_version()}"
    )

    vf = find_vineflower()

    if vf:

        print(
            c(
                f"Vineflower  : {vf}",
                GREEN,
            )
        )

        help_text = vineflower_help()

        if help_text:

            print(
                c(
                    "CLI help    : OK",
                    GREEN,
                )
            )

    else:

        print(
            c(
                "Vineflower  : NOT FOUND",
                RED,
            )
        )

    print(
        f"Input dir   : {INPUT_DIR}"
    )

    print(
        f"Output dir  : {OUTPUT_DIR}"
    )

    print(
        f"Report dir  : {REPORT_DIR}"
    )

    pause()


# ============================================================
# SINGLE
# ============================================================

def single_deobfuscate():

    jar = choose_jar()

    if not jar:
        pause()
        return

    if not jar.exists():

        error(
            f"Không tìm thấy: {jar}"
        )

        pause()
        return

    deobfuscate(jar)

    pause()


# ============================================================
# MAIN MENU
# ============================================================

def main_menu():

    while True:

        clear()
        banner()

        print(
            c("MAIN MENU", MAGENTA)
        )
        print()

        print(
            c("[1]", CYAN),
            "Deobfuscate JAR"
        )

        print(
            c("[2]", CYAN),
            "Batch Deobfuscate"
        )

        print(
            c("[3]", CYAN),
            "Static Analyze"
        )

        print(
            c("[4]", CYAN),
            "Mapping Manager"
        )

        print(
            c("[5]", CYAN),
            "Settings"
        )

        print(
            c("[6]", CYAN),
            "System Check"
        )

        print(
            c("[0]", RED),
            "Exit"
        )

        print()

        choice = input(
            c("> ", GREEN)
        ).strip()

        if choice == "1":
            single_deobfuscate()

        elif choice == "2":
            batch_deobfuscate()
            pause()

        elif choice == "3":
            analyze_menu()

        elif choice == "4":
            mapping_menu()

        elif choice == "5":
            settings_menu()

        elif choice == "6":
            system_check()

        elif choice == "0":
            clear()
            print(
                c(
                    "Bye!",
                    CYAN,
                )
            )
            break

        else:
            warning("Lựa chọn không hợp lệ.")
            time.sleep(0.7)


# ============================================================
# CLI MODE
# ============================================================

def cli_mode():

    if len(sys.argv) <= 1:
        main_menu()
        return

    command = sys.argv[1].lower()

    if command in (
        "--help",
        "-h",
    ):

        print("""
Minecraft Deobf Engine

Usage:
    python main.py
    python main.py deobf file.jar
    python main.py analyze file.jar
    python main.py batch
    python main.py system
    python main.py mapping

Examples:
    python main.py deobf input/mod.jar
    python main.py analyze input/mod.jar
    python main.py batch
""")

        return

    if command == "deobf":

        if len(sys.argv) < 3:

            error(
                "Thiếu file JAR."
            )

            return

        deobfuscate(
            Path(
                sys.argv[2]
            ).expanduser()
        )

        return

    if command == "analyze":

        if len(sys.argv) < 3:

            error(
                "Thiếu file JAR."
            )

            return

        jar = Path(
            sys.argv[2]
        ).expanduser()

        if not jar.exists():

            error(
                "File không tồn tại."
            )

            return

        result = analyze_jar(
            jar
        )

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

        return

    if command == "batch":

        batch_deobfuscate()
        return

    if command == "system":

        system_check()
        return

    if command == "mapping":

        mapping_menu()
        return

    error(
        f"Unknown command: {command}"
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:
        cli_mode()

    except KeyboardInterrupt:

        print()
        warning("Đã thoát.")

    except Exception as exc:

        print()
        error(
            f"Fatal error: {exc}"
        )

        raise
