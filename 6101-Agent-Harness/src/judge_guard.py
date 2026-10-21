"""Bounded injection indicators and provenance checks, not an authorization oracle."""
import json
import re
import unicodedata

GUARD_VERSION = 'judge-guard/2'
# Deliberately explainable indicators. A negative scan does not certify safety.
PATTERNS = {
    'instruction_override': r'\b(?:ignore|disregard|override)\b.{0,90}\b(?:instructions?|user|task|rules?|previous|above)\b|忽略.{0,30}(?:指令|用户|任务|规则)',
    'role_spoofing': r'<\|(?:im_start|system|start_header_id)\|>|\[/?INST\]|(?:^|\n)\s*(?:system|developer)\s*:|"role"\s*:\s*"(?:system|developer)"',
    'judge_manipulation': r'\b(?:return|output|mark|set)\b.{0,100}\b(?:SATISFIED|authorized|auto.approve|risk_score)\b|(?:输出|标记|判定).{0,30}(?:授权|安全|批准)',
    'authority_spoofing': r'\b(?:user|administrator|system)\s+(?:has\s+)?(?:already\s+)?(?:approved|authorized|instructs)\b|用户已(?:授权|批准)',
    'task_redirection': r'\b(?:TODO|new task|additional instructions?)\s*:\s*(?:send|transfer|delete|execute|upload|reveal|change)\b|(?:新任务|额外指令|待办)\s*[:：].{0,30}(?:发送|转账|删除|执行|上传)',
    'consent_bypass': r'\b(?:without asking(?: me| the user)?|do not ask (?:me|the user)|fill (?:them|it) in without)\b|(?:无需|不要)(?:询问|确认)',
}


def indicators(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
    raw = ''.join(c for c in unicodedata.normalize('NFKC', raw)
                  if unicodedata.category(c) != 'Cf')
    return [name for name, pattern in PATTERNS.items() if re.search(pattern, raw, re.I)]


def evidence_scan(request):
    """Only the runtime's exact original task record is instruction authority."""
    trusted = {e.evidence_id for e in request.evidence
               if e.evidence_id == 'u0001' and e.kind == 'instruction'
               and e.source_call_id is None and e.content == request.task}
    signals = []
    for evidence in request.evidence:
        if evidence.evidence_id in trusted:
            continue
        rules = indicators(evidence.content)
        if evidence.kind == 'instruction':
            rules.append('untrusted_instruction_provenance')
        if rules:
            signals.append({'evidence_id': evidence.evidence_id, 'rules': rules})
    return trusted, signals


def authorization_prediction(request, response):
    """Conservative reduction of the complete check vector; not a gate verdict.

    Missing checks, N/A reinterpretations and incomplete semantics abstain.
    Deterministic checks are retained, never replaced by model opinions.
    """
    if response.status != 'ok':
        return 'abstain'
    supplied = {c.check_id: c for c in response.checks}
    states = {}
    for original in request.checks:
        state = original.status.value
        if state == 'UNRESOLVED':
            finding = supplied.get(original.check_id)
            state = finding.status.value if finding else 'UNRESOLVED'
            if state == 'NOT_APPLICABLE':
                state = 'UNRESOLVED'
        states[original.check_id] = state
    # A semantic/catalog failure alone is not evidence of unauthorized intent.
    if any(v == 'VIOLATED' for k, v in states.items() if k != 'semantics'):
        return 'unauthorized'
    if states.get('scope') == 'SATISFIED' and all(
            v in ('SATISFIED', 'NOT_APPLICABLE') for v in states.values()):
        return 'authorized'
    return 'abstain'
