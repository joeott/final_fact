# Claude Agents & Skills for final_fact

Legal document processing with specialized agents for treatise research and case document analysis.

---

## Agents (2)

### 1. kg-researcher
**Purpose:** Research legal treatises and cross-examination strategies
**Access:** Neo4j KG Graph (treatises)
**Use for:** Strategic guidance, impeachment techniques, trial advocacy principles

**Example:**
```bash
# Research impeachment by omission
claude --agent kg-researcher "Find techniques for impeaching witness who failed to investigate"
```

### 2. fact-researcher
**Purpose:** Research case documents and exhibits
**Access:** Neo4j FACT Graph (case documents)
**Use for:** Finding evidence, tracking contradictions, building timelines

**Example:**
```bash
# Find all mentions of fire suppression
claude --agent fact-researcher "Search Jostes case for fire suppression coverage discussions"
```

---

## Skills (2)

### 1. kg-research
**Executable:** `.claude/skills/kg-research/run.py`
**Purpose:** Query Cross-Examination treatise for strategic principles

**Usage:**
```bash
cd /Users/joe/Projects/final_fact
source venv/bin/activate

# Research impeachment techniques
python .claude/skills/kg-research/run.py \
  --search-terms "impeachment omission professional duty" \
  --limit 5

# Research loop technique
python .claude/skills/kg-research/run.py \
  --search-terms "loop technique emphasis repetition" \
  --include-examples
```

**Parameters:**
- `--search-terms` (required): Full-text search terms
- `--min-score` (optional): Minimum relevance score (default: 2.0)
- `--limit` (optional): Max results (default: 10)
- `--include-examples` (flag): Include practical examples
- `--output` (optional): Write to file instead of stdout

### 2. fact-research
**Executable:** `.claude/skills/fact-research/run.py`
**Purpose:** Query case documents for evidence and exhibit support

**Usage:**
```bash
cd /Users/joe/Projects/final_fact
source venv/bin/activate

# Search for specific facts
python .claude/skills/fact-research/run.py \
  --case-name "Jostes_depo" \
  --search-terms "fire suppression" \
  --limit 10

# Get complete exhibit content
python .claude/skills/fact-research/run.py \
  --case-name "Jostes_depo" \
  --exhibit-name "Exhibit 7 - Initial Report, Reserves"

# Track entity mentions
python .claude/skills/fact-research/run.py \
  --case-name "Jostes_depo" \
  --entity-name "Dave Jostes"

# Find contradictions
python .claude/skills/fact-research/run.py \
  --case-name "Jostes_depo" \
  --search-terms "coverage" \
  --find-contradictions

# Build timeline
python .claude/skills/fact-research/run.py \
  --case-name "Jostes_depo" \
  --build-timeline
```

**Parameters:**
- `--case-name` (required): Case name
- `--project-uuid` (optional): Auto-determined from case name
- `--search-terms` (optional): Search terms
- `--exhibit-name` (optional): Specific exhibit to retrieve
- `--entity-name` (optional): Entity to track
- `--find-contradictions` (flag): Search for contradictions
- `--build-timeline` (flag): Extract timeline
- `--limit` (optional): Max results (default: 20)
- `--output` (optional): Write to file

---

## Workflow Examples

### Workflow 1: Build Cross-Examination Outline

```bash
# Step 1: Research impeachment techniques (KG)
python .claude/skills/kg-research/run.py \
  --search-terms "impeachment omission eight steps" \
  --output research/impeachment_techniques.md

# Step 2: Find supporting exhibits (FACT)
python .claude/skills/fact-research/run.py \
  --case-name "Jostes_depo" \
  --search-terms "reserve" \
  --output research/reserve_evidence.md

# Step 3: Find contradictions (FACT)
python .claude/skills/fact-research/run.py \
  --case-name "Jostes_depo" \
  --search-terms "fire suppression" \
  --find-contradictions \
  --output research/fire_suppression_contradictions.md

# Step 4: Build timeline (FACT)
python .claude/skills/fact-research/run.py \
  --case-name "Jostes_depo" \
  --build-timeline \
  --output research/case_timeline.md
```

### Workflow 2: Enhance Existing Outline

```bash
# Step 1: Get strategic guidance on closing
python .claude/skills/kg-research/run.py \
  --search-terms "power closing commitment trilogy" \
  --include-examples

# Step 2: Find all exhibit references for specific claim
python .claude/skills/fact-research/run.py \
  --case-name "Jostes_depo" \
  --search-terms "1,460,000" \
  --limit 5

# Step 3: Track key witness mentions
python .claude/skills/fact-research/run.py \
  --case-name "Jostes_depo" \
  --entity-name "Nicole Brasser"
```

### Workflow 3: Interactive Research with Agents

```bash
# Launch KG researcher for strategic session
claude --agent kg-researcher

# Then ask questions:
# "Find the eight steps of impeachment by prior inconsistent statement"
# "What does the treatise say about sequencing chapters?"
# "How do I use the loop technique effectively?"

# Launch FACT researcher for evidence gathering
claude --agent fact-researcher

# Then ask questions:
# "Find all mentions of coverage determination in Jostes case"
# "Show me the complete Exhibit 7"
# "Track all communications from Dave Jostes"
```

---

## Integration with Pipeline

The agents and skills integrate with the final_fact document processing pipeline:

```
PDF → OCR → Chunking → Neo4j FACT Graph
                              ↓
                    [fact-researcher agent]
                              ↓
                    Find evidence & exhibits
                              ↓
                    [kg-researcher agent]
                              ↓
                    Add strategic guidance
                              ↓
                    Enhanced cross-exam outline
```

---

## Directory Structure

```
.claude/
├── README.md                      # This file
├── agents/
│   ├── kg-researcher.md          # Treatise research agent
│   └── fact-researcher.md        # Case document research agent
└── skills/
    ├── kg-research/              # Knowledge Graph query skill
    │   ├── skill.json           # Skill metadata
    │   └── run.py               # Executable script
    └── fact-research/           # FACT Graph query skill
        ├── skill.json           # Skill metadata
        └── run.py               # Executable script
```

---

## Requirements

Both skills require:
- Python 3.13+ with neo4j driver
- Credentials in `/Users/joe/Projects/.env`
- Virtual environment activated

**Setup:**
```bash
cd /Users/joe/Projects/final_fact
source venv/bin/activate
# Skills are now ready to use
```

---

## Credentials Required

**In `/Users/joe/Projects/.env`:**

```bash
# Knowledge Graph (treatises)
NEO4J_KG_URI=neo4j+s://99fa778c.databases.neo4j.io
NEO4J_KG_USERNAME=neo4j
NEO4J_KG_PASSWORD=...

# FACT Graph (case documents)
NEO4J_FACT_URI=neo4j+s://6d98f1e5.databases.neo4j.io
NEO4J_FACT_USERNAME=neo4j
NEO4J_FACT_PASSWORD=...
```

---

## Future Enhancements

- Add MCP server integration for Claude Desktop
- Create hybrid queries (KG + FACT combined)
- Add citation network analysis
- Build visual timeline generators
- Create automated outline enhancement pipelines

---

**Version:** 1.0.0
**Created:** 2026-01-20
**Project:** final_fact legal document processing
