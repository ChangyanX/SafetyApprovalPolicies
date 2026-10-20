"""Small whole-task grammar, not a general natural-language authorization parser.

Every pattern is anchored via fullmatch. JSON-quoted strings preserve payload
boundaries. Extra sentences, negation, conditions and delegated lookups fall back
to UNRESOLVED. These formats are never substituted for benchmark prompts.
"""
import json
import re

Q = r'"(?:[^"\\\x00-\x1f]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"'


def literal_action(suite, task):
    patterns = {
        'workspace': [(rf'Read file with ID ({Q})\.', 'get_file_by_id', ['file_id'])],
        'travel': [(rf'Get all hotels in ({Q})\.', 'get_all_hotels_in_city', ['city'])],
        'banking': [
            (r'Get my current balance\.', 'get_balance', []),
            (rf'Read file ({Q})\.', 'read_file', ['file_path']),
            (rf'Send ([0-9]+(?:\.[0-9]+)?) to ({Q}) with subject ({Q}) on ({Q})\.',
             'send_money', ['amount','recipient','subject','date'])],
        'slack': [(rf'Send a direct message to ({Q}) with body ({Q})\.',
                   'send_direct_message', ['recipient','body'])],
    }
    for pattern, tool, fields in patterns.get(suite, []):
        match = re.fullmatch(pattern, task)
        if match:
            return dict(tool=tool,args=dict(zip(fields,map(json.loads,match.groups()))),max_executions=1)
    return None
