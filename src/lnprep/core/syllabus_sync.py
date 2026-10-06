"""
Syllabus & Assessment Brief auto-sync parser.
Scans a module directory for Teaching and Learning Plans, Module Descriptors,
and Assignment Briefs (docx, pdf) and extracts MLOs and assessment tasks.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, List

try:
    import docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

DEFAULT_MLOS = {
    "MO9529": [
        "MLO 1: Understand the context of global and regional integrated operations and supply chain management, its likely future direction, and the impact of its strategies and tools on the future direction in global business.",
        "MLO 2: Demonstrate understanding of various tools, strategies, key skills, and techniques that can be used in any global or regional operations and supply chain management area in different sectors with different sizes of the organisations with the support of contemporary research - enriched material.",
        "MLO 3: Problem solving skills in global business context associated with different contemporary operational and supply chain issues and strategies with the support of cross-functional thinking, critical reading, intensive and extensive research, teamwork and presentation skills.",
        "MLO 4: Ethical and social awareness and cultural interface in global operations, and supply chain environment.",
    ]
}


def extract_text_from_docx(file_path: str) -> str:
    """Extract text and tables from a docx file."""
    if not HAS_DOCX:
        return ""
    try:
        doc = docx.Document(file_path)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        table_text = []
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells if cell.text.strip()]
                if cells:
                    table_text.append(" | ".join(cells))
        return "\n".join(paragraphs + table_text)
    except Exception as e:
        sys.stderr.write(f"Warning: could not read {file_path}: {e}\n")
        return ""


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from a PDF file using PyMuPDF (fitz)."""
    if not HAS_FITZ:
        return ""
    try:
        doc = fitz.open(file_path)
        pages = [page.get_text() for page in doc]
        return "\n".join(pages)
    except Exception as e:
        sys.stderr.write(f"Warning: could not read {file_path}: {e}\n")
        return ""


def find_syllabus_files(module_folder: str) -> List[str]:
    """Locate TLP, Assessment Brief, and Module Descriptor documents."""
    syllabus_files: List[str] = []
    abs_start = os.path.abspath(module_folder)
    search_dirs = [abs_start]
    curr = abs_start
    for _ in range(3):
        p = os.path.dirname(curr)
        if p == curr:
            break
        search_dirs.append(p)
        curr = p

    for sdir in search_dirs:
        if not os.path.isdir(sdir):
            continue
        for file in os.listdir(sdir):
            lower = file.lower()
            if lower.startswith("~$"):
                continue
            if lower.endswith((".docx", ".pdf", ".doc")):
                if any(
                    k in lower
                    for k in [
                        "teaching and learning plan",
                        "tlp",
                        "assignment brief",
                        "module descriptor",
                        "module specification",
                        "handbook",
                        "marking guide",
                    ]
                ):
                    full_p = os.path.join(sdir, file)
                    if full_p not in syllabus_files:
                        syllabus_files.append(full_p)
        if syllabus_files:
            break
    return syllabus_files


def extract_mlos_from_text(text: str, module_code: str = "") -> List[str]:
    """Extract Module Learning Outcomes from document text."""
    if module_code in DEFAULT_MLOS:
        return list(DEFAULT_MLOS[module_code])

    mlos: List[str] = []
    mlo_match = re.search(r"able to demonstrate:?\s*((?:\d+[\)\.]\s*[^\n]+(?:\n|$))+)", text, re.IGNORECASE)
    if mlo_match:
        items = re.split(r"\s*(?=\d+[\)\.]|\bMLO\s*\d+)", mlo_match.group(1).strip())
        for item in items:
            c = item.strip()
            if len(c) > 15:
                c = re.sub(r"^\d+[\)\.]\s*", "", c)
                mlos.append(c)

    if not mlos:
        mlos = [
            "NEEDS WILSON — no MLOs parsed from the TLP/handbook; state the official outcomes"
        ]
    return mlos


def extract_assessments_from_text(text: str) -> List[Dict[str, Any]]:
    """Extract assessment details (word counts, tasks, weighting)."""
    wc_matches = re.findall(r"(\d+[\d,]*)\s*words", text, re.IGNORECASE)
    word_counts = [m.replace(",", "") for m in wc_matches if int(m.replace(",", "")) >= 500]
    task_matches = re.findall(r"(Task\s*\d+[:\s][^\.\n]{5,80})", text, re.IGNORECASE)
    is_individual = bool(re.search(r"\bindividual\b", text, re.IGNORECASE))
    is_group = bool(re.search(r"\bgroup\b", text, re.IGNORECASE))

    return [{
        "type": "individual" if is_individual else ("group" if is_group else "coursework"),
        "word_counts": list(dict.fromkeys(word_counts))[:3],
        "tasks": list(dict.fromkeys(task_matches))[:5],
    }]


def parse_syllabus(module_folder: str) -> Dict[str, Any]:
    """Scan module folder and parse syllabus components."""
    abs_folder = os.path.abspath(module_folder)
    files = find_syllabus_files(abs_folder)
    all_text = ""
    for f in files:
        if f.endswith(".docx"):
            all_text += "\n" + extract_text_from_docx(f)
        elif f.endswith(".pdf"):
            all_text += "\n" + extract_text_from_pdf(f)

    m = re.search(r"\b([A-Z]+\d+)\b", abs_folder)
    code = m.group(1) if m else "UNKNOWN"
    m_title = re.search(r"([A-Z]+\d+)\.([^\/]+)", abs_folder)
    title = m_title.group(2).replace("_", " ") if m_title else os.path.basename(abs_folder)

    mlos = extract_mlos_from_text(all_text, code)
    assessments = extract_assessments_from_text(all_text)

    return {
        "module_code": code,
        "module_title": title,
        "syllabus_files": [os.path.basename(f) for f in files],
        "module_learning_outcomes": mlos,
        "assessments": assessments,
    }


INSTITUTION_STYLES = {
    "NTB": "strategic-case-based",
    "KAPLAN": "practical",
    "MU": "analytical",
    "UCD": "theoretical",
    "BANGOR": "practical",
    "BCU": "practical",
    "RHUL": "theoretical",
    "TU": "practical",
    "UNISA": "analytical",
    "UOE": "analytical",
    "DBA": "theoretical",
    "ACTA": "practical",
    "SHELTON": "practical",
}

INSTITUTION_NAMES = {
    "NTB": "Northumbria University (via Kaplan Singapore)",
    "KAPLAN": "Kaplan Singapore",
    "MU": "Murdoch University (via Kaplan Singapore)",
    "UCD": "University College Dublin (via Kaplan Singapore)",
    "BANGOR": "Bangor University (via Kaplan Singapore)",
    "BCU": "Birmingham City University (via Kaplan Singapore)",
    "RHUL": "Royal Holloway, University of London (via Kaplan Singapore)",
    "TU": "Temasek Polytechnic",
    "UNISA": "University of South Australia",
    "UOE": "University of Edinburgh",
    "DBA": "Doctor of Business Administration",
    "ACTA": "ACTA (Singapore)",
    "SHELTON": "Shelton College International",
}

INSTITUTION_LEVELS = {
    "NTB": "Intermediate",
    "KAPLAN": "Intermediate",
    "MU": "Intermediate",
    "UCD": "Advanced",
    "BANGOR": "Intermediate",
    "BCU": "Intermediate",
    "RHUL": "Advanced",
    "TU": "Foundational",
    "UNISA": "Intermediate",
    "UOE": "Advanced",
    "DBA": "Advanced",
    "ACTA": "Foundational",
    "SHELTON": "Intermediate",
}


def parse_module_folder(folder_path: str) -> tuple[str, str]:
    """Parse module code and name from folder name."""
    folder_name = os.path.basename(os.path.abspath(folder_path))
    m = re.match(r"^([A-Z]+\d+)\.(.+)$", folder_name)
    if m:
        return m.group(1), m.group(2).replace("_", " ")
    m = re.match(r"^([A-Z]+\d+)\s+(.+)$", folder_name)
    if m:
        return m.group(1), m.group(2)
    return folder_name, folder_name


def detect_institution(folder_path: str) -> str | None:
    """Detect institution from parent folder name."""
    parent = os.path.basename(os.path.dirname(os.path.abspath(folder_path)))
    if parent in INSTITUTION_NAMES:
        return parent
    grandparent = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(folder_path))))
    if grandparent in INSTITUTION_NAMES:
        return grandparent
    return None


def scan_session_folders(folder_path: str) -> list[int]:
    """Scan for session folders to detect session structure."""
    session_folders = []
    search_paths = [
        os.path.join(folder_path, "Teaching_Materials"),
        os.path.join(folder_path, "Materials", "Lecture Materials"),
        os.path.join(folder_path, "Materials"),
        folder_path,
    ]
    for base in search_paths:
        if not os.path.isdir(base):
            continue
        for item in os.listdir(base):
            item_path = os.path.join(base, item)
            if os.path.isdir(item_path):
                m = re.match(r"^(?:Session|Week)[_\s]?(\d+)$", item, re.IGNORECASE)
                if m:
                    session_folders.append((int(m.group(1)), item_path))
        if session_folders:
            break
    session_folders.sort(key=lambda x: x[0])
    return [s[0] for s in session_folders]


def scan_pptx_files(folder_path: str, session_num: int) -> list[str]:
    """Scan for PPTX files in a session folder to extract topic names."""
    search_paths = [
        os.path.join(folder_path, "Teaching_Materials", f"Session_{session_num}"),
        os.path.join(folder_path, "Materials", "Lecture Materials", f"Session_{session_num}"),
        os.path.join(folder_path, "Materials", f"Session_{session_num}"),
        os.path.join(folder_path, f"Session_{session_num}"),
        os.path.join(folder_path, f"Session {session_num}"),
        os.path.join(folder_path, f"Week_{session_num}"),
        os.path.join(folder_path, f"Week {session_num}"),
    ]
    for path in search_paths:
        if not os.path.isdir(path):
            continue
        pptx_files = [f for f in os.listdir(path) if f.endswith(".pptx")]
        if pptx_files:
            topics = []
            for f in sorted(pptx_files):
                name = re.sub(r"^[\d.-]+\s*", "", f.replace(".pptx", ""))
                name = re.sub(r"[_-]?slide$", "", name, flags=re.IGNORECASE)
                name = re.sub(r"^L\d[-_]|Lectures?[\s_&]+\d+[\s_&-]*", "", name)
                if name:
                    topics.append(name.strip())
            return topics
    return []


def read_existing_agents_md(folder_path: str) -> dict[str, str]:
    """Read existing AGENTS.md for any pre-configured values."""
    agents_path = os.path.join(folder_path, "AGENTS.md")
    if not os.path.exists(agents_path):
        return {}
    try:
        with open(agents_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return {}

    info: dict[str, str] = {}
    m = re.search(r"class\s+size[:\s]+(\d+)\+?", content, re.IGNORECASE)
    if m:
        info["class_size"] = m.group(1)
    m = re.search(r"programme[:\s]+[\"']?([^\"'\n]+)", content, re.IGNORECASE)
    if m:
        info["programme"] = m.group(1).strip()
    m = re.search(r"level[:\s]+[\"']?([^\"'\n]+)", content, re.IGNORECASE)
    if m:
        info["level"] = m.group(1).strip()
    return info


def generate_guide(
    folder_path: str,
    class_size: int | None = None,
    style: str | None = None,
    force: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    """Generate LECTURE_NOTES_GUIDE.md for a module folder."""
    abs_folder = os.path.abspath(folder_path)
    guide_path = os.path.join(abs_folder, "LECTURE_NOTES_GUIDE.md")
    if os.path.exists(guide_path) and not force:
        return False, f"Guide already exists at {guide_path}. Use --force to overwrite.", {}

    module_code, module_name = parse_module_folder(abs_folder)
    institution_code = detect_institution(abs_folder)
    institution_name = INSTITUTION_NAMES.get(institution_code or "", "Unknown Institution")
    institution_level = INSTITUTION_LEVELS.get(institution_code or "", "Intermediate")
    institution_style = INSTITUTION_STYLES.get(institution_code or "", "strategic-case-based")

    agents_info = read_existing_agents_md(abs_folder)
    if class_size:
        agents_info["class_size"] = str(class_size)
    if style:
        institution_style = style

    session_nums = scan_session_folders(abs_folder)
    total_sessions = len(session_nums) if session_nums else 8

    session_topics = []
    for sn in range(1, total_sessions + 1):
        topics = scan_pptx_files(abs_folder, sn)
        if topics:
            session_topics.append({"number": sn, "topics": topics})

    if os.path.isdir(os.path.join(abs_folder, "Teaching_Materials")):
        materials_path = "Teaching_Materials/Session_N/"
    elif os.path.isdir(os.path.join(abs_folder, "Materials")):
        materials_path = "Materials/Session_N/"
    else:
        materials_path = "Session_N/"

    term_folder = "_Classes/YYYY.MM/"

    mlos_list: list[str] = []
    try:
        syllabus_data = parse_syllabus(abs_folder)
        if syllabus_data.get("module_learning_outcomes"):
            mlos_list = syllabus_data["module_learning_outcomes"]
    except Exception:
        pass

    if not mlos_list:
        mlos_list = [
            "NEEDS WILSON — official MLOs not parsed from the TLP/handbook; state them here"
        ]

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d")
    mlos_yaml = "\n".join(f'  - "{m}"' for m in mlos_list)

    guide_content = f"""# LECTURE_NOTES_GUIDE — {module_code}

> Auto-generated by `lnprep init` on {now} (lnprep v1.0.0)
> Review and update the values below for accuracy.

## Module Identity

```yaml
module_code: "{module_code}"
module_name: "{module_name}"
institution: "{institution_name}"
programme: "{agents_info.get('programme', 'Programme Name')}"
level: "{agents_info.get('level', institution_level)}"
class_size: {agents_info.get('class_size', '30')}
style: "{institution_style}"
```

## Module Learning Outcomes (MLOs)

```yaml
mlos:
{mlos_yaml}
```

## Session Structure

```yaml
total_sessions: {total_sessions}
teaching_materials_path: "{materials_path}"
term_folder: "{term_folder}"
```

## Lecture Notes Format

> The note format is **not** defined here. It lives in `NOTES_FORMAT.md` at the
> module root. This guide holds the session plan (decks, blocks, timings, assessment links).

## Institution Style Bias

```yaml
style: "{institution_style}"    # practical | analytical | strategic-case-based | theoretical
```

- **practical** (KAPLAN) — employability skills, hands-on tools, exam alignment
- **analytical** (Murdoch) — consumer behavior, research methodology, data evaluation
- **strategic-case-based** (Northumbria) — Harvard case methods, Asian business context, supply chain crises
- **theoretical** (UCD) — strategic decisions, corporate governance, decision frameworks

## Assessment Links

```yaml
assessments: []                  # NEEDS WILSON — read from the assignment brief; NOT auto-filled
```

## Session Topics (Optional)

```yaml
sessions:
"""
    for st in session_topics:
        guide_content += f"""  - number: {st['number']}
    date: "2026-XX-XX"
    topics:
"""
        for topic in st["topics"]:
            guide_content += f'      - "{topic}"\n'

    if not session_topics:
        guide_content += """  - number: 1
    date: "2026-XX-XX"
    topics:
      - "Topic 1"
      - "Topic 2"
  - number: 2
    date: "2026-XX-XX"
    topics:
      - "Topic 1"
      - "Topic 2"
"""

    with open(guide_path, "w", encoding="utf-8") as f:
        f.write(guide_content)

    meta = {
        "guide_path": guide_path,
        "module_code": module_code,
        "module_name": module_name,
        "institution": institution_name,
        "total_sessions": total_sessions,
        "topics_extracted": sum(len(st["topics"]) for st in session_topics),
    }
    return True, f"Generated {guide_path}", meta

