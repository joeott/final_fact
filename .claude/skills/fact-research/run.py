#!/usr/bin/env python3
"""
FACT Research Skill - Query Case Documents

Searches the Neo4j FACT Graph for case-specific documents and builds
exhibit-referenced cross-examination support.
"""

import argparse
import json
import sys
from pathlib import Path
from neo4j import GraphDatabase
from dotenv import load_dotenv
import os
from uuid import uuid5, NAMESPACE_DNS


def load_neo4j_fact_driver():
    """Load Neo4j FACT connection from .env"""
    env_path = Path('/Users/joe/Projects/.env')
    load_dotenv(env_path)

    uri = os.getenv('NEO4J_FACT_URI')
    username = os.getenv('NEO4J_FACT_USERNAME')
    password = os.getenv('NEO4J_FACT_PASSWORD')

    if not all([uri, username, password]):
        raise RuntimeError("Missing Neo4j FACT credentials in /Users/joe/Projects/.env")

    return GraphDatabase.driver(uri, auth=(username, password))


def deterministic_project_uuid(case_name: str) -> str:
    """Generate deterministic project UUID from case name (matches config.py)"""
    # Match config.py: _deterministic_uuid5("final_fact_project", case_name)
    namespace = uuid5(NAMESPACE_DNS, "final_fact_project")
    project_uuid = str(uuid5(namespace, case_name))
    return project_uuid


def search_chunks(session, project_uuid: str, search_terms: str, limit: int = 20):
    """Search for chunks containing search terms"""
    query = '''
        MATCH (c:CaseChunk {project_uuid: $project_uuid})
        WHERE toLower(c.text) CONTAINS toLower($search_terms)
        RETURN c.exhibit_name as exhibit,
               c.page_number as page,
               c.chunk_index as chunk,
               c.text as content
        ORDER BY c.exhibit_name, c.chunk_index
        LIMIT $limit
    '''

    result = session.run(query, project_uuid=project_uuid, search_terms=search_terms, limit=limit)
    return list(result)


def get_exhibit_content(session, project_uuid: str, exhibit_name: str):
    """Get all chunks from specific exhibit"""
    query = '''
        MATCH (c:CaseChunk {
          project_uuid: $project_uuid,
          exhibit_name: $exhibit_name
        })
        RETURN c.chunk_index,
               c.page_number,
               c.text
        ORDER BY c.chunk_index
    '''

    result = session.run(query, project_uuid=project_uuid, exhibit_name=exhibit_name)
    return list(result)


def track_entity(session, project_uuid: str, entity_name: str, limit: int = 20):
    """Track mentions of specific entity"""
    query = '''
        MATCH (e:CanonicalEntity {project_uuid: $project_uuid})
        WHERE toLower(e.canonical_form) CONTAINS toLower($entity_name)
           OR any(variant IN e.variant_forms WHERE toLower(variant) CONTAINS toLower($entity_name))
        OPTIONAL MATCH (e)<-[:MENTIONED_IN]-(c:CaseChunk)
        OPTIONAL MATCH (c)<-[:HAS_CHUNK]-(d:CaseDocument)
        RETURN e.canonical_form as entity,
               e.entity_type as type,
               d.exhibit_name as exhibit,
               c.page_number as page,
               substring(c.text, 0, 250) as context
        ORDER BY d.exhibit_name, c.chunk_index
        LIMIT $limit
    '''

    result = session.run(query, project_uuid=project_uuid, entity_name=entity_name, limit=limit)
    return list(result)


def find_contradictions(session, project_uuid: str, topic: str, limit: int = 10):
    """Find potentially contradictory statements on same topic across exhibits"""
    query = '''
        MATCH (c1:CaseChunk {project_uuid: $project_uuid})
        WHERE toLower(c1.text) CONTAINS toLower($topic)
        MATCH (c2:CaseChunk {project_uuid: $project_uuid})
        WHERE toLower(c2.text) CONTAINS toLower($topic)
          AND c1.document_uuid <> c2.document_uuid
          AND c1.chunk_uuid < c2.chunk_uuid
        RETURN c1.exhibit_name as exhibit1,
               c1.page_number as page1,
               substring(c1.text, 0, 250) as statement1,
               c2.exhibit_name as exhibit2,
               c2.page_number as page2,
               substring(c2.text, 0, 250) as statement2
        LIMIT $limit
    '''

    result = session.run(query, project_uuid=project_uuid, topic=topic, limit=limit)
    return list(result)


def build_timeline(session, project_uuid: str):
    """Extract timeline of events from date entities"""
    query = '''
        MATCH (e:CanonicalEntity {
          project_uuid: $project_uuid,
          entity_type: 'Date'
        })
        OPTIONAL MATCH (e)<-[:MENTIONED_IN]-(c:CaseChunk)
        OPTIONAL MATCH (c)<-[:HAS_CHUNK]-(d:CaseDocument)
        RETURN e.canonical_form as date,
               d.exhibit_name as exhibit,
               c.page_number as page,
               substring(c.text, 0, 200) as event
        ORDER BY e.canonical_form
    '''

    result = session.run(query, project_uuid=project_uuid)
    return list(result)


def format_search_results(results):
    """Format search results as markdown"""
    output = []
    output.append(f"\n**Found {len(results)} mentions:**\n")

    for i, record in enumerate(results, 1):
        output.append(f"### {i}. {record['exhibit']} (Page {record['page']})")
        output.append(f"**Chunk:** {record['chunk']}\n")
        content = record['content']
        if len(content) > 500:
            content = content[:500] + "..."
        output.append(f"```\n{content}\n```\n")

    return "\n".join(output)


def format_exhibit_results(results, exhibit_name):
    """Format complete exhibit content"""
    output = []
    output.append(f"\n# Complete Content: {exhibit_name}\n")
    output.append(f"**Total Chunks:** {len(results)}\n")

    for record in results:
        output.append(f"\n## Chunk {record['c.chunk_index']} (Page {record['c.page_number']})\n")
        output.append(f"```\n{record['c.text']}\n```\n")

    return "\n".join(output)


def format_entity_results(results):
    """Format entity tracking results"""
    output = []

    if not results:
        output.append("\nNo entity mentions found.\n")
        return "\n".join(output)

    # Group by entity
    entity = results[0]['entity']
    entity_type = results[0]['type']

    output.append(f"\n# Entity: {entity}")
    output.append(f"**Type:** {entity_type}")
    output.append(f"**Mentions:** {len(results)}\n")

    for i, record in enumerate(results, 1):
        if record['exhibit']:
            output.append(f"### {i}. {record['exhibit']} (Page {record['page']})")
            output.append(f"```\n{record['context']}...\n```\n")

    return "\n".join(output)


def format_contradiction_results(results):
    """Format contradiction analysis"""
    output = []
    output.append(f"\n**Found {len(results)} potential contradictions:**\n")

    for i, record in enumerate(results, 1):
        output.append(f"### Contradiction {i}:")
        output.append(f"**Exhibit 1:** {record['exhibit1']} (Page {record['page1']})")
        output.append(f"```\n{record['statement1']}...\n```\n")
        output.append(f"**Exhibit 2:** {record['exhibit2']} (Page {record['page2']})")
        output.append(f"```\n{record['statement2']}...\n```\n")
        output.append("**Analysis Required:** Review both statements to determine if they contradict.\n")

    return "\n".join(output)


def format_timeline_results(results):
    """Format timeline"""
    output = []
    output.append(f"\n# Case Timeline\n")
    output.append(f"**Total Events:** {len(results)}\n")

    for record in results:
        if record['date']:
            output.append(f"\n### {record['date']}")
            if record['exhibit']:
                output.append(f"**Source:** {record['exhibit']} (Page {record['page']})")
                output.append(f"**Event:** {record['event']}...\n")

    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(description="Research case documents in FACT Graph")
    parser.add_argument('--case-name', required=True, help='Case name')
    parser.add_argument('--project-uuid', help='Project UUID (auto-determined if not provided)')
    parser.add_argument('--search-terms', help='Search terms')
    parser.add_argument('--exhibit-name', help='Specific exhibit to retrieve')
    parser.add_argument('--entity-name', help='Entity to track')
    parser.add_argument('--find-contradictions', action='store_true', help='Find contradictions')
    parser.add_argument('--build-timeline', action='store_true', help='Build timeline')
    parser.add_argument('--limit', type=int, default=20, help='Max results')
    parser.add_argument('--output', help='Output file path (default: stdout)')

    args = parser.parse_args()

    # Determine project UUID
    if args.project_uuid:
        project_uuid = args.project_uuid
    else:
        project_uuid = deterministic_project_uuid(args.case_name)

    print(f"# FACT Graph Research: {args.case_name}")
    print(f"**Project UUID:** {project_uuid}\n")

    try:
        driver = load_neo4j_fact_driver()
        output_parts = []

        with driver.session() as session:
            # Execute appropriate query
            if args.search_terms:
                results = search_chunks(session, project_uuid, args.search_terms, args.limit)
                output_parts.append(format_search_results(results))

            if args.exhibit_name:
                results = get_exhibit_content(session, project_uuid, args.exhibit_name)
                output_parts.append(format_exhibit_results(results, args.exhibit_name))

            if args.entity_name:
                results = track_entity(session, project_uuid, args.entity_name, args.limit)
                output_parts.append(format_entity_results(results))

            if args.find_contradictions and args.search_terms:
                results = find_contradictions(session, project_uuid, args.search_terms, args.limit)
                output_parts.append(format_contradiction_results(results))

            if args.build_timeline:
                results = build_timeline(session, project_uuid)
                output_parts.append(format_timeline_results(results))

            # Combine output
            final_output = "\n".join(output_parts)

            # Write output
            if args.output:
                Path(args.output).write_text(final_output)
                print(f"✓ Results written to {args.output}")
            else:
                print(final_output)

        driver.close()
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
