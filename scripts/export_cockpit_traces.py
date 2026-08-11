#!/usr/bin/env python

from __future__ import annotations

import argparse
from pathlib import Path

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings
from fastapi.testclient import TestClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Create one export per session.")
    parser.add_argument("--db-path", default="outputs/cockpit/phase3.sqlite3")
    parser.add_argument("--artifact-root", default="outputs/cockpit/artifacts")
    args = parser.parse_args()

    settings = build_settings(db_path=Path(args.db_path), artifact_root=Path(args.artifact_root))

    # Direct reuse of API call pattern keeps export logic consistent with HTTP surface.
    client = TestClient(create_app(settings))
    response = client.get('/api/sessions')
    sessions = response.json()
    for session in sessions:
        session_id = session['session_id']
        payload = {
            'session_id': session_id,
            'turn_ids': None,
            'redaction_mode': 'snippets_hashed',
            'include_turns': True,
            'include_data_sources': True,
            'include_artifacts': True,
        }
        response = client.post('/api/exports', json=payload)
        if response.status_code != 200:
            raise RuntimeError(f'export for {session_id} failed: {response.status_code} {response.text}')


if __name__ == "__main__":
    main()
