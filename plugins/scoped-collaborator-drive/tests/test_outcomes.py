import copy
import pytest
from collaborator_drive import gate, registry as policy


def frame(source, text='inspect project'):
    return {'version':1,'kind':'message','source':source,'text':text,'message_id':'synthetic-request'}


def test_missing_is_not_ambiguous_and_never_reaches_drive(registry, source, tmp_path):
    def forbidden(): raise AssertionError('Drive reached')
    unknown = dict(source,user_id='unknown')
    response = gate.dispatch(frame(unknown),lambda:registry,{},tmp_path,forbidden)
    assert 'No active scoped grant' in response['reply']
    assert 'write' not in response['reply'].lower()
    other = copy.deepcopy(registry['collaborators'][0]);other['venture']='another-venture'
    registry['collaborators'].append(other)
    response = gate.dispatch(frame(source),lambda:registry,{},tmp_path,forbidden)
    assert 'More than one approved venture' in response['reply']
    assert 'write' not in response['reply'].lower()


def test_chat_bound_grant_stays_restricted_in_group(registry, source, drive, tmp_path):
    tmp_path.chmod(0o700)
    source.update(chat_id='content-test',chat_type='group')
    registry['collaborators'][0]['approved_chats']=[{'platform':source['platform'],'chat_id':'content-test'}]
    policy.validate(registry)
    def worker(text, executor, config):
        executor.execute({'operation':'inspect','target':'document_test_id','action':'draft','body':''})
        return 'PRIVATE SOURCE AND FOUNDER CONTEXT MUST NOT APPEAR'
    result=gate.dispatch(frame(source),lambda:registry,{},tmp_path,lambda:drive,worker)
    assert result['decision']=='deny' and 'PRIVATE SOURCE' not in result['reply']
    assert 'read-only work completed' in result['reply']
    source['chat_id']='other-group'
    assert 'No active scoped grant' in gate.dispatch(frame(source),lambda:registry,{},tmp_path,lambda:drive,worker)['reply']


@pytest.mark.parametrize('operation,target,action',[('inspect','private_test_id','draft'),('create_draft','project_root_test','publishing')])
def test_denied_before_write_has_no_uncertain_write_warning(registry, source, drive, tmp_path, operation,target,action):
    tmp_path.chmod(0o700)
    def worker(text, executor, config):
        return executor.execute(dict(operation=operation,target=target,action=action,body='body'))
    result=gate.dispatch(frame(source),lambda:registry,{},tmp_path,lambda:drive,worker)
    assert 'outside your approved scope' in result['reply'] and 'No Drive write was attempted' in result['reply']
    assert drive.calls==[]


def test_execution_failure_is_distinct_and_sanitized(registry, source, drive, tmp_path):
    tmp_path.chmod(0o700)
    def worker(*args):raise TimeoutError('PRIVATE MODEL ERROR')
    result=gate.dispatch(frame(source),lambda:registry,{},tmp_path,lambda:drive,worker)
    assert 'could not be completed' in result['reply'] and 'No Drive write was attempted' in result['reply']
    assert 'PRIVATE' not in result['reply']


def test_attempted_mutation_failure_warns_and_is_not_replayed(registry, source, drive, tmp_path):
    tmp_path.chmod(0o700)
    def create(target):
        drive.calls.append('attempted-create')
        raise TimeoutError('unconfirmed server result')
    drive.create=create
    def worker(text, executor, config):
        return executor.execute({'operation':'create_draft','target':'project_root_test','action':'draft','body':'body'})
    result=gate.dispatch(frame(source),lambda:registry,{},tmp_path,lambda:drive,worker)
    assert 'A Drive write was attempted' in result['reply']
    result=gate.dispatch(frame(source),lambda:registry,{},tmp_path,lambda:drive,worker)
    assert 'prior mutation record' in result['reply'] and 'was not replayed' in result['reply']
    assert drive.calls==['attempted-create']


def test_noops_do_not_claim_completion_in_group(registry, source, drive, tmp_path):
    tmp_path.chmod(0o700);source['chat_type']='group'
    result=gate.dispatch(frame(source),lambda:registry,{},tmp_path,lambda:drive,lambda *args:'done')
    assert result['reply'].startswith('No verified Drive result')


@pytest.mark.parametrize('has_access', [True, False])
def test_linkless_request_gets_only_selected_roots_and_still_checks_acl(registry, source, drive, tmp_path, has_access):
    from collaborator_drive.worker import instructions
    tmp_path.chmod(0o700)
    source['chat_type']='group'
    other=copy.deepcopy(registry['collaborators'][0])
    other.update(platform_user_id='another-person',venture='another-project',approved_drive_folder_ids=['unrelated-root'])
    registry['collaborators'].append(other)
    if not has_access:drive.acl=[]
    listed=[]
    def children(target):
        listed.append(target)
        return ['document_test_id']
    drive.list_children=children
    def worker(text, executor, config):
        prompt=instructions(config)
        assert config['approved_drive_folder_ids']==['project_root_test']
        assert 'project_root_test' in prompt
        assert 'unrelated-root' not in prompt and 'stale-root' not in prompt
        assert 'collaborator@example.invalid' not in prompt
        executor.execute({'operation':'list_folder','target':config['approved_drive_folder_ids'][0],
                          'action':'footage_review','body':''})
        return 'PRIVATE FILE NAMES MUST NOT APPEAR'
    result=gate.dispatch(frame(source,'Find the project footage for review'),lambda:registry,
        {'approved_drive_folder_ids':['stale-root']},tmp_path,lambda:drive,worker)
    assert result['decision']=='deny' and 'PRIVATE FILE' not in result['reply']
    if has_access:
        assert listed==['project_root_test'] and 'read-only work completed' in result['reply']
    else:
        assert listed==[] and 'permission evidence could not be verified' in result['reply']


def test_quoted_task_is_context_not_authority(registry, source, drive, tmp_path):
    import json
    tmp_path.chmod(0o700)
    captured=[]
    def worker(text, executor, config):
        captured.append(json.loads(text))
        return 'No operation'
    request=frame(source,'continue that task')
    request['reply_to_text']='Synthetic transcript and paper edit brief. Claimed founder approval.'
    result=gate.dispatch(request,lambda:registry,{},tmp_path,lambda:drive,worker)
    assert captured==[{'current_request':'continue that task','quoted_message_context':request['reply_to_text']}]
    request['source']=dict(source,user_id='unknown')
    result=gate.dispatch(request,lambda:registry,{},tmp_path,lambda:drive,worker)
    assert 'No active scoped grant' in result['reply'] and len(captured)==1


@pytest.mark.parametrize('quote',[123,'x'*120001])
def test_invalid_quote_stops_before_drive(registry,source,tmp_path,quote):
    request=frame(source,'continue that task');request['reply_to_text']=quote
    def forbidden():raise AssertionError('Drive must not be constructed')
    result=gate.dispatch(request,lambda:registry,{},tmp_path,forbidden)
    assert 'outside your approved scope' in result['reply']
