import copy
import pytest
from collaborator_drive.registry import validate, grant_for, effective_grants, Uncertain, Denied
from collaborator_drive.guard import authorize
from collaborator_drive.gate import dispatch


def delegated(registry):
    base=registry['collaborators'][0]
    route={key:copy.deepcopy(base[key]) for key in ('venture','approved_drive_folder_ids','allowed_actions','exclusions','resource_scope','status','approving_founder','approval_source')}
    route.update(founder='founder-test',approved_chats=[{'platform':'test-platform','chat_id':'content-test'}])
    registry['scoped_founder_routes']=[route]
    validate(registry)
    return {'platform':'test-platform','user_id':'owner-test','chat_id':'content-test','chat_type':'group'}


def test_founder_service_route_has_no_personal_acl_dependency(registry,drive):
    source=delegated(registry)
    drive.acl=[]
    drive.items['document_test_id']['capabilities']={'canDownload':True,'canEdit':True}
    assert authorize(registry,drive,source,'test-project','draft','document_test_id','read')['id']=='document_test_id'
    assert grant_for(registry,source,'test-project')['_scope_kind']=='founder_service'
    assert not effective_grants(registry,dict(source,chat_id='other-group'))
    assert not effective_grants(registry,dict(source,user_id='unknown'))


def test_service_route_does_not_change_collaborator_access_basis(registry,source,drive):
    delegated(registry)
    drive.acl=[]
    drive.items['document_test_id']['capabilities']={'canDownload':True,'canEdit':True}
    registry['collaborators'][0]['_scope_kind']='founder_service'
    with pytest.raises(Uncertain):authorize(registry,drive,source,'test-project','draft','document_test_id','read')


def test_founder_service_still_requires_boundary_action_and_current_capability(registry,drive):
    source=delegated(registry)
    drive.items['document_test_id']['capabilities']={'canDownload':False}
    with pytest.raises(Uncertain):authorize(registry,drive,source,'test-project','draft','document_test_id','read')
    drive.items['document_test_id']['capabilities']={'canDownload':True}
    for target,action in [('private_test_id','draft'),('document_test_id','publishing')]:
        with pytest.raises(Denied):authorize(registry,drive,source,'test-project',action,target,'read')
    with pytest.raises(Uncertain):authorize(registry,drive,source,'test-project','paper_edit','document_test_id','edit')


def test_delegated_group_cannot_reach_privileged_context(registry,drive,tmp_path):
    source=delegated(registry);tmp_path.chmod(0o700)
    drive.items['document_test_id']['capabilities']={'canDownload':True}
    def worker(text,executor,config):
        executor.execute({'operation':'inspect','target':'document_test_id','action':'draft','body':''})
        return 'PRIVATE FOUNDER HISTORY'
    frame={'version':1,'kind':'message','source':source,'text':'inspect','message_id':'synthetic'}
    result=dispatch(frame,lambda:registry,{},tmp_path,lambda:drive,worker)
    assert result['decision']=='deny' and 'read-only work completed' in result['reply']
    assert 'PRIVATE' not in result['reply']
    registry['scoped_founder_routes'][0]['founder']='not-verified'
    with pytest.raises(Uncertain):validate(registry)
