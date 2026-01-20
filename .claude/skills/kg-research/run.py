#!/usr/bin/env python3
"""
KG Research Skill - Query Cross-Examination Treatise

Searches the Neo4j Knowledge Graph for legal treatise content and provides
strategic guidance for cross-examination preparation.
"""

import argparse
import json
import sys
from pathlib import Path
from neo4j import GraphDatabase
from dotenv import load_dotenv
import os


def load_neo4j_kg_driver():
    """Load Neo4j KG connection from .env"""
    env_path = Path('/Users/joe/Projects/.env')
    load_dotenv(env_path)

    uri = os.getenv('NEO4J_KG_URI')
    username = os.getenv('NEO4J_KG_USERNAME')
    password = os.getenv('NEO4J_KG_PASSWORD')

    if not all([uri, username, password]):
        raise RuntimeError("Missing Neo4j KG credentials in /Users/joe/Projects/.env")

    return GraphDatabase.driver(uri, auth=(username, password))


def search_treatise(session, search_terms: str, min_score: float = 2.0, limit: int = 10):
    """Full-text search across treatises"""
    query = '''
        CALL db.index.fulltext.queryNodes('chunk_fulltext', $search_terms)
        YIELD node, score
        MATCH (node:Chunk)-[:HAS_CHUNK]-(t:Treatise)
        WHERE score > $min_score
        RETURN node.section_title as section,
               node.text as content,
               node.page_number as page,
               node.hierarchy_level as level,
               t.title as treatise,
               score
        ORDER BY score DESC
        LIMIT $limit
    '''

    result = session.run(query, search_terms=search_terms, min_score=min_score, limit=limit)
    return list(result)


def get_sequential_content(session, section_title: str, max_depth: int = 5):
    """Get sequential content following NEXT_CHUNK relationships"""
    query = '''
        MATCH (c:Chunk)-[:HAS_CHUNK]-(t:Treatise)
        WHERE t.title CONTAINS 'Cross'
          AND c.section_title = $section_title
        WITH c LIMIT 1
        MATCH path = (c)-[:NEXT_CHUNK*0..$max_depth]->(next:Chunk)
        RETURN [node IN nodes(path) | {
          section: node.section_title,
          text: node.text,
          page: node.page_number,
          level: node.hierarchy_level
        }] AS sequential_content
    '''

    result = session.run(query, section_title=section_title, max_depth=max_depth)
    record = result.single()
    return record['sequential_content'] if record else []


def format_output(results, include_examples: bool = True):
    """Format research results as markdown"""
    output = []
    output.append("# Knowledge Graph Research Results\n")

    if not results:
        output.append("No results found. Try broader search terms.\n")
        return "\n".join(output)

    output.append(f"**Found {len(results)} relevant sections:**\n")

    for i, record in enumerate(results, 1):
        output.append(f"\n## {i}. {record['section']}")
        output.append(f"**Treatise:** {record['treatise']}")
        output.append(f"**Page:** {record['page']}")
        output.append(f"**Relevance Score:** {record['score']:.2f}")
        output.append(f"**Hierarchy Level:** {record['level']}\n")

        # Content
        content = record['content']
        if len(content) > 800 and not include_examples:
            content = content[:800] + "..."

        output.append("**Content:**")
        output.append(f"```\n{content}\n```\n")

        # Extract examples if present
        if include_examples and "Example:" in content or "Q:" in content:
            output.append("*Note: This section contains practical examples or sample questions.*\n")

        output.append("---\n")

    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(description="Research legal treatises in KG Graph")
    parser.add_argument('--search-terms', required=True, help='Full-text search terms')
    parser.add_argument('--min-score', type=float, default=2.0, help='Minimum relevance score')
    parser.add_argument('--limit', type=int, default=10, help='Max results to return')
    parser.add_argument('--include-examples', action='store_true', default=True, help='Include examples')
    parser.add_argument('--topic', help='Specific topic for sequential content')
    parser.add_argument('--output', help='Output file path (default: stdout)')

    args = parser.parse_args()

    try:
        driver = load_neo4j_kg_driver()

        with driver.session() as session:
            # Execute search
            results = search_treatise(
                session,
                search_terms=args.search_terms,
                min_score=args.min_score,
                limit=args.limit
            )

            # Format output
            output = format_output(results, include_examples=args.include_examples)

            # Write output
            if args.output:
                Path(args.output).write_text(output)
                print(f"✓ Results written to {args.output}")
            else:
                print(output)

        driver.close()
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
